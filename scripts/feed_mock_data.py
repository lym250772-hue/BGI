#!/usr/bin/env python3
"""Feed mock collected intel JSON into MySQL raw_data table, ready for analysis.

Usage:
    python scripts/feed_mock_data.py                           # default: data/mock_collected_intel.json
    python scripts/feed_mock_data.py -i custom.json            # custom input
    python scripts/feed_mock_data.py --status pending          # insert as pending (needs cleaning)
"""

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from storage.mysql_store import mysql


def feed(file_path: str, status: str = "cleaned") -> int:
    """Insert mock intel items into raw_data. Returns count."""
    with open(file_path, "r", encoding="utf-8") as f:
        items = json.load(f)

    count = 0
    for item in items:
        metadata = item.get("metadata", {})
        raw = {
            "source_platform": item["platform"],
            "source_url": item.get("source_url", ""),
            "author_uid": item.get("author_uid", ""),
            "author_username": item.get("author_username", ""),
            "content_type": item.get("content_type", "text"),
            "content_raw": item["content_raw"],
            "content": item["content_raw"],  # already "cleaned"
            "image_hash": "",
            "simhash": "",
            "priority": "normal",
            "status": status,
            "collected_at": item.get("collected_at", datetime.now().strftime("%Y-%m-%dT%H:%M:%S")),
            "group_id": item.get("group_id", ""),
            "message_id": metadata.get("message_id", None),
            "metadata": json.dumps(metadata, ensure_ascii=False),
        }
        rid = mysql.insert_raw(raw)
        count += 1
        if count % 50 == 0:
            print(f"  Inserted {count} items...")

    return count


def main():
    parser = argparse.ArgumentParser(description="Feed mock intel JSON into MySQL raw_data")
    parser.add_argument("-i", "--input", default=None, help="Path to mock JSON file")
    parser.add_argument("--status", default="cleaned", choices=["pending", "cleaned"])
    args = parser.parse_args()

    default_path = Path(__file__).resolve().parent.parent / "data" / "mock_collected_intel.json"
    file_path = args.input or str(default_path)

    if not Path(file_path).exists():
        print(f"File not found: {file_path}")
        sys.exit(1)

    print(f"Feeding {file_path} → MySQL raw_data (status={args.status})...")
    count = feed(file_path, args.status)
    print(f"Done. {count} items inserted into raw_data.")


if __name__ == "__main__":
    main()
