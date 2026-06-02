#!/usr/bin/env python3
"""Collect real sample data from each platform and save to examples/.

This script runs a small collection (1-2 pages, limited items) on each
available platform with real search keywords, then saves the raw parsed
items as JSON files in the examples/ directory for analysis & demo use.

Usage:
    python scripts/collect_examples.py
    python scripts/collect_examples.py --max-pages 2 --keywords "刷单"
    python scripts/collect_examples.py --platforms weibo,zhihu
"""

import json
import sys
import time
import argparse
from dataclasses import asdict, is_dataclass
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from loguru import logger

logger.remove()
logger.add(sys.stderr, level="INFO",
           format="<green>{time:HH:mm:ss}</green> | <level>{level: <8}</level> | {message}")

EXAMPLES_DIR = PROJECT_ROOT / "examples"

# Keywords that reliably return grey-market results on each platform
DEFAULT_KEYWORDS = [
    "刷单",       # brushing / fake orders
    "接码",       # SMS verification code services
    "账号出售",   # account selling
]

PLATFORM_CONFIG = {
    "weibo": {
        "spider": "http",
        "keyword": "刷单",
        "max_pages": 2,
        "count": 20,
    },
    "tieba": {
        "spider": "playwright",
        "keyword": "刷单",
        "max_pages": 2,
    },
    "zhihu": {
        "spider": "playwright",
        "keyword": "刷单",
        "max_pages": 2,
    },
    "xiaohongshu": {
        "spider": "playwright",
        "keyword": "刷单",
        "max_pages": 2,
    },
    "douyin": {
        "spider": "playwright",
        "keyword": "无人直播",
        "max_pages": 2,
    },
}


def _serialize(obj):
    """JSON serializer for dataclasses & datetime."""
    if is_dataclass(obj):
        return {k: _serialize(v) for k, v in asdict(obj).items()}
    if isinstance(obj, datetime):
        return obj.isoformat()
    if isinstance(obj, (set, frozenset)):
        return list(obj)
    if isinstance(obj, bytes):
        return obj.decode("utf-8", errors="replace")
    return obj


def collect_weibo(keyword: str, max_pages: int, fetch_comments: bool = True) -> list[dict]:
    """Collect from Weibo (pure HTTP API, no browser)."""
    from collectors.spiders.weibo_api_spider import WeiboAPISpider

    spider = WeiboAPISpider()
    all_items = []
    try:
        logger.info("[weibo] Searching: {} (max_pages={})", keyword, max_pages)
        parsed = spider.search(keyword, max_pages=max_pages)
        for item in parsed:
            d = _serialize(item)
            # 采集评论
            if fetch_comments and item.comments_count > 0:
                try:
                    comments = spider.get_comments(item.weibo_id, max_pages=2)
                    d.setdefault("metadata", {})["comments"] = [
                        {"id": c.get("id", ""),
                         "author": (c.get("user", {}) or {}).get("screen_name", ""),
                         "text": c.get("text_raw", "") or c.get("text", ""),
                         "like_count": c.get("like_counts", 0)}
                        for c in comments
                    ]
                except Exception:
                    pass
            all_items.append(d)
        logger.info("[weibo] {} items collected", len(all_items))
    finally:
        if spider._session:
            spider._session.close()
    return all_items


def collect_playwright(platform: str, keyword: str, max_pages: int) -> list[dict]:
    """Collect from a Playwright-based platform (tieba/zhihu/xhs/douyin)."""
    if platform == "tieba":
        from collectors.spiders.tieba_spider import TiebaSpider as SpiderClass
    elif platform == "zhihu":
        from collectors.spiders.zhihu_spider import ZhihuSearchSpider as SpiderClass
    elif platform == "xiaohongshu":
        from collectors.spiders.xiaohongshu_spider import XiaohongshuSearchSpider as SpiderClass
    elif platform == "douyin":
        from collectors.spiders.douyin_spider import DouyinSearchSpider as SpiderClass
    else:
        logger.error("Unknown platform: {}", platform)
        return []

    spider = SpiderClass(headless=True)
    all_items = []
    try:
        spider.start()
        logger.info("[{}] Searching: {} (max_pages={})", platform, keyword, max_pages)

        if platform == "zhihu":
            items = spider.search_and_parse(
                keyword, max_pages=max_pages,
                fetch_answers=True, fetch_comments=True)
        elif platform == "tieba":
            items = spider.search_and_parse(
                keyword, max_pages=max_pages,
                fetch_replies=True)
        else:
            items = spider.search_and_parse(keyword, max_pages=max_pages)

        for item in items:
            all_items.append(_serialize(item))
        logger.info("[{}] {} items collected", platform, len(all_items))
    except Exception as exc:
        logger.error("[{}] Collection failed: {}", platform, exc)
    finally:
        try:
            spider.close()
        except Exception:
            pass
    return all_items


def main():
    parser = argparse.ArgumentParser(description="Collect real sample data for examples/")
    parser.add_argument("--max-pages", type=int, default=2,
                        help="Max pages per platform (default: 2)")
    parser.add_argument("--keywords", "-k", default="",
                        help="Comma-separated keywords (default: built-in list)")
    parser.add_argument("--platforms", default="",
                        help="Comma-separated platforms (default: all available)")
    parser.add_argument("--output-dir", default=str(EXAMPLES_DIR),
                        help="Output directory (default: examples/)")
    args = parser.parse_args()

    out_dir = Path(args.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    # Resolve keywords
    kw_list = [k.strip() for k in args.keywords.split(",") if k.strip()] if args.keywords else []
    if not kw_list:
        kw_list = DEFAULT_KEYWORDS

    # Resolve platforms
    platforms = [p.strip() for p in args.platforms.split(",") if p.strip()] if args.platforms else []
    if not platforms:
        platforms = list(PLATFORM_CONFIG.keys())

    logger.info("=" * 60)
    logger.info("Collecting sample data for {} platforms", len(platforms))
    logger.info("Platforms: {}", ", ".join(platforms))
    logger.info("Keywords: {}", ", ".join(kw_list))
    logger.info("Output: {}", out_dir)
    logger.info("=" * 60)

    summary = {}
    t_start = time.time()

    for platform in platforms:
        config = PLATFORM_CONFIG.get(platform, {})
        if not config:
            logger.warning("[{}] No config — skipping", platform)
            continue

        # Check cookies (except weibo which is HTTP-based)
        if config["spider"] == "playwright":
            from collectors.spiders.base_spider import BaseSpider
            cookies = BaseSpider.load_cookies(platform)
            if not cookies:
                logger.warning("[{}] No cookies — skipping", platform)
                continue

        # Collect with all keywords
        all_items = []
        for kw in kw_list:
            if config["spider"] == "http":
                items = collect_weibo(kw, args.max_pages)
            else:
                items = collect_playwright(platform, kw, args.max_pages)
            all_items.extend(items)
            if items:
                time.sleep(2)  # Be polite between keywords

        # Save to file
        out_path = out_dir / f"{platform}_sample.json"
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(
                {
                    "platform": platform,
                    "collected_at": datetime.utcnow().isoformat(),
                    "keywords": kw_list,
                    "total": len(all_items),
                    "items": all_items,
                },
                f, ensure_ascii=False, indent=2, default=str,
            )
        logger.info("[{}] Saved {} items → {}", platform, len(all_items), out_path.name)
        summary[platform] = {"items": len(all_items), "file": out_path.name}

    elapsed = time.time() - t_start
    logger.info("=" * 60)
    logger.info("Done in {:.0f}s", elapsed)
    total = sum(v["items"] for v in summary.values())
    logger.info("Total: {} items across {} platforms", total, len(summary))
    for p, s in summary.items():
        logger.info("  {}: {} items → {}", p, s["items"], s["file"])
    logger.info("=" * 60)


if __name__ == "__main__":
    main()
