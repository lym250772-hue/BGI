#!/usr/bin/env python3
"""One-click demo: from a raw JSON sample to a full analysis report.

Usage:
    # Demo with built-in sample data
    python scripts/demo/demo_one.py

    # Demo with a specific existing raw_id
    python scripts/demo/demo_one.py --raw-id 200

    # Demo with a custom JSON file
    python scripts/demo/demo_one.py --json sample.json

    # Demo with JSON from stdin
    echo '{"platform":"telegram","content_raw":"..."}' | python scripts/demo/demo_one.py --stdin

This is the "key moment" script for presentations:
    输入一条情报 JSON → 一键研判 → 展示完整结果
"""

import sys
import json
import os
import argparse
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

os.environ.setdefault("HF_ENDPOINT", "https://hf-mirror.com")

from loguru import logger

# Built-in demo samples
DEMO_SAMPLES = {
    "live_stream": {
        "platform": "telegram",
        "content_raw": (
            "抖音无人直播技术，全套教程+工具，包教包会。"
            "详情看主页，联系微信 douyin_pro888。"
            "工具下载 https://linktr.ee/douyin_pro"
        ),
        "content_type": "text",
        "author_username": "外挂脚本",
        "group_id": "直播技术",
        "metadata": {"keyword": "直播技术", "message_id": 24305904},
    },
    "fraud": {
        "platform": "tieba",
        "content_raw": (
            "刷单返利兼职，日赚500+，无抵押贷款秒批。"
            "加QQ 33445566 详谈，银行卡转账到 6222021234567890。"
            "征信修复，百分百成功，不成功退款。"
        ),
        "content_type": "text",
        "author_username": "诚信兼职",
        "group_id": "兼职吧",
        "metadata": {"keyword": "刷单", "message_id": 12345},
    },
    "cheat": {
        "platform": "weibo",
        "content_raw": (
            "王者荣耀自瞄透视外挂，稳定不封号。"
            "出售和平精英辅助脚本，批量注册抖音白号。"
            "联系微信 hack_master_2024 购买，支持支付宝付款。"
        ),
        "content_type": "text",
        "author_username": "科技改变生活",
        "metadata": {"keyword": "外挂", "message_id": 67890},
    },
}

DIVIDER = "=" * 72
THIN = "-" * 72


def pretty_evidence(evidence: list) -> None:
    if not evidence:
        print("  (无证据片段)")
        return
    for i, ev in enumerate(evidence[:8], 1):
        method = ev.get("method", "?")
        risk = ev.get("risk_point", "")
        text = ev.get("text", "")[:80]
        reason = ev.get("reason", "")[:80]
        print(f"  [{i}] [{method}] {risk}")
        print(f"      原文: 「{text}」")
        print(f"      解释: {reason}")


def pretty_entities(entities: list) -> None:
    if not entities:
        print("  (无实体)")
        return
    by_type = {}
    for e in entities:
        et = e.get("entity_type", "")
        et_s = et.value if hasattr(et, "value") else str(et)
        ev = e.get("entity_value", "")
        by_type.setdefault(et_s, []).append(ev)
    for t, vals in sorted(by_type.items()):
        unique = list(dict.fromkeys(vals))  # dedup keep order
        print(f"  [{t}] ({len(unique)}): {', '.join(unique[:8])}")


def pretty_slang(slang_terms: list) -> None:
    if not slang_terms:
        print("  (无黑话)")
        return
    for sl in slang_terms[:10]:
        print(f"  · {sl.get('term', '?')} → {sl.get('meaning', '?')}")


def pretty_graph(graph: dict) -> None:
    if not graph:
        print("  (无图谱结果)")
        return
    print(f"  团伙关联: {'是' if graph.get('is_gang_related') else '否'}")
    if graph.get("case_id"):
        print(f"  案件编号: {graph['case_id']}")
    if graph.get("cluster_id"):
        print(f"  聚类编号: {graph['cluster_id']}")
    print(f"  关联实体数: {graph.get('related_entities_count', 0)}")
    contacts = graph.get("shared_contacts", [])
    if contacts:
        print(f"  共享联系方式: {', '.join(contacts[:5])}")


def pretty_advice(advice: list) -> None:
    if not advice:
        print("  (无处置建议)")
        return
    for a in advice[:10]:
        prio = a.get("priority", "medium")
        prio_icon = {"critical": "!!", "high": " !", "medium": " -", "low": "  "}
        icon = prio_icon.get(prio, " -")
        print(f"  [{icon}] {a.get('action', '?')}")
        detail = a.get("detail", "")
        if detail:
            print(f"       {detail}")


def run_demo(
    raw_id: int = None,
    json_file: str = None,
    sample_name: str = "live_stream",
    stdin: bool = False,
    enable_graph: bool = True,
    enable_report: bool = True,
):
    """Run the full analysis pipeline and pretty-print results."""

    # ── 1. Resolve input source ──────────────────────────────────────────
    text = ""
    platform = "unknown"

    if stdin:
        raw = json.loads(sys.stdin.read())
        text = raw.get("content_raw", raw.get("text", ""))
        platform = raw.get("platform", "stdin")
        print(f"\n  [输入] stdin, platform={platform}")

    elif json_file:
        with open(json_file, "r", encoding="utf-8") as f:
            raw = json.load(f)
        text = raw.get("content_raw", raw.get("text", ""))
        platform = raw.get("platform", "unknown")
        print(f"\n  [输入] {json_file}, platform={platform}")

        # Insert into DB so we have a raw_id
        from storage.mysql_store import mysql
        raw_id = mysql.insert_raw({
            "source_platform": platform,
            "source_url": raw.get("source_url", ""),
            "author_id": str(raw.get("author_uid", "")),
            "author_name": raw.get("author_username", ""),
            "content_type": raw.get("content_type", "text"),
            "content_raw": text,
            "raw_status": "RAW_COLLECTED",
            "metadata": json.dumps(raw.get("metadata", {}), ensure_ascii=False, default=str),
        })
        print(f"  [入库] ods_raw_intel id={raw_id}")

    elif raw_id:
        from storage.mysql_store import mysql
        items = mysql.list_raw(limit=1)
        # Find the specific raw_id
        with mysql.cursor() as c:
            c.execute("SELECT * FROM ods_raw_intel WHERE id=%s", (raw_id,))
            item = c.fetchone()
        if not item:
            print(f"  [错误] raw_id={raw_id} 不存在")
            return
        text = item.get("content_raw", "")
        platform = item.get("source_platform", "unknown")
        print(f"\n  [输入] ods_raw_intel id={raw_id}, platform={platform}")

    else:
        sample = DEMO_SAMPLES.get(sample_name, DEMO_SAMPLES["live_stream"])
        text = sample["content_raw"]
        platform = sample["platform"]

        # Insert into DB
        from storage.mysql_store import mysql
        raw_id = mysql.insert_raw({
            "source_platform": platform,
            "source_url": sample.get("source_url", ""),
            "author_id": "",
            "author_name": sample.get("author_username", ""),
            "content_type": sample.get("content_type", "text"),
            "content_raw": text,
            "raw_status": "RAW_COLLECTED",
            "metadata": json.dumps(sample.get("metadata", {}), ensure_ascii=False, default=str),
        })
        print(f"\n  [输入] 内置样本「{sample_name}」, platform={platform}")
        print(f"  [入库] ods_raw_intel id={raw_id}")

    # ── 2. Display raw text ──────────────────────────────────────────────
    print(f"\n  [原文] ({len(text)} 字)")
    print(f"  {text[:300]}")
    if len(text) > 300:
        print(f"  ... (共 {len(text)} 字)")

    # ── 3. Run analysis ──────────────────────────────────────────────────
    print(f"\n{THIN}")
    print("  分析中...")
    print(THIN)

    from analyzer.engine import engine
    result = engine.run(
        raw_data_id=raw_id,
        text=text,
        platform=platform,
        enable_graph_expand=enable_graph,
        enable_report=enable_report,
    )

    # ── 4. Display results ───────────────────────────────────────────────
    print(f"\n{DIVIDER}")
    print(f"  BAGI 黑灰产情报研判报告")
    print(DIVIDER)

    # Risk
    risk_label = result["risk_label"]
    risk_sub = result.get("risk_sub_label", "")
    risk_score = result.get("risk_score", 0)
    risk_level = result.get("risk_level", "normal")

    level_cn = {"critical": "严重", "high": "高危", "normal": "普通", "low": "低"}
    level_label = level_cn.get(risk_level, risk_level)

    print(f"\n  ◆ 风险标签")
    print(f"    一级分类: {risk_label}")
    if risk_sub:
        print(f"    二级分类: {risk_sub}")
    print(f"    风险评分: {risk_score:.2f}  ({level_label})")
    print(f"    风险等级: {risk_level}")

    # Evidence
    print(f"\n  ◆ 证据片段 ({len(result.get('evidence_spans', []))} 条)")
    pretty_evidence(result.get("evidence_spans", []))

    # Entities
    print(f"\n  ◆ 抽取实体 ({len(result.get('entities', []))} 个)")
    pretty_entities(result.get("entities", []))

    # Slang
    print(f"\n  ◆ 黑话解释 ({len(result.get('slang_terms', []))} 条)")
    pretty_slang(result.get("slang_terms", []))

    # Graph
    print(f"\n  ◆ 图谱扩线")
    pretty_graph(result.get("graph_result", {}))

    # Summary
    summary = result.get("agent_summary", "")
    if summary:
        print(f"\n  ◆ Agent 研判摘要")
        print(f"  {summary[:500]}")

    # Disposal advice
    print(f"\n  ◆ 处置建议 ({len(result.get('disposal_advice', []))} 条)")
    pretty_advice(result.get("disposal_advice", []))

    print(f"\n{DIVIDER}")
    print(f"  研判完成 — raw_id={raw_id}")
    print(DIVIDER)

    return result


def main():
    parser = argparse.ArgumentParser(
        description="BAGI 一键演示：从情报 JSON 到完整研判报告"
    )
    src = parser.add_mutually_exclusive_group()
    src.add_argument("--sample", default="live_stream",
                     choices=list(DEMO_SAMPLES.keys()),
                     help="Use built-in sample (default: live_stream)")
    src.add_argument("--raw-id", type=int, help="Re-analyze existing ods_raw_intel by ID")
    src.add_argument("--json", help="Path to a JSON file")
    src.add_argument("--stdin", action="store_true", help="Read JSON from stdin")
    parser.add_argument("--no-graph", action="store_true", help="Skip graph expansion")
    parser.add_argument("--no-report", action="store_true", help="Skip report generation")
    args = parser.parse_args()

    run_demo(
        raw_id=args.raw_id,
        json_file=args.json,
        sample_name=args.sample,
        stdin=args.stdin,
        enable_graph=not args.no_graph,
        enable_report=not args.no_report,
    )


if __name__ == "__main__":
    main()
