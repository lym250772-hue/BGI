#!/usr/bin/env python3
"""Import partner's JSONL data into ods_raw_intel.

Partner delivers one JSON object per line (JSONL format), matching
PROJECT_PLAN.md Section 1.1 schema:

    {
      "platform": "telegram",
      "content_raw": "...",
      "content_type": "text",
      "source_url": "...",
      "author_uid": "...",
      "author_username": "...",
      "group_id": "...",
      "collected_at": "2026-05-18T12:33:35",
      "metadata": {
        "keyword": "...",
        "has_image": false,
        "has_video": false,
        "message_id": 24305904
      }
    }

Usage:
    python scripts/import_partner_jsonl.py partner_data.jsonl
    python scripts/import_partner_jsonl.py partner_data.jsonl --dry-run
    python scripts/import_partner_jsonl.py partner_data.jsonl --status RAW_COLLECTED
"""

import sys
import json
import argparse
from datetime import datetime
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from loguru import logger
from storage.mysql_store import mysql

# Required fields in partner's JSON
REQUIRED_FIELDS = ["platform", "content_raw"]


def validate(item: dict, line_no: int) -> list[str]:
    """Return list of missing required fields."""
    missing = []
    for f in REQUIRED_FIELDS:
        if f not in item or not item[f]:
            missing.append(f)
    return missing


def map_to_raw(item: dict) -> dict:
    """Map partner's JSON fields to ods_raw_intel columns."""
    return {
        "source_platform": item.get("platform", "unknown"),
        "source_url": item.get("source_url", ""),
        "source_keyword": (item.get("metadata") or {}).get("keyword", ""),
        "author_id": str(item.get("author_uid", "")),
        "author_name": item.get("author_username", ""),
        "publish_time": item.get("publish_time"),
        "collect_time": item.get("collected_at", datetime.now().isoformat()),
        "content_type": item.get("content_type", "text"),
        "content_raw": item["content_raw"],
        "media_urls": json.dumps(item.get("media_urls", []), ensure_ascii=False),
        "media_hash": item.get("media_hash", ""),
        "crawl_batch_id": item.get("crawl_batch_id", ""),
        "raw_status": item.get("status", "RAW_COLLECTED"),
        "metadata": json.dumps(
            {**(item.get("metadata") or {}),
             "group_id": item.get("group_id", ""),
             "message_id": item.get("message_id")},
            ensure_ascii=False, default=str,
        ),
    }


def main():
    parser = argparse.ArgumentParser(description="Import partner JSONL into ods_raw_intel")
    parser.add_argument("file", help="Path to JSONL file")
    parser.add_argument("--dry-run", action="store_true", help="Validate only, no insert")
    parser.add_argument("--status", default="RAW_COLLECTED",
                        help="Set raw_status for all imported rows (default: RAW_COLLECTED)")
    args = parser.parse_args()

    filepath = Path(args.file)
    if not filepath.exists():
        logger.error(f"File not found: {args.file}")
        sys.exit(1)

    total, valid, skipped, imported = 0, 0, 0, 0
    errors = []

    with open(filepath, "r", encoding="utf-8") as f:
        for line in f:
            total += 1
            line = line.strip()
            if not line:
                continue

            try:
                item = json.loads(line)
            except json.JSONDecodeError as e:
                skipped += 1
                errors.append(f"Line {total}: invalid JSON — {e}")
                continue

            missing = validate(item, total)
            if missing:
                skipped += 1
                errors.append(f"Line {total}: missing fields {missing}")
                continue

            valid += 1

            if args.dry_run:
                logger.info(f"  [DRY RUN] Line {total}: platform={item.get('platform')}, "
                           f"len={len(item.get('content_raw', ''))}")
                continue

            try:
                mapped = map_to_raw(item)
                mapped["raw_status"] = args.status
                raw_id = mysql.insert_raw(mapped)
                imported += 1
                if imported % 50 == 0:
                    logger.info(f"  Imported {imported} items...")
            except Exception as e:
                skipped += 1
                errors.append(f"Line {total}: insert failed — {e}")

    # Summary
    print()
    print("=" * 60)
    print(f"  File:       {args.file}")
    print(f"  Total lines: {total}")
    print(f"  Valid:       {valid}")
    print(f"  Imported:    {imported}")
    print(f"  Skipped:     {skipped}")
    print("=" * 60)

    if errors:
        print(f"\n  Errors ({len(errors)}):")
        for e in errors[:10]:
            print(f"    {e}")
        if len(errors) > 10:
            print(f"    ... and {len(errors) - 10} more")

    if args.dry_run:
        print("\n  (Dry run — no data inserted)")

    return 0 if skipped == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
