#!/usr/bin/env python3
"""Import partner's JSONL data into ods_raw_intel.

Partner delivers one JSON object per line (JSONL format), matching
PROJECT_PLAN.md Section 1.1 schema:

    {
      "platform": "content_raw": "...",
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
    python scripts/importers/import_partner_jsonl.py partner_data.jsonl
    python scripts/importers/import_partner_jsonl.py partner_data.jsonl --dry-run
    python scripts/importers/import_partner_jsonl.py partner_data.jsonl --status RAW_COLLECTED
"""

import sys
import json
import argparse
from datetime import datetime
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from loguru import logger
from storage.mysql_store import mysql

# Required fields in partner's JSON
REQUIRED_FIELDS = ["platform", "content_raw", "content_type", "collected_at"]


def _is_duplicate(platform: str, source_url: str, message_id) -> bool:
    """Check if a record with the same platform + source_url already exists.
    Falls back to platform + source_url alone if no message_id is available.
    """
    with mysql.cursor() as c:
        if source_url and message_id:
            c.execute(
                """SELECT COUNT(*) as cnt FROM ods_raw_intel
                   WHERE source_platform=%s AND source_url=%s
                   AND JSON_EXTRACT(metadata, '$.message_id') = %s""",
                (platform, source_url, str(message_id)))
        elif source_url:
            c.execute(
                """SELECT COUNT(*) as cnt FROM ods_raw_intel
                   WHERE source_platform=%s AND source_url=%s""",
                (platform, source_url))
        else:
            return False
        row = c.fetchone()
        return (row["cnt"] if row else 0) > 0


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
            ensure_ascii=False, default=str),
    }


def exists_in_db(item: dict) -> bool:
    """Best-effort idempotence check for partner imports."""
    metadata = item.get("metadata") or {}
    message_id = metadata.get("message_id") or item.get("message_id")
    platform = item.get("platform", "unknown")
    source_url = item.get("source_url", "")
    from storage.mysql_store import mysql
    with mysql.cursor() as c:
        if source_url:
            c.execute(
                "SELECT id FROM ods_raw_intel WHERE source_platform=%s AND source_url=%s LIMIT 1",
                (platform, source_url))
            if c.fetchone():
                return True
        if message_id:
            c.execute(
                """SELECT id FROM ods_raw_intel
                   WHERE source_platform=%s
                     AND JSON_EXTRACT(metadata, '$.message_id') = %s
                   LIMIT 1""",
                (platform, str(message_id)))
            if c.fetchone():
                return True
    return False


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

    total, valid, skipped, imported, dedup = 0, 0, 0, 0, 0
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
                if exists_in_db(item):
                    skipped += 1
                    continue
                mapped = map_to_raw(item)
                mapped["raw_status"] = args.status

                # Dedup: skip if same platform + source_url (+ message_id) already exists
                msg_id = (item.get("metadata") or {}).get("message_id") or item.get("message_id")
                if _is_duplicate(mapped["source_platform"], mapped["source_url"], msg_id):
                    dedup += 1
                    continue

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
    print(f"  Duplicates:  {dedup}")
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
