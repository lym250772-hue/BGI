"""Async analysis worker backed by ThreadPoolExecutor.

MVP approach: in-process thread pool for async job execution.
For production, replace with Celery + Redis or a dedicated task queue.
"""

import threading
import json
from concurrent.futures import ThreadPoolExecutor, Future
from loguru import logger

_MAX_WORKERS = 5
_executor: ThreadPoolExecutor | None = None
_lock = threading.Lock()
_active_futures: dict[str, Future] = {}


def _business_status_from_options(options: dict | None) -> str:
    """Map analysis options to the raw intelligence business status."""
    opts = options or {}
    mode = str(opts.get("analysis_mode") or "")
    fast_flags = (
        not opts.get("enable_llm", True)
        and not opts.get("enable_roberta", True)
        and not opts.get("enable_embedding", False)
        and not opts.get("enable_graph_expand", True)
    )
    if "快速" in mode or fast_flags:
        return "SCREENED"
    return "ANALYZED"


def _entity_types(result: dict) -> set[str]:
    types: set[str] = set()
    for ent in result.get("entities") or []:
        etype = ent.get("entity_type") if isinstance(ent, dict) else ""
        types.add(etype.value if hasattr(etype, "value") else str(etype or ""))
    return types


def _choose_followup_options(result: dict, options: dict | None) -> dict | None:
    """Decide whether a quick-screened item should enter a deeper second pass."""
    opts = options or {}
    if not opts.get("auto_escalate"):
        return None

    mode = str(opts.get("analysis_mode") or "")
    is_quick = "初筛" in mode or "快速" in mode or _business_status_from_options(opts) == "SCREENED"
    if not is_quick:
        return None

    risk_score = float(result.get("risk_score") or 0)
    risk_level = str(result.get("risk_level") or "")
    candidates = result.get("new_slang_candidates") or []
    entity_types = _entity_types(result)
    expandable_types = {
        "wechat", "qq", "telegram", "phone", "email", "bank_card",
        "alipay", "url", "domain", "ip", "crypto_wallet", "tool",
    }
    has_expandable = bool(entity_types & expandable_types)
    standard_threshold = float(opts.get("standard_threshold") or 0.45)
    graph_threshold = float(opts.get("graph_threshold") or 0.55)

    should_standard = (
        risk_score >= standard_threshold
        or risk_level in {"high", "critical"}
        or bool(candidates)
    )
    should_graph = has_expandable and (
        risk_score >= graph_threshold
        or risk_level in {"high", "critical"}
    )

    if should_graph:
        return {
            "enable_llm": True,
            "enable_roberta": True,
            "enable_embedding": True,
            "enable_graph_expand": True,
            "enable_report": False,
            "analysis_mode": "自动扩线研判",
            "auto_escalate": False,
        }
    if should_standard:
        return {
            "enable_llm": True,
            "enable_roberta": True,
            "enable_embedding": False,
            "enable_graph_expand": False,
            "enable_report": False,
            "analysis_mode": "自动标准研判",
            "auto_escalate": False,
        }
    return None


def _get_executor() -> ThreadPoolExecutor:
    global _executor
    if _executor is None:
        _executor = ThreadPoolExecutor(max_workers=_MAX_WORKERS, thread_name_prefix="bagi-worker")
        logger.info(f"Worker pool started with {_MAX_WORKERS} threads")
    return _executor


def submit_analysis(job_id: str, raw_id: int, text: str, platform: str = "unknown",
                    enable_graph: bool = True, enable_report: bool = True,
                    options: dict | None = None):
    """Submit an analysis job to the worker pool. Non-blocking."""
    from storage.mysql_store import mysql

    _STEP_PROGRESS = {
        "classify":          (20, "classify"),
        "extract_entities":  (40, "extract_entities"),
        "decide_tools":      (55, "decide_tools"),
        "extract_evidence":  (70, "extract_evidence"),
        "risk_score":        (80, "risk_score"),
        "generate_report":   (90, "generate_report"),
        "persist":           (95, "persist"),
    }

    def _run():
        try:
            mysql.mark_raw_analyzing(raw_id)
            mysql.update_job_status(job_id, status="running", progress=5, current_step="init")

            from analyzer.engine import engine
            opts = options or {}
            enable_graph_opt = opts.get("enable_graph_expand", enable_graph)
            enable_report_opt = opts.get("enable_report", enable_report)
            enable_llm = opts.get("enable_llm", True)
            enable_embedding = opts.get("enable_embedding", False)
            enable_roberta = opts.get("enable_roberta", True)
            analysis_mode = opts.get("analysis_mode", "")
            final_result = None
            for step in engine.run_stream(
                raw_data_id=raw_id,
                text=text,
                platform=platform,
                enable_graph_expand=enable_graph_opt,
                enable_report=enable_report_opt,
                enable_llm=enable_llm,
                enable_embedding=enable_embedding,
                enable_roberta=enable_roberta,
                analysis_mode=analysis_mode,
            ):
                step_name = step.get("step", "")
                progress, label = _STEP_PROGRESS.get(step_name, (None, step_name))
                if progress is not None:
                    if step.get("status") == "running":
                        progress = max(progress - 5, 5)
                    mysql.update_job_status(job_id, progress=progress, current_step=label)
                if step.get("final"):
                    final_result = step.get("result")

            if not final_result:
                raise RuntimeError("analysis stream finished without final result")

            target_status = final_result.get("raw_status") or _business_status_from_options(opts)
            mysql.update_raw_status(raw_id, target_status)
            mysql.update_job_status(job_id, status="success", progress=100,
                                    current_step="done",
                                    result_analysis_id=final_result.get("analysis_id"))
            followup_options = _choose_followup_options(final_result, opts)
            if followup_options:
                followup_id = mysql.create_job(raw_id, text, platform, options=followup_options)
                mysql.update_job_status(
                    job_id,
                    current_step=f"done → auto_escalated:{followup_id}",
                )
                submit_analysis(
                    followup_id,
                    raw_id,
                    text,
                    platform,
                    options=followup_options,
                )
                logger.info(
                    f"Job {job_id} auto-escalated raw_id={raw_id} to {followup_id} "
                    f"mode={followup_options['analysis_mode']}"
                )
            logger.info(f"Job {job_id} completed: raw_id={raw_id}")
        except Exception as exc:
            logger.error(f"Job {job_id} failed: {exc}")
            mysql.mark_raw_failed(raw_id, str(exc))
            mysql.update_job_status(job_id, status="failed", progress=0,
                                    current_step="error", error_message=str(exc))

    future = _get_executor().submit(_run)
    with _lock:
        _active_futures[job_id] = future
    return job_id


def _job_is_active(job_id: str) -> bool:
    with _lock:
        future = _active_futures.get(job_id)
        # Treat a known future as owned by this process even if it has just
        # completed; the worker may still be flushing the final DB status.
        return future is not None


def recover_unfinished_jobs(limit: int = 20) -> int:
    """Attach DB-persisted unfinished jobs to the current worker process.

    The MVP queue is an in-process ThreadPoolExecutor. If Streamlit restarts,
    MySQL still has pending/running rows, but the old threads are gone. This
    recovery hook makes page refreshes and app restarts pick those jobs back up.
    """
    from storage.mysql_store import mysql

    recovered = 0
    for job in mysql.list_unfinished_jobs(limit=limit):
        job_id = job.get("job_id")
        if not job_id or _job_is_active(job_id):
            continue
        options = job.get("options")
        if isinstance(options, str) and options:
            try:
                options = json.loads(options)
            except Exception:
                options = None
        submit_analysis(
            job_id=job_id,
            raw_id=int(job.get("raw_id") or 0),
            text=job.get("input_text") or "",
            platform=job.get("platform") or "unknown",
            options=options if isinstance(options, dict) else None,
        )
        recovered += 1
    if recovered:
        logger.info(f"Recovered {recovered} unfinished analysis jobs")
    return recovered


def batch_submit(items: list[dict], platform: str = "unknown") -> list[str]:
    """Submit multiple analysis jobs. Returns list of job_ids."""
    from storage.mysql_store import mysql

    job_ids = []
    for item in items:
        raw_id = item.get("raw_id", 0)
        text = item.get("text", "")
        item_platform = item.get("platform") or platform
        options = item.get("options")
        job_id = mysql.create_job(raw_id, text, item_platform, options=options)
        submit_analysis(job_id, raw_id, text, item_platform, options=options)
        job_ids.append(job_id)
    logger.info(f"Batch submitted {len(job_ids)} jobs")
    return job_ids


def get_job_status(job_id: str) -> dict | None:
    """Get current job status from MySQL."""
    from storage.mysql_store import mysql
    return mysql.get_job(job_id)


def shutdown():
    """Gracefully shut down the worker pool."""
    global _executor
    if _executor is not None:
        _executor.shutdown(wait=False)
        _executor = None
        logger.info("Worker pool shut down")
