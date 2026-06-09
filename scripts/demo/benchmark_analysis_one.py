#!/usr/bin/env python3
"""Benchmark one analysis run and print per-step latency.

Examples:
    python scripts/demo/benchmark_analysis_one.py --raw-id 286 --fast
    python scripts/demo/benchmark_analysis_one.py --raw-id 286 --standard --prewarm
    python scripts/demo/benchmark_analysis_one.py --text "接码跑分，加V test_wx" --platform manual
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))


def _load_raw(raw_id: int) -> dict:
    from storage.mysql_store import mysql

    with mysql.cursor() as c:
        c.execute(
            """SELECT id, source_platform, content_raw
               FROM ods_raw_intel WHERE id=%s""",
            (raw_id,),
        )
        row = c.fetchone()
    if not row:
        raise SystemExit(f"raw_id={raw_id} not found in ods_raw_intel")
    return row


def _preferred_text(raw_id: int, fallback: str) -> str:
    from storage.mysql_store import mysql

    return mysql.get_preferred_analysis_text(raw_id, fallback=fallback)


def _options_from_mode(args) -> dict:
    if args.fast:
        return {
            "enable_llm": False,
            "enable_roberta": False,
            "enable_embedding": False,
            "enable_graph_expand": False,
            "enable_report": False,
            "analysis_mode": "快速筛查",
        }
    if args.standard:
        return {
            "enable_llm": True,
            "enable_roberta": True,
            "enable_embedding": False,
            "enable_graph_expand": False,
            "enable_report": False,
            "analysis_mode": "标准研判",
        }
    if args.expand:
        return {
            "enable_llm": True,
            "enable_roberta": True,
            "enable_embedding": not args.no_embedding,
            "enable_graph_expand": True,
            "enable_report": False,
            "analysis_mode": "扩线研判",
        }
    return {
        "enable_llm": not args.no_llm,
        "enable_roberta": True,
        "enable_embedding": not args.no_embedding,
        "enable_graph_expand": args.graph,
        "enable_report": args.report,
        "analysis_mode": "自定义研判",
    }


def _fmt(sec: float) -> str:
    return f"{sec * 1000:.1f} ms" if sec < 1 else f"{sec:.2f} s"


def main() -> int:
    parser = argparse.ArgumentParser(description="Benchmark one BGI analysis run")
    parser.add_argument("--raw-id", type=int, help="ods_raw_intel.id to analyze")
    parser.add_argument("--text", default="", help="Analyze this text instead of loading raw_id")
    parser.add_argument("--platform", default="manual", help="Platform used with --text")
    parser.add_argument("--fast", action="store_true", help="Disable LLM, RoBERTa, graph and report")
    parser.add_argument("--standard", action="store_true", help="Enable RoBERTa and LLM, disable graph/report")
    parser.add_argument("--expand", action="store_true", help="Enable LLM, RoBERTa and graph expansion")
    parser.add_argument("--no-llm", action="store_true", help="Disable LLM fallback")
    parser.add_argument("--graph", action="store_true", help="Enable graph expansion")
    parser.add_argument("--report", action="store_true", help="Enable report generation")
    parser.add_argument("--repeat", type=int, default=1, help="Run the same benchmark N times")
    parser.add_argument("--no-embedding", action="store_true", help="Disable embedding/Milvus")
    parser.add_argument("--prewarm", action="store_true", help="Preload classifier/embedding before timing")
    parser.add_argument("--no-persist-warning", action="store_true", help="Do not print persistence warning")
    args = parser.parse_args()

    if not args.raw_id and not args.text:
        raise SystemExit("Provide --raw-id or --text")

    if args.raw_id:
        raw = _load_raw(args.raw_id)
        raw_id = int(raw["id"])
        platform = raw.get("source_platform") or "unknown"
        text = _preferred_text(raw_id, fallback=raw.get("content_raw") or "")
    else:
        raw_id = 0
        platform = args.platform
        text = args.text

    options = _options_from_mode(args)

    if not args.no_persist_warning:
        print("NOTE: the Agent persists results at the final step.")
        print("      Use a disposable raw_id if you only want a benchmark run.\n")

    if args.prewarm:
        print("Prewarming analysis models before timing...")
        prewarm_start = time.perf_counter()
        from services.prewarm import prewarm_analysis_models
        prewarm_result = prewarm_analysis_models(include_embedding=options["enable_embedding"])
        print(f"Prewarm done in {_fmt(time.perf_counter() - prewarm_start)}")
        print(json.dumps(prewarm_result, ensure_ascii=False, indent=2))

    from analyzer.engine import engine

    totals: list[float] = []
    for run_no in range(1, max(1, args.repeat) + 1):
        print("=" * 72)
        print(f"run         : {run_no}/{max(1, args.repeat)}")
        print(f"raw_id      : {raw_id}")
        print(f"platform    : {platform}")
        print(f"text length : {len(text)}")
        print(f"options     : {json.dumps(options, ensure_ascii=False)}")
        print("=" * 72)

        starts: dict[str, float] = {}
        durations: list[tuple[str, float]] = []
        final_result = None
        total_start = time.perf_counter()

        for event in engine.run_stream(
            raw_data_id=raw_id,
            text=text,
            platform=platform,
            enable_graph_expand=options["enable_graph_expand"],
            enable_report=options["enable_report"],
            enable_llm=options["enable_llm"],
            enable_embedding=options["enable_embedding"],
            enable_roberta=options["enable_roberta"],
            analysis_mode=options["analysis_mode"],
        ):
            step = event.get("step", "unknown")
            status = event.get("status", "")
            now = time.perf_counter()

            if status == "running":
                starts[step] = now
                print(f"START {step}")
            elif status == "done":
                elapsed = now - starts.get(step, now)
                durations.append((step, elapsed))
                print(f"DONE  {step:<18} {_fmt(elapsed):>10}")

            if event.get("final"):
                final_result = event.get("result")

        total = time.perf_counter() - total_start
        totals.append(total)
        print("=" * 72)
        print(f"TOTAL {_fmt(total)}")

        if durations:
            print("\nSlowest steps:")
            for step, elapsed in sorted(durations, key=lambda item: item[1], reverse=True)[:5]:
                print(f"  {step:<18} {_fmt(elapsed):>10}   {elapsed / total * 100:4.1f}%")

        if final_result:
            print("\nResult:")
            print(f"  raw_status  : {final_result.get('raw_status')}")
            print(f"  risk        : {final_result.get('risk_label')} / {final_result.get('risk_sub_label')}")
            print(f"  score       : {final_result.get('risk_score')} ({final_result.get('risk_level')})")
            print(f"  entities    : {len(final_result.get('entities') or [])}")
            print(f"  evidence    : {len(final_result.get('evidence_spans') or [])}")
            print(f"  tool_log    : {final_result.get('tool_log')}")

    if len(totals) > 1:
        avg = sum(totals) / len(totals)
        print("=" * 72)
        print(f"AVERAGE {_fmt(avg)} over {len(totals)} runs")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
