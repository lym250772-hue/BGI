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
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from loguru import logger
from collectors.normalizer import normalize_items  # 🆕 统一格式

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
        "spider": "http",  # 🆕 已升级为 JSON API
        "keyword": "刷单",
        "max_pages": 3,
        "count": 20,
    },
    "zhihu": {
        "spider": "http",  # 🆕 使用纯 HTTP API Spider
        "keyword": "刷单",
        "max_pages": 2,
        "count": 20,
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
    "xianyu": {
        "spider": "playwright_v3",
        "keyword": "刷单",
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


def collect_weibo(keyword: str, max_pages: int, fetch_comments: bool = True) -> list:
    """Collect from Weibo (pure HTTP API, no browser). Returns parsed items + comments in metadata."""
    from collectors.spiders.weibo_api_spider import WeiboAPISpider

    spider = WeiboAPISpider()
    all_items = []
    try:
        logger.info("[weibo] Searching: {} (max_pages={})", keyword, max_pages)
        parsed = spider.search(keyword, max_pages=max_pages)
        for item in parsed:
            # 采集评论，存到 metadata.comments（normalize_weibo 会读取）
            if fetch_comments and item.comments_count > 0:
                try:
                    comments = spider.get_comments(item.weibo_id, max_pages=2)
                    item.metadata["comments"] = [
                        {"id": c.get("id", ""),
                         "author": (c.get("user", {}) or {}).get("screen_name", ""),
                         "text": c.get("text_raw", "") or c.get("text", ""),
                         "like_count": c.get("like_counts", 0)}
                        for c in comments
                    ]
                except Exception:
                    pass
            all_items.append(item)  # Keep as ParsedWeiboAPIItem object
        logger.info("[weibo] {} items collected", len(all_items))
    finally:
        if spider._session:
            spider._session.close()
    return all_items


def collect_tieba(keyword: str, max_pages: int) -> list:
    """Collect from Tieba (JSON API, no browser). Returns ParsedTiebaItem objects. 🆕"""
    from collectors.spiders.tieba_api_spider import TiebaAPISpider

    spider = TiebaAPISpider()
    all_items = []
    try:
        logger.info("[tieba] Searching: {} (max_pages={})", keyword, max_pages)
        items = spider.search(keyword, max_pages=max_pages, rn=20)
        all_items = items  # Keep as ParsedTiebaItem objects
        logger.info("[tieba] {} items collected", len(all_items))
    finally:
        spider.close()
    return all_items


def collect_zhihu_http(keyword: str, max_pages: int) -> list:
    """Collect from Zhihu (pure HTTP API, no browser). Returns ParsedZhihuAPIItem objects. 🆕"""
    from collectors.spiders.zhihu_api_spider import ZhihuAPISpider

    spider = ZhihuAPISpider()
    all_items = []
    try:
        logger.info("[zhihu] Searching: {} (max_pages={})", keyword, max_pages)
        items = spider.search(keyword, max_pages=max_pages)
        all_items = items  # Keep as ParsedZhihuAPIItem objects
        logger.info("[zhihu] {} items collected", len(all_items))
    finally:
        if hasattr(spider, '_session') and spider._session:
            spider._session.close()
    return all_items


def collect_playwright(platform: str, keyword: str, max_pages: int) -> list:
    """Collect from a Playwright-based platform (xhs/douyin). Returns raw parsed objects."""
    if platform == "xiaohongshu":
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
        items = spider.search_and_parse(keyword, max_pages=max_pages)
        all_items = items  # Keep as raw parsed objects
        logger.info("[{}] {} items collected", platform, len(all_items))
    except Exception as exc:
        logger.error("[{}] Collection failed: {}", platform, exc)
    finally:
        try:
            spider.close()
        except Exception:
            pass
    return all_items


def collect_xianyu(keywords: list, max_pages: int, cookie_file: str = None) -> list:
    """Collect from Xianyu (v3 persistent browser, MUST be visible).
    Uses a single persistent browser session for ALL keywords.
    Returns list of (keyword, [ParsedXianyuItem]) tuples.
    """
    from collectors.spiders.xianyu_spider import XianyuSearchSpider

    spider = XianyuSearchSpider(headless=False)
    all_items = []
    try:
        spider.start()  # 仅启动一次浏览器
        for kw in keywords:
            logger.info("[xianyu] Searching: {} (max_pages={})", kw, max_pages)
            try:
                items = spider.search_and_parse(kw, max_pages=max_pages)
                all_items.append((kw, items))
                logger.info("[xianyu] {}: {} items", kw, len(items))
            except Exception as exc:
                logger.error("[xianyu] {}: Collection failed: {}", kw, exc)
    except Exception as exc:
        logger.error("[xianyu] Fatal: {}", exc)
    finally:
        try:
            spider.close()  # 所有关键词采集完后才关闭
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
    parser.add_argument("--with-comments", action="store_true",
                        help="采集主帖后继续采集评论（会增加耗时）")
    parser.add_argument("--max-comment-items", type=int, default=20,
                        help="最多为多少条帖子采集评论 (default: 20)")
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

        # Check cookies for playwright-based platforms
        if config["spider"] in ("playwright", "playwright_v3"):
            from collectors.spiders.base_spider import BaseSpider
            cookies = BaseSpider.load_cookies(platform)
            if not cookies:
                logger.warning("[{}] No cookies — skipping", platform)
                continue

        # Collect with all keywords
        all_items = []
        for kw in kw_list:
            if platform == "weibo":
                items = collect_weibo(kw, args.max_pages)
            elif platform == "tieba":
                items = collect_tieba(kw, args.max_pages)
            elif platform == "zhihu":
                items = collect_zhihu_http(kw, args.max_pages)
            elif platform == "xianyu":
                # Xianyu uses a single persistent browser session for all keywords
                results = collect_xianyu(kw_list, args.max_pages)
                for kw, items in results:
                    all_items.extend(items)
                    if items:
                        time.sleep(2)  # Gentle delay between keywords
                break  # Already processed all keywords in one call
            elif config["spider"] == "http":
                items = collect_weibo(kw, args.max_pages)
            else:
                items = collect_playwright(platform, kw, args.max_pages)
            all_items.extend(items)
            if items:
                time.sleep(1)  # Be polite between keywords

        # 🆕 归一化为统一 IntelItem 格式
        normalized = normalize_items(platform, all_items)
        logger.info("[{}] Normalized {} items to unified IntelItem format", platform, len(normalized))

        # 🆕 评论采集（小红书：响应拦截；抖音：需可见浏览器；贴吧：旧版DOM）
        if args.with_comments and platform == "xiaohongshu":
            logger.info("[{}] 开始采集评论 (最多{}条帖子)...", platform, args.max_comment_items)
            try:
                from collectors.comment_collector import enrich_comments
                from collectors.spiders.xiaohongshu_spider import XiaohongshuSearchSpider
                cs = XiaohongshuSearchSpider(headless=True)
                cs.start()
                serialized = [_serialize(item) for item in normalized]
                enriched = enrich_comments(cs._page, platform, serialized, max_items=args.max_comment_items)
                # 将评论合并回 IntelItem
                for i, e in enumerate(enriched):
                    if i < len(normalized) and e.get("comments"):
                        normalized[i].comments = e["comments"]
                        normalized[i].comment_count = max(normalized[i].comment_count, len(e["comments"]))
                cs.close()
                with_comments = sum(1 for item in normalized if item.comments)
                logger.info("[{}] 评论采集完成: {}篇有评论", platform, with_comments)
            except Exception as e:
                logger.error("[{}] 评论采集失败: {}", platform, e)

        # Save to file
        out_path = out_dir / f"{platform}_sample.json"
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(
                {
                    "platform": platform,
                    "collected_at": datetime.now(timezone.utc).isoformat(),
                    "keywords": kw_list,
                    "total": len(normalized),
                    "items": [_serialize(item) for item in normalized],
                },
                f, ensure_ascii=False, indent=2, default=str,
            )
        logger.info("[{}] Saved {} items → {}", platform, len(normalized), out_path.name)
        summary[platform] = {"items": len(normalized), "file": out_path.name}

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
