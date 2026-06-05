#!/usr/bin/env python3
"""Run full Xianyu collection with ALL 48 slang keywords from seed_slang.json."""
import json, sys, os
from pathlib import Path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from loguru import logger
from collectors.normalizer import normalize_items
# Import collect_xianyu from the sibling script
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))
from collect_examples import collect_xianyu, EXAMPLES_DIR, _serialize
from datetime import datetime, timezone

logger.remove()
logger.add(sys.stderr, level="INFO",
           format="<green>{time:HH:mm:ss}</green> | <level>{level: <8}</level> | {message}")

# Load all 48 keywords
with open('data/slang_dict/seed_slang.json', 'r', encoding='utf-8') as f:
    slang = json.load(f)
keywords = [s['slang'] for s in slang]

logger.info("=" * 60)
logger.info("Xianyu full collection: {} keywords", len(keywords))
logger.info("=" * 60)

# Collect all keywords in single browser session
results = collect_xianyu(keywords, max_pages=2)

# Flatten results
all_items = []
for kw, items in results:
    all_items.extend(items)

logger.info("Total raw items: {}", len(all_items))

# Normalize to IntelItem
normalized = normalize_items("xianyu", all_items)
logger.info("Normalized: {} items", len(normalized))

# Save
out_path = EXAMPLES_DIR / "xianyu_sample.json"
with open(out_path, "w", encoding="utf-8") as f:
    json.dump({
        "platform": "xianyu",
        "collected_at": datetime.now(timezone.utc).isoformat(),
        "keywords": keywords,
        "total": len(normalized),
        "items": [_serialize(item) for item in normalized],
    }, f, ensure_ascii=False, indent=2, default=str)

logger.info("Saved {} items -> {}", len(normalized), out_path.name)
logger.info("Done!")
