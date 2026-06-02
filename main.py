#!/usr/bin/env python3
"""BGI — Black/Grey-market Intelligence Analysis Agent.

Usage:
    python main.py init-db          # Initialize all databases
    python main.py login -p PLATFORM # Interactive login (browser popup → manual login → auto-save cookies)
    python main.py collect          # Run single-platform collector
    python main.py collect-all      # Run ALL platforms concurrently
    python main.py clean            # Run cleaning pipeline on pending items
    python main.py analyze          # Run classification + entity extraction
    python main.py run              # Full pipeline: collect → clean → analyze
    python main.py ui               # Launch Streamlit dashboard
    python main.py api              # Launch FastAPI server
"""
import sys
import click
from loguru import logger

logger.remove()
logger.add(
    sys.stderr, level="INFO",
    format="<green>{time:HH:mm:ss}</green> | <level>{level: <8}</level> | {message}",
)


# Status constants (aligned to PROJECT_PLAN.md ods_raw_intel.raw_status)
STATUS_PENDING = "RAW_COLLECTED"
STATUS_CLEANED = "CLEANED"
STATUS_ANALYZED = "ANALYZED"
STATUS_DISCARDED = "DISCARDED"


@click.group()
def cli():
    """BGI Intelligence Analysis Agent"""


# ============================================================================
# init-db
# ============================================================================

@cli.command()
def init_db():
    """Initialize MySQL tables + Neo4j constraints + Milvus collections."""
    from storage.mysql_store import mysql
    from storage.neo4j_store import neo4j
    from storage.milvus_store import milvus

    logger.info("Initializing MySQL (9-table ODS/DWD/DIM/ADS schema)...")
    mysql.init_tables()

    logger.info("Migrating legacy data to new tables...")
    stats = mysql.migrate_old_data()
    for k, v in stats.items():
        logger.info(f"  {k}: {v}")

    logger.info("Normalizing status values to uppercase...")
    _normalize_status()

    logger.info("Initializing Neo4j...")
    neo4j.init_constraints()

    logger.info("Initializing Milvus...")
    milvus.init_collections()

    from config.settings import settings
    if settings.doris_enabled:
        logger.info("Initializing Doris (OLAP)...")
        try:
            from storage.doris_store import doris
            doris.init_tables()
        except Exception as exc:
            logger.warning(f"Doris init skipped (not critical): {exc}")
    else:
        logger.info("Doris disabled; set BGI_DORIS_ENABLED=true to enable OLAP")

    logger.info("Loading seed slang dictionary...")
    _load_seed_slang()

    logger.info("All databases initialized!")


# ============================================================================
# login — interactive browser login, auto-save cookies
# ============================================================================

# 平台名 → Spider 类映射（用于 login 命令）
_LOGIN_SPIDER_MAP: dict[str, type] = {}

def _get_login_spider_map() -> dict[str, type]:
    """懒加载平台→Spider映射，避免触发浏览器导入。"""
    if _LOGIN_SPIDER_MAP:
        return _LOGIN_SPIDER_MAP
    from collectors.spiders.weibo_spider import WeiboSearchSpider
    from collectors.spiders.tieba_spider import TiebaSpider
    from collectors.spiders.zhihu_spider import ZhihuSearchSpider
    from collectors.spiders.xiaohongshu_spider import XiaohongshuSearchSpider
    from collectors.spiders.douyin_spider import DouyinSearchSpider
    _LOGIN_SPIDER_MAP.update({
        "weibo": WeiboSearchSpider,
        "tieba": TiebaSpider,
        "zhihu": ZhihuSearchSpider,
        "xiaohongshu": XiaohongshuSearchSpider,
        "douyin": DouyinSearchSpider,
    })
    return _LOGIN_SPIDER_MAP


@cli.command()
@click.option("--platform", "-p", required=True,
              help="Platform: weibo / tieba / zhihu / xiaohongshu / douyin / all")
@click.option("--headful/--headless", default=True,
              help="Show browser window (default: --headful, required for manual login)")
def login(platform: str, headful: bool):
    """Interactive login: open browser → log in manually → auto-save cookies.

    \b
    Examples:
        python main.py login -p weibo        # Login to Weibo
        python main.py login -p zhihu        # Login to Zhihu
        python main.py login -p xiaohongshu  # Login to Xiaohongshu
        python main.py login -p douyin       # Login to Douyin
        python main.py login -p all          # Login to all platforms one by one
    """
    spider_map = _get_login_spider_map()

    if platform == "all":
        platforms = list(spider_map.keys())
        logger.info(f"将依次登录 {len(platforms)} 个平台: {', '.join(platforms)}")
        for i, p in enumerate(platforms, 1):
            logger.info(f"\n[{i}/{len(platforms)}] 登录 {p} ...")
            spider_map[p].interactive_login(headless=not headful)
        logger.info("\n全部平台登录完成！")
        return

    if platform not in spider_map:
        available = ", ".join(spider_map.keys())
        logger.error(f"未知平台 '{platform}'。可选: {available}, all")
        return

    spider_map[platform].interactive_login(headless=not headful)


def _normalize_status():
    """Convert legacy lowercase statuses to PROJECT_PLAN uppercase format."""
    from storage.mysql_store import mysql
    mapping = {
        "pending": STATUS_PENDING,
        "cleaned": STATUS_CLEANED,
        "analyzed": STATUS_ANALYZED,
        "discarded": STATUS_DISCARDED,
    }
    with mysql.cursor() as c:
        for old, new in mapping.items():
            c.execute(
                "UPDATE ods_raw_intel SET raw_status=%s WHERE raw_status=%s",
                (new, old),
            )
        logger.info("Status values normalized")


def _load_seed_slang():
    """Load seed slang data from seed file into MySQL and Milvus."""
    import json
    from config.settings import settings
    seed_path = settings.slang_dict_path / "seed_slang.json"
    if not seed_path.exists():
        logger.warning(f"Seed slang file not found: {seed_path}")
        return
    with open(seed_path, "r", encoding="utf-8") as f:
        slangs = json.load(f)
    from storage.mysql_store import mysql
    for item in slangs:
        mysql.insert_slang(item)
    logger.info(f"Loaded {len(slangs)} seed slang entries")


def _resolve_keywords(keywords: str, keyword_file: str) -> list[str] | None:
    """Resolve keyword list from CLI args or JSON file.

    Priority: --keywords > --keyword-file.  Returns None if no keywords found.
    """
    import json as _json

    kw_list = []
    if keywords:
        kw_list = [k.strip() for k in keywords.split(",") if k.strip()]
    if not kw_list and keyword_file:
        try:
            with open(keyword_file, "r", encoding="utf-8") as f:
                kw_data = _json.load(f)
            if isinstance(kw_data, dict):
                kw_list = kw_data.get("quick_keywords", [])
                if not kw_list:
                    for cat, kws in kw_data.get("keywords", {}).items():
                        kw_list.extend(kws)
            elif isinstance(kw_data, list):
                kw_list = kw_data
        except Exception as exc:
            logger.error("Failed to load keyword file: {}", exc)
    return kw_list if kw_list else None


def _warn_missing_cookies(platforms: list[str]) -> None:
    """Check cookie availability for browser-based platforms."""
    from collectors.spiders.base_spider import BaseSpider
    for p in platforms:
        if p == "telegram":
            continue
        cookies = BaseSpider.load_cookies(p)
        if not cookies:
            logger.warning(
                "  [{}] No cookies found. Run: python main.py login -p {}",
                p, p,
            )


# ============================================================================
# collect
# ============================================================================

@cli.command()
@click.option("--platform", "-p", default="telegram", help="Platform to collect from")
@click.option("--tg-groups", default="", help="Comma-separated Telegram group usernames")
@click.option("--keywords", "-k", default="", help="Comma-separated search keywords")
@click.option("--keyword-file", default="", help="JSON keyword file path (e.g. data/grey_keywords.json)")
@click.option("--max-pages", default=10, help="Max pages per keyword (0 = auto, collect until empty)")
@click.option("--max-items", default=0, help="Max items per keyword (0 = unlimited)")
@click.option("--fetch-replies/--no-fetch-replies", default=True, help="Fetch post replies/comments")
@click.option("--incremental/--no-incremental", default=False, help="Incremental collection (skip previously collected)")
@click.option("--batch-size", default=100, help="Items per batch insert")
def collect(platform: str, tg_groups: str, keywords: str, keyword_file: str,
            max_pages: int, max_items: int, fetch_replies: bool,
            incremental: bool, batch_size: int):
    """Run data collectors and save to ods_raw_intel (batch insert)."""
    from collectors.registry import get_collector
    from storage.mysql_store import mysql
    from collectors.spiders.base_spider import BaseSpider
    import json as _json, time as _time

    # 检查 Cookie 是否存在
    if platform in ("weibo", "tieba", "zhihu", "xiaohongshu", "douyin"):
        cookies = BaseSpider.load_cookies(platform)
        if not cookies:
            logger.warning(f"  ⚠️  {platform} 未配置 Cookie！")
            logger.warning(f"  请先运行: python main.py login -p {platform}")
            logger.warning(f"  或在 data/raw/{platform}_cookies.json 放置 Cookie 文件")
            logger.warning(f"  继续尝试采集（可能失败）...")
            logger.info("")

    kw_list = _resolve_keywords(keywords, keyword_file)
    if not kw_list:
        logger.error("No keywords specified. Use --keywords or --keyword-file")
        return

    logger.info("关键词列表 ({}): {}{}", len(kw_list),
                ", ".join(kw_list[:10]),
                "..." if len(kw_list) > 10 else "")

    kwargs = {}
    if platform == "telegram" and tg_groups:
        kwargs["group_usernames"] = [g.strip() for g in tg_groups.split(",")]
    elif platform == "weibo":
        kwargs["keywords"] = kw_list
        kwargs["max_pages_per_keyword"] = max_pages
    elif platform in ("tieba", "zhihu"):
        kwargs["keywords"] = kw_list
        kwargs["max_pages_per_keyword"] = max_pages
        kwargs["max_items_per_keyword"] = max_items
        kwargs["fetch_replies"] = fetch_replies
        kwargs["fetch_answers"] = fetch_replies  # zhihu: answers = replies
        kwargs["fetch_comments"] = fetch_replies  # zhihu: comments = replies
        kwargs["incremental"] = incremental
    elif platform in ("xiaohongshu", "douyin"):
        kwargs["keywords"] = kw_list
        kwargs["max_pages_per_keyword"] = max_pages
        kwargs["max_items_per_keyword"] = max_items
    elif platform == "forum":
        kwargs["urls"] = kw_list

    t_start = _time.time()
    collector = get_collector(platform, **kwargs)
    batch, total, errors = [], 0, 0

    def flush_batch():
        """将累积的批次一次性写入 MySQL。"""
        nonlocal errors
        if not batch:
            return
        try:
            with mysql.cursor() as c:
                sql = """INSERT INTO ods_raw_intel
                    (source_platform, source_channel, source_url, source_keyword,
                     author_id, author_name, publish_time, collect_time,
                     content_type, content_raw, media_urls, media_hash,
                     crawl_batch_id, raw_status, metadata)
                    VALUES (%(source_platform)s, %(source_channel)s, %(source_url)s, %(source_keyword)s,
                            %(author_id)s, %(author_name)s, %(publish_time)s, %(collect_time)s,
                            %(content_type)s, %(content_raw)s, %(media_urls)s, %(media_hash)s,
                            %(crawl_batch_id)s, %(raw_status)s, %(metadata)s)"""
                c.executemany(sql, batch)
        except Exception as exc:
            logger.error(f"Batch insert failed: {exc}")
            errors += len(batch)
        batch.clear()

    for item in collector.collect():
        batch.append({
            "source_platform": item.platform,
            "source_url": item.source_url,
            "source_channel": item.group_id,
            "source_keyword": item.metadata.get("keyword", ""),
            "author_id": item.author_uid,
            "author_name": item.author_username,
            "content_type": item.content_type,
            "content_raw": item.content_raw,
            "publish_time": item.collected_at,
            "collect_time": item.collected_at,
            "raw_status": STATUS_PENDING,
            "media_urls": _json.dumps([]),
            "media_hash": "",
            "crawl_batch_id": "",
            "metadata": _json.dumps(
                {**item.metadata,
                 "group_id": item.group_id,
                 "message_id": item.message_id},
                ensure_ascii=False, default=str,
            ),
        })
        total += 1
        if len(batch) >= batch_size:
            flush_batch()
            logger.info(f"Collected {total} items...")

    flush_batch()  # final flush
    elapsed = _time.time() - t_start
    rate = total / elapsed if elapsed > 0 else 0
    logger.info(
        f"Collection complete: {total} items from {platform} "
        f"({elapsed:.1f}s, {rate:.1f} items/s, {errors} errors)"
    )


# ============================================================================
# collect-all — concurrent multi-platform collection
# ============================================================================

@cli.command("collect-all")
@click.option("--keywords", "-k", default="", help="Comma-separated keywords (applied to all platforms)")
@click.option("--keyword-file", default="", help="JSON keyword file path (e.g. data/grey_keywords.json)")
@click.option("--platforms", default="weibo,tieba,zhihu,douyin,xiaohongshu",
              show_default=True,
              help="Comma-separated platforms to run concurrently")
@click.option("--max-pages", default=10, help="Max pages per keyword per platform")
@click.option("--max-items", default=0, help="Max items per keyword per platform (0=unlimited)")
@click.option("--fetch-replies/--no-fetch-replies", default=True)
@click.option("--incremental/--no-incremental", default=False)
@click.option("--headless/--no-headless", default=True)
@click.option("--no-checkpoint-resume", is_flag=True, help="Disable checkpoint resume (fresh start)")
@click.option("--batch-size", default=100, help="MySQL batch insert size")
@click.option("--rpm-per-platform", default=20, help="Max keyword-start rate per platform (req/min)")
@click.option("--tg-groups", default="", help="Telegram group usernames (comma-separated)")
def collect_all(keywords: str, keyword_file: str, platforms: str,
                max_pages: int, max_items: int, fetch_replies: bool,
                incremental: bool, headless: bool, no_checkpoint_resume: bool,
                batch_size: int, rpm_per_platform: int, tg_groups: str):
    """Run ALL platform collectors concurrently with unified keywords.

    \b
    Each platform runs in its own thread.  Write pipeline uses a single
    background thread for batch MySQL inserts.  Ctrl+C triggers graceful
    shutdown with checkpoint save.

    \b
    Examples:
        python main.py collect-all -k "刷单" --max-pages 2
        python main.py collect-all -k "刷单,接码,跑分" --max-pages 3
        python main.py collect-all -k "刷单" --platforms weibo,zhihu --max-pages 1
        python main.py collect-all --keyword-file data/grey_keywords.json --max-pages 2
        python main.py collect-all -k "刷单" --rpm-per-platform 10 --no-checkpoint-resume
    """
    import time as _time
    from collectors.orchestrator import (
        CollectionOrchestrator, PlatformTask, SpiderType,
    )
    from storage.write_pipeline import ConcurrentWritePipeline

    # Resolve keywords
    kw_list = _resolve_keywords(keywords, keyword_file)
    if not kw_list:
        logger.error("No keywords specified. Use --keywords or --keyword-file")
        return

    # Parse platforms
    platform_list = [p.strip() for p in platforms.split(",") if p.strip()]
    if not platform_list:
        logger.error("No platforms specified")
        return

    # Resolve Telegram groups
    tg_list = [g.strip() for g in tg_groups.split(",") if g.strip()] if tg_groups else []

    # Build tasks
    tasks: list[PlatformTask] = []
    for p in platform_list:
        st = _spider_type_for(p)
        task = PlatformTask(
            platform=p,
            keywords=list(kw_list),  # copy — each platform gets its own list
            spider_type=st,
            max_pages=max_pages,
            max_items=max_items,
            fetch_replies=fetch_replies,
            incremental=incremental,
            headless=headless,
            resume_from_checkpoint=not no_checkpoint_resume,
            requests_per_minute=rpm_per_platform,
            tg_groups=tg_list if p == "telegram" else [],
        )
        tasks.append(task)

    # Warn about missing cookies
    _warn_missing_cookies(platform_list)

    logger.info(
        "Starting multi-platform collection: {} platforms, {} keywords each",
        len(tasks), len(kw_list),
    )
    logger.info("Platforms: {}", ", ".join(t.platform for t in tasks))
    logger.info(
        "Keywords: {}{}",
        ", ".join(kw_list[:10]),
        "..." if len(kw_list) > 10 else "",
    )
    logger.info("")

    # Start write pipeline
    pipeline = ConcurrentWritePipeline(batch_size=batch_size)
    pipeline.start()

    # Run orchestrator
    t0 = _time.time()
    orch = CollectionOrchestrator(tasks, pipeline)
    stats = orch.run_all()

    # Finish writes
    write_stats = pipeline.finish()
    elapsed = _time.time() - t0

    # Final summary
    logger.info("=" * 60)
    logger.info(
        "Collection complete: {} items in {:.1f}s ({:.1f}/s), {} errors",
        stats["total_items"], elapsed, stats["items_per_sec"],
        stats["total_errors"],
    )
    logger.info(
        "Write pipeline: {} inserted, {} failed, {} batches, {} retries",
        write_stats["inserted"], write_stats["errors"],
        write_stats["batches"], write_stats["retries"],
    )
    for p, d in sorted(stats.get("platforms", {}).items()):
        logger.info(
            "  [{}] {} items, {} errors — {}",
            p, d["items"], d["errors"], d["status"],
        )


def _spider_type_for(platform: str):
    """Map platform name to SpiderType."""
    from collectors.orchestrator import SpiderType
    if platform in ("weibo", "zhihu"):
        return SpiderType.HTTP
    elif platform == "telegram":
        return SpiderType.TELETHON
    else:
        return SpiderType.PLAYWRIGHT


# ============================================================================
# clean
# ============================================================================

@cli.command()
@click.option("--limit", "-l", default=500, help="Max items to clean per run")
def clean(limit: int):
    """Run cleaning pipeline on raw intel."""
    from cleaner.pipeline import CleaningPipeline
    from storage.mysql_store import mysql
    import json as _json

    pipeline = CleaningPipeline()

    # Fetch existing simhashes for dedup
    existing_hashes = []
    try:
        with mysql.cursor() as c:
            c.execute("SELECT simhash FROM dwd_clean_intel WHERE simhash IS NOT NULL")
            existing_hashes = [r["simhash"] for r in c.fetchall()]
        logger.info(f"Loaded {len(existing_hashes)} existing hashes for dedup")
    except Exception:
        pass

    pending = mysql.list_raw(status=STATUS_PENDING, limit=limit)

    cleaned, discarded = 0, 0
    for item in pending:
        text = item.get("content_raw", "")
        platform = item.get("source_platform", "")
        # 解析 metadata JSON（可能是字符串或已解析的 dict）
        metadata_raw = item.get("metadata", {})
        if isinstance(metadata_raw, str):
            try:
                metadata = _json.loads(metadata_raw)
            except Exception:
                metadata = {}
        else:
            metadata = metadata_raw

        result = pipeline.process(text, existing_hashes,
                                  platform=platform, metadata=metadata)
        noise_score = result.get("noise_score", 0.0)
        if result["should_discard"]:
            mysql.update_raw_status(item["id"], STATUS_DISCARDED,
                                    clean_text=result["text"],
                                    simhash=result["simhash"],
                                    priority=result["priority"],
                                    noise_score=noise_score,
                                    clean_reason=result.get("discard_reason", ""))
            discarded += 1
        else:
            mysql.update_raw_status(
                item["id"], STATUS_CLEANED,
                clean_text=result["text"],
                simhash=result["simhash"],
                priority=result["priority"],
                noise_score=noise_score,
                clean_reason=f"risk:{result.get('risk_reason','')}" if result.get('risk_reason') else "",
            )
            cleaned += 1

        if (cleaned + discarded) % 20 == 0:
            logger.info(f"Cleaned {cleaned + discarded} items...")

    logger.info(f"Cleaning complete: {cleaned} kept, {discarded} discarded")


# ============================================================================
# ocr — extract text from images (XHS/Douyin)
# ============================================================================

@cli.command()
@click.option("--limit", "-l", default=100, help="Max items to process")
@click.option("--platform", "-p", default="douyin,xiaohongshu",
              help="Platforms to OCR (comma-separated)")
def ocr(limit: int, platform: str):
    """Run OCR on images from collected data (XHS notes, Douyin covers)."""
    from cleaner.media_bridge import media_bridge
    platforms = [p.strip() for p in platform.split(",") if p.strip()]
    logger.info(f"开始 OCR 处理: limit={limit}, platforms={platforms}")
    count = media_bridge.process_pending(limit=limit, platforms=platforms)
    logger.info(f"OCR 完成: {count} 条已处理")


# ============================================================================
# analyze
# ============================================================================

@cli.command()
@click.option("--limit", "-l", default=200, help="Max items to analyze per run")
def analyze(limit: int):
    """Run full analysis pipeline (classify + extract + evidence + score + report)."""
    from analyzer.engine import engine
    from storage.mysql_store import mysql

    items = mysql.list_raw(status=STATUS_CLEANED, limit=limit)
    if not items:
        logger.warning("No cleaned items found. Run 'python main.py clean' first.")
        return

    # Preload clean texts for all items
    clean_map = {}
    with mysql.cursor() as c:
        c.execute(
            "SELECT raw_id, merged_text, clean_text FROM dwd_clean_intel WHERE raw_id IN (%s)"
            % ",".join(["%s"] * len(items)),
            [it["id"] for it in items],
        )
        for row in c.fetchall():
            clean_map[row["raw_id"]] = row

    analyzed = 0
    for item in items:
        # Priority: merged_text > clean_text > content_raw
        clean = clean_map.get(item["id"], {})
        text = clean.get("merged_text") or clean.get("clean_text") or item.get("content_raw", "")
        if not text or not text.strip():
            continue
        try:
            engine.run(
                raw_data_id=item["id"],
                text=text,
                platform=item.get("source_platform", "unknown"),
            )
            # engine.run already updates status to ANALYZED via _persist_all
            analyzed += 1
            if analyzed % 5 == 0:
                logger.info(f"Analyzed {analyzed} items...")
        except Exception as exc:
            logger.error(f"Analysis failed for raw_id={item['id']}: {exc}")

    logger.info(f"Analysis complete: {analyzed} items")


# ============================================================================
# run — full pipeline
# ============================================================================

@cli.command()
@click.option("--limit", "-l", default=500, help="Max items per stage")
def run(limit: int):
    """Run full pipeline: collect → clean → analyze."""
    logger.info("=== Stage 1: Collect ===")
    # collect() is called separately with platform selection
    logger.info("=== Stage 2: Clean ===")
    ctx = click.Context(clean)
    ctx.invoke(clean, limit=limit)
    logger.info("=== Stage 3: Analyze ===")
    ctx = click.Context(analyze)
    ctx.invoke(analyze, limit=limit)
    logger.info("=== Pipeline complete ===")


# ============================================================================
# ui
# ============================================================================

@cli.command()
def ui():
    """Launch Streamlit dashboard."""
    import subprocess
    from pathlib import Path
    app = Path(__file__).parent / "ui" / "app.py"
    subprocess.run(["streamlit", "run", str(app)])


# ============================================================================
# api
# ============================================================================

@cli.command()
@click.option("--host", default="0.0.0.0", help="Bind address")
@click.option("--port", default=8000, help="Bind port")
def api(host: str, port: int):
    """Launch FastAPI server."""
    import uvicorn
    uvicorn.run("api.server:app", host=host, port=port, reload=True)


if __name__ == "__main__":
    cli()
