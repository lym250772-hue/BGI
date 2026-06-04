"""FastAPI REST API for BGI Intelligence Analysis Agent.

Endpoints:
    /health                            — health check
    /api/stats                         — dashboard stats
    /api/intel                         — list intel items
    /api/intel/{raw_id}                — single intel detail
    /api/entities                      — list entities
    /api/entities/{entity_id}/graph    — Neo4j subgraph around an entity
    /api/slang                         — list slang dictionary
    /internal/v1/agent/analyze         — Agent analysis (PROJECT_PLAN 8.1 contract)
"""

from fastapi import FastAPI, Query, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Optional, Any
from datetime import datetime
from loguru import logger

app = FastAPI(title="BGI Intelligence API", version="0.2.0")
app.add_middleware(
    CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"]
)


# ============================================================================
# Response models
# ============================================================================

class StatsResponse(BaseModel):
    today_total: int = 0
    high_priority: int = 0
    risk_distribution: dict = {}
    entities_total: int = 0
    pending_count: int = 0
    today_count: int = 0
    high_risk_count: int = 0
    entity_count: int = 0
    label_distribution: dict = {}
    recent_items: list = []


class IntelItem(BaseModel):
    id: int
    source_platform: str = ""
    content: str = ""
    content_type: str = "text"
    priority: str = "normal"
    status: str = "pending"
    collected_at: Optional[datetime] = None
    intent_label: Optional[str] = None
    sub_label: Optional[str] = None
    confidence: Optional[float] = None


class EntityItem(BaseModel):
    id: int
    entity_type: str
    entity_value: str
    extraction_method: str = ""
    first_seen: Optional[datetime] = None


# ============================================================================
# Agent Analyze — PROJECT_PLAN.md Section 8.1 contract
# ============================================================================

class AnalyzeOptions(BaseModel):
    enable_graph_expand: bool = True
    enable_report: bool = True
    enable_llm: bool = True


class AnalyzeRequest(BaseModel):
    raw_id: int
    platform: str = "unknown"
    text: str
    metadata: Optional[dict] = None
    options: Optional[AnalyzeOptions] = None


class EvidenceSpanDTO(BaseModel):
    text: str
    start: int = 0
    end: int = 0
    risk_point: str = ""
    reason: str = ""
    confidence: float = 0.0
    method: str = ""


class EntityDTO(BaseModel):
    entity_type: str
    entity_value: str
    context: str = ""
    confidence: float = 0.0
    extraction_method: str = ""


class SlangTermDTO(BaseModel):
    term: str
    meaning: str = ""
    risk_category: str = ""
    source: str = ""


class NewSlangCandidateDTO(BaseModel):
    term: str
    suggested_meaning: str = ""
    risk_category: str = ""
    confidence: float = 0.0
    evidence: str = ""
    reason: str = ""
    source: str = ""


class AnalyzeResponse(BaseModel):
    raw_id: int
    clean_text: str = ""
    risk_label: str = ""
    risk_sub_label: str = ""
    risk_score: float = 0.0
    risk_level: str = "normal"
    evidence_spans: list[dict] = []
    entities: list[dict] = []
    slang_terms: list[dict] = []
    new_slang_candidates: list[dict] = []
    graph_result: dict = {}
    agent_summary: str = ""
    disposal_advice: list[dict] = []
    training_sample: dict = {}


# ============================================================================
# Routes — Health
# ============================================================================

@app.get("/health")
def health():
    return {"status": "ok", "timestamp": datetime.now().isoformat()}


# ============================================================================
# Routes — Agent Analyze (P0: core API)
# ============================================================================

@app.post("/internal/v1/agent/analyze", response_model=AnalyzeResponse)
def agent_analyze(req: AnalyzeRequest):
    """Run full analysis pipeline on a single intel item.

    PROJECT_PLAN.md Section 8.1 contract:
        POST /internal/v1/agent/analyze
        Request:  {raw_id, platform, text, metadata, options}
        Response: {raw_id, risk_label, risk_score, evidence_spans, entities,
                   slang_terms, graph_result, agent_summary, disposal_advice}
    """
    opts = req.options or AnalyzeOptions()
    try:
        from storage.mysql_store import mysql
        from analyzer.engine import engine
        mysql.mark_raw_analyzing(req.raw_id)
        result = engine.run(
            raw_data_id=req.raw_id,
            text=req.text,
            platform=req.platform,
            enable_graph_expand=opts.enable_graph_expand,
            enable_report=opts.enable_report,
            enable_llm=opts.enable_llm,
        )

        return AnalyzeResponse(
            raw_id=result["raw_id"],
            clean_text=result["clean_text"],
            risk_label=result["risk_label"],
            risk_sub_label=result["risk_sub_label"],
            risk_score=result["risk_score"],
            risk_level=result["risk_level"],
            evidence_spans=result.get("evidence_spans", []),
            entities=result.get("entities", []),
            slang_terms=result.get("slang_terms", []),
            new_slang_candidates=result.get("new_slang_candidates", []),
            graph_result=result.get("graph_result", {}),
            agent_summary=result.get("agent_summary", ""),
            disposal_advice=result.get("disposal_advice", []),
            training_sample={},
        )
    except Exception as exc:
        logger.error(f"Agent analyze failed for raw_id={req.raw_id}: {exc}")
        try:
            from storage.mysql_store import mysql
            mysql.mark_raw_failed(req.raw_id, str(exc))
        except Exception as status_exc:
            logger.warning(f"Failed to mark raw_id={req.raw_id} as FAILED: {status_exc}")
        raise HTTPException(
            status_code=500,
            detail=f"Agent analyze failed for raw_id={req.raw_id}: {exc}",
        ) from exc


# ============================================================================
# Routes — Async Analysis Jobs
# ============================================================================

class JobSubmitRequest(BaseModel):
    raw_id: int
    text: str
    platform: str = "unknown"
    options: Optional[AnalyzeOptions] = None


class BatchJobRequest(BaseModel):
    items: list[JobSubmitRequest]
    platform: str = "unknown"


@app.post("/api/analysis/jobs")
def submit_job(req: JobSubmitRequest):
    """Submit a single analysis job. Returns job_id for polling."""
    try:
        from storage.mysql_store import mysql
        from analyzer.worker import submit_analysis

        options = req.options.model_dump() if req.options else None
        job_id = mysql.create_job(req.raw_id, req.text, req.platform, options=options)
        submit_analysis(job_id, req.raw_id, req.text, req.platform, options=options)
        return {"job_id": job_id, "status": "pending"}
    except Exception as exc:
        logger.error(f"Job submission failed: {exc}")
        return {"error": str(exc)}


@app.post("/api/analysis/jobs/batch")
def submit_batch_jobs(req: BatchJobRequest):
    """Submit multiple analysis jobs. Returns list of job_ids."""
    try:
        from analyzer.worker import batch_submit
        items = [
            {
                "raw_id": it.raw_id,
                "text": it.text,
                "platform": it.platform or req.platform,
                "options": it.options.model_dump() if it.options else None,
            }
            for it in req.items
        ]
        job_ids = batch_submit(items, req.platform)
        return {"job_ids": job_ids, "count": len(job_ids)}
    except Exception as exc:
        logger.error(f"Batch job submission failed: {exc}")
        return {"error": str(exc)}


@app.get("/api/analysis/jobs/{job_id}")
def get_job(job_id: str):
    """Get job status and result. Poll this to track progress."""
    try:
        from analyzer.worker import get_job_status
        job = get_job_status(job_id)
        if not job:
            return {"error": "Job not found"}
        return dict(job)
    except Exception as exc:
        return {"error": str(exc)}


@app.get("/api/analysis/jobs")
def list_jobs(status: Optional[str] = Query(default=None), limit: int = Query(default=50)):
    """List recent analysis jobs."""
    try:
        from storage.mysql_store import mysql
        jobs = mysql.list_jobs(status=status, limit=limit)
        return {"total": len(jobs), "items": jobs}
    except Exception as exc:
        return {"total": 0, "items": [], "error": str(exc)}


# ============================================================================
# Routes — Stats
# ============================================================================

@app.get("/api/stats", response_model=StatsResponse)
def get_stats():
    """Get dashboard statistics. Matches daily_stats() return fields."""
    try:
        from storage.mysql_store import mysql
        stats = mysql.daily_stats()
        return StatsResponse(
            today_total=stats.get("today_count", 0),
            today_count=stats.get("today_count", 0),
            high_priority=stats.get("high_risk_count", 0),
            high_risk_count=stats.get("high_risk_count", 0),
            risk_distribution=stats.get("label_distribution", {}),
            label_distribution=stats.get("label_distribution", {}),
            entities_total=stats.get("entity_count", 0),
            entity_count=stats.get("entity_count", 0),
            pending_count=stats.get("pending_count", 0),
            recent_items=stats.get("recent_items", []),
        )
    except Exception as exc:
        logger.error(f"Stats failed: {exc}")
        return StatsResponse()


# ============================================================================
# Routes — Intel
# ============================================================================

@app.get("/api/intel")
def list_intel(
    status: str = Query(default="ANALYZED"),
    platform: Optional[str] = Query(default=None),
    priority: Optional[str] = Query(default=None),
    intent: Optional[str] = Query(default=None),
    limit: int = Query(default=50, le=500),
    offset: int = Query(default=0),
):
    """List intelligence items with optional filters."""
    try:
        from storage.mysql_store import mysql
        rows = mysql.list_raw(
            status=status, platform=platform, priority=priority,
            limit=limit, offset=offset,
        )
        for row in rows:
            with mysql.cursor() as c:
                c.execute(
                    """SELECT risk_label, risk_sub_label, risk_score
                       FROM dwd_intel_analysis
                       WHERE raw_id=%s ORDER BY created_at DESC LIMIT 1""",
                    (row["id"],),
                )
                ar = c.fetchone()
                if ar:
                    row["intent_label"] = ar["risk_label"]
                    row["sub_label"] = ar["risk_sub_label"]
                    row["confidence"] = ar["risk_score"]
        return {"total": len(rows), "items": rows}
    except Exception as exc:
        logger.error(f"List intel failed: {exc}")
        return {"total": 0, "items": [], "error": str(exc)}


@app.get("/api/intel/{raw_id}")
def get_intel_detail(raw_id: int):
    """Get full detail for a single intel item including analysis + entities."""
    try:
        from storage.mysql_store import mysql
        intel = mysql.get_raw_by_id(raw_id)
        if not intel:
            return {"error": "Not found"}

        with mysql.cursor() as c:
            c.execute(
                """SELECT * FROM dwd_intel_analysis
                   WHERE raw_id=%s AND is_latest=1
                   ORDER BY created_at DESC LIMIT 1""",
                (raw_id,),
            )
            analysis = c.fetchone()
            c.execute(
                "SELECT * FROM dwd_entity WHERE raw_id=%s ORDER BY first_seen DESC",
                (raw_id,),
            )
            entities = c.fetchall()
            c.execute(
                "SELECT * FROM agent_report WHERE raw_id=%s ORDER BY created_at DESC LIMIT 1",
                (raw_id,),
            )
            report = c.fetchone()

        return {
            "intel": intel,
            "analysis": analysis,
            "entities": entities,
            "report": report,
        }
    except Exception as exc:
        return {"error": str(exc)}


# ============================================================================
# Routes — Entities
# ============================================================================

@app.get("/api/entities")
def list_entities(
    entity_type: Optional[str] = Query(default=None),
    limit: int = Query(default=100, le=500),
    offset: int = Query(default=0),
):
    """List extracted entities."""
    try:
        from storage.mysql_store import mysql
        with mysql.cursor() as c:
            if entity_type:
                c.execute(
                    "SELECT * FROM dwd_entity WHERE entity_type=%s ORDER BY first_seen DESC LIMIT %s OFFSET %s",
                    (entity_type, limit, offset),
                )
            else:
                c.execute(
                    "SELECT * FROM dwd_entity ORDER BY first_seen DESC LIMIT %s OFFSET %s",
                    (limit, offset),
                )
            items = c.fetchall()

            c.execute("SELECT COUNT(*) as cnt FROM dwd_entity")
            total = c.fetchone()["cnt"]

        return {"total": total, "items": items}
    except Exception as exc:
        logger.error(f"List entities failed: {exc}")
        return {"total": 0, "items": [], "error": str(exc)}


@app.get("/api/entities/{entity_id}/graph")
def entity_graph(entity_id: int):
    """Get the Neo4j subgraph around an entity."""
    try:
        from storage.mysql_store import mysql
        with mysql.cursor() as c:
            c.execute("SELECT * FROM dwd_entity WHERE id=%s", (entity_id,))
            ent = c.fetchone()
        if not ent:
            return {"error": "Entity not found"}
        from storage.neo4j_store import neo4j
        results = neo4j.find_entity_neighborhood(
            ent["entity_type"], ent["entity_value"]
        )
        return {"entity": ent, "neighborhood": results}
    except Exception as exc:
        return {"error": str(exc)}


# ============================================================================
# Routes — Slang, Cheat Scripts
# ============================================================================

@app.get("/api/slang")
def list_slang(status: str = Query(default="active")):
    """List slang dictionary entries."""
    try:
        from storage.mysql_store import mysql
        rows = mysql.list_slang(status=None if status == "all" else status)
        return {"total": len(rows), "items": rows}
    except Exception as exc:
        return {"total": 0, "items": [], "error": str(exc)}


class SlangCandidateReviewRequest(BaseModel):
    term: str
    meaning: str = ""
    category: str = ""
    reviewer: str = "analyst"
    reason: str = ""


@app.get("/api/slang/candidates")
def list_slang_candidates(raw_id: Optional[int] = Query(default=None)):
    """List pending model-discovered slang candidates."""
    try:
        from storage.mysql_store import mysql
        rows = mysql.list_slang_candidates(raw_id=raw_id)
        return {"total": len(rows), "items": rows}
    except Exception as exc:
        return {"total": 0, "items": [], "error": str(exc)}


@app.post("/api/slang/candidates/approve")
def approve_slang_candidate(req: SlangCandidateReviewRequest):
    """Promote a pending slang candidate into the active dictionary."""
    try:
        from storage.mysql_store import mysql
        ok = mysql.approve_slang_candidate(
            term=req.term,
            meaning=req.meaning,
            category=req.category,
            reviewer=req.reviewer,
        )
        return {"status": "ok" if ok else "not_found", "term": req.term}
    except Exception as exc:
        return {"status": "error", "error": str(exc)}


@app.post("/api/slang/candidates/reject")
def reject_slang_candidate(req: SlangCandidateReviewRequest):
    """Reject a pending slang candidate while keeping audit evidence."""
    try:
        from storage.mysql_store import mysql
        ok = mysql.reject_slang_candidate(
            term=req.term,
            reviewer=req.reviewer,
            reason=req.reason,
        )
        return {"status": "ok" if ok else "not_found", "term": req.term}
    except Exception as exc:
        return {"status": "error", "error": str(exc)}




# ============================================================================
# Routes — Annotations (HITL feedback loop)
# ============================================================================

class AnnotationRequest(BaseModel):
    target_type: str          # "slang" | "classification" | "entity"
    target_id: int            # raw_id for classification, entity_id for entity, 0 for slang
    field_name: str           # corrected field (intent_label / entity_type / slang term)
    old_value: str = ""
    new_value: str
    annotator: str = "human"
    reason: str = ""


@app.post("/api/annotations")
def submit_annotation(req: AnnotationRequest):
    """Submit a human correction. Auto-triggers the feedback loop:
    - slang → updates dim_slang_dict
    - classification → updates dwd_intel_analysis + generates training sample
    - entity → updates dwd_entity
    """
    try:
        from storage.mysql_store import mysql
        result = mysql.log_annotation(
            target_type=req.target_type,
            target_id=req.target_id,
            field_name=req.field_name,
            old_value=req.old_value,
            new_value=req.new_value,
            annotator=req.annotator,
            reason=req.reason,
        )
        return {"status": "ok", "result": result}
    except Exception as exc:
        logger.error(f"Annotation submission failed: {exc}")
        return {"status": "error", "error": str(exc)}


@app.get("/api/annotations")
def list_annotations(synced: Optional[str] = Query(default=None)):
    """List HITL annotations. ?synced=0 returns only pending corrections."""
    try:
        from storage.mysql_store import mysql
        with mysql.cursor() as c:
            if synced is not None:
                c.execute(
                    "SELECT * FROM annotation_log WHERE synced=%s ORDER BY created_at DESC LIMIT 100",
                    (int(synced),),
                )
            else:
                c.execute("SELECT * FROM annotation_log ORDER BY created_at DESC LIMIT 100")
            items = c.fetchall()
            return {"total": len(items), "items": items}
    except Exception as exc:
        return {"total": 0, "items": [], "error": str(exc)}
