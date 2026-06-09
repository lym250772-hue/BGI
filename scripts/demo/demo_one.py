#!/usr/bin/env python3
"""One-click demo from one raw JSON/text sample to an Agent result."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))


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
            "微信修复百分百成功，不成功退款。"
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


def _load_input(args) -> tuple[int | None, str, str, dict]:
    if args.stdin:
        raw = json.loads(sys.stdin.read())
        return None, raw.get("content_raw") or raw.get("text") or "", raw.get("platform", "stdin"), raw

    if args.json:
        with open(args.json, "r", encoding="utf-8") as f:
            raw = json.load(f)
        return None, raw.get("content_raw") or raw.get("text") or "", raw.get("platform", "unknown"), raw

    if args.raw_id:
        from storage.mysql_store import mysql

        with mysql.cursor() as c:
            c.execute("SELECT * FROM ods_raw_intel WHERE id=%s", (args.raw_id,))
            row = c.fetchone()
        if not row:
            raise SystemExit(f"raw_id={args.raw_id} 不存在")
        return args.raw_id, row.get("content_raw") or "", row.get("source_platform") or "unknown", row

    sample = DEMO_SAMPLES[args.sample]
    return None, sample["content_raw"], sample["platform"], sample


def _ensure_raw_id(raw_id: int | None, text: str, platform: str, raw: dict) -> int:
    if raw_id:
        return raw_id

    from storage.mysql_store import mysql

    return mysql.insert_raw({
        "source_platform": platform,
        "source_url": raw.get("source_url", ""),
        "author_id": str(raw.get("author_uid") or raw.get("author_id") or ""),
        "author_name": raw.get("author_username") or raw.get("author_name") or "",
        "content_type": raw.get("content_type", "text"),
        "content_raw": text,
        "raw_status": "RAW_COLLECTED",
        "metadata": json.dumps(raw.get("metadata", {}), ensure_ascii=False, default=str),
    })


def _print_result(result: dict):
    print("\n" + "=" * 72)
    print("BAGI 情报研判结果")
    print("=" * 72)
    print(f"情报ID     : {result.get('raw_id')}")
    print(f"业务状态   : {result.get('raw_status')}")
    print(f"风险分类   : {result.get('risk_label')} / {result.get('risk_sub_label')}")
    print(f"风险分     : {result.get('risk_score')} ({result.get('risk_level')})")

    entities = result.get("entities") or []
    print(f"\n实体({len(entities)}):")
    for ent in entities[:20]:
        etype = ent.get("entity_type")
        if hasattr(etype, "value"):
            etype = etype.value
        print(f"  - {etype}: {ent.get('entity_value')}  conf={ent.get('confidence')}")

    evidence = result.get("evidence_spans") or []
    print(f"\n证据片段({len(evidence)}):")
    for item in evidence[:10]:
        if isinstance(item, dict):
            print(f"  - {item.get('text') or item.get('evidence') or item}")
        else:
            print(f"  - {item}")

    print("\n工具决策:")
    for item in result.get("tool_log") or []:
        print(f"  - {item.get('tool')}: {item.get('decision')} {item.get('reason') or item.get('result') or ''}")


def main() -> int:
    parser = argparse.ArgumentParser(description="BAGI 单条情报演示脚本")
    src = parser.add_mutually_exclusive_group()
    src.add_argument("--sample", default="live_stream", choices=list(DEMO_SAMPLES.keys()))
    src.add_argument("--raw-id", type=int)
    src.add_argument("--json")
    src.add_argument("--stdin", action="store_true")
    parser.add_argument("--mode", choices=["fast", "standard", "expand"], default="standard")
    args = parser.parse_args()

    raw_id, text, platform, raw = _load_input(args)
    raw_id = _ensure_raw_id(raw_id, text, platform, raw)

    mode_options = {
        "fast": {
            "enable_llm": False,
            "enable_roberta": False,
            "enable_embedding": False,
            "enable_graph_expand": False,
            "enable_report": False,
            "analysis_mode": "快速筛查",
        },
        "standard": {
            "enable_llm": True,
            "enable_roberta": True,
            "enable_embedding": False,
            "enable_graph_expand": False,
            "enable_report": False,
            "analysis_mode": "标准研判",
        },
        "expand": {
            "enable_llm": True,
            "enable_roberta": True,
            "enable_embedding": True,
            "enable_graph_expand": True,
            "enable_report": False,
            "analysis_mode": "扩线研判",
        },
    }[args.mode]

    print(f"输入 raw_id={raw_id}, platform={platform}, text_len={len(text)}, mode={args.mode}")

    from analyzer.engine import engine

    result = engine.run(
        raw_data_id=raw_id,
        text=text,
        platform=platform,
        **mode_options,
    )
    _print_result(result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
