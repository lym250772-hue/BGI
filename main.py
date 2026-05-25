#!/usr/bin/env python3
"""BGI — Black/Grey-market Intelligence Analysis Agent.

Usage:
    python main.py init-db          # Initialize all databases
    python main.py collect          # Run collectors and save raw data
    python main.py clean            # Run cleaning pipeline on pending items
    python main.py analyze          # Run classification + entity extraction
    python main.py run              # Full pipeline: collect → clean → analyze
    python main.py ui               # Launch Streamlit dashboard
"""
import sys
import click
from loguru import logger

logger.remove()
logger.add(sys.stderr, level="INFO", format="<green>{time:HH:mm:ss}</green> | <level>{level: <8}</level> | {message}")


@click.group()
def cli():
    """BGI Intelligence Analysis Agent"""


@cli.command()
def init_db():
    """Initialize MySQL tables + Neo4j constraints + Milvus collections."""
    from storage.mysql_store import mysql
    from storage.neo4j_store import neo4j
    from storage.milvus_store import milvus

    logger.info("Initializing MySQL...")
    mysql.init_tables()

    logger.info("Initializing Neo4j...")
    neo4j.init_constraints()

    logger.info("Initializing Milvus...")
    milvus.init_collections()

    logger.info("Loading seed slang dictionary...")
    _load_seed_slang()

    logger.info("All databases initialized!")


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


@cli.command()
@click.option("--platform", "-p", default="telegram", help="Platform to collect from")
@click.option("--tg-groups", default="", help="Comma-separated Telegram group usernames")
@click.option("--keywords", "-k", default="", help="Comma-separated search keywords (for weibo/tieba)")
@click.option("--max-pages", default=3, help="Max pages per keyword (for search-based collectors)")
@click.option("--fetch-replies/--no-fetch-replies", default=True, help="Fetch post replies (tieba)")
def collect(platform: str, tg_groups: str, keywords: str, max_pages: int, fetch_replies: bool):
    """Run data collectors."""
    from collectors.registry import get_collector
    from storage.mysql_store import mysql
    import hashlib

    kwargs = {}
    if platform == "telegram" and tg_groups:
        kwargs["group_usernames"] = [g.strip() for g in tg_groups.split(",")]
    elif platform == "weibo" and keywords:
        kwargs["keywords"] = [k.strip() for k in keywords.split(",")]
        kwargs["max_pages_per_keyword"] = max_pages
    elif platform in ("tieba", "zhihu") and keywords:
        kwargs["keywords"] = [k.strip() for k in keywords.split(",")]
        kwargs["max_pages_per_keyword"] = max_pages
        kwargs["fetch_replies"] = fetch_replies
    elif platform in ("xiaohongshu", "forum"):
        kwargs["urls"] = keywords.split(",") if keywords else (tg_groups.split(",") if tg_groups else [])

    collector = get_collector(platform, **kwargs)
    count = 0
    for item in collector.collect():
        mysql.insert_raw({
            "source_platform": item.platform,
            "source_url": item.source_url,
            "author_uid": item.author_uid,
            "author_username": item.author_username,
            "content_type": item.content_type,
            "content_raw": item.content_raw,
            "content": "",
            "image_hash": item.image_hash,
            "simhash": "",
            "priority": "normal",
            "status": "pending",
            "collected_at": item.collected_at,
            "group_id": item.group_id,
            "message_id": item.message_id,
            "metadata": json_dumps_safe(item.metadata),
        })
        count += 1
        if count % 10 == 0:
            logger.info(f"Collected {count} items...")
    logger.info(f"Collection complete: {count} items from {platform}")


@cli.command()
@click.option("--limit", "-l", default=500, help="Max items to clean per run")
def clean(limit: int):
    """Run cleaning pipeline on pending raw data."""
    from cleaner.pipeline import CleaningPipeline
    from storage.mysql_store import mysql

    pipeline = CleaningPipeline()
    pending = mysql.list_raw(status="pending", limit=limit)

    cleaned, discarded = 0, 0
    for item in pending:
        result = pipeline.process(item["content_raw"])
        if result["should_discard"]:
            mysql.update_raw_status(item["id"], "discarded", content=result["text"])
            discarded += 1
        else:
            mysql.update_raw_status(
                item["id"], "cleaned",
                content=result["text"],
                simhash=result["simhash"],
            )
            # Also update priority
            sql = "UPDATE raw_data SET priority=%s WHERE id=%s"
            with mysql.cursor() as c:
                c.execute(sql, (result["priority"], item["id"]))
            cleaned += 1

    logger.info(f"Cleaning complete: {cleaned} kept, {discarded} discarded")


@cli.command()
@click.option("--limit", "-l", default=200, help="Max items to analyze per run")
def analyze(limit: int):
    """Run intent classification + entity extraction on cleaned data."""
    from analyzer.engine import engine
    from storage.mysql_store import mysql

    items = mysql.list_raw(status="cleaned", limit=limit)
    analyzed = 0
    for item in items:
        if not item.get("content"):
            continue
        try:
            engine.run(
                raw_data_id=item["id"],
                text=item["content"],
                platform=item["source_platform"],
            )
            mysql.update_raw_status(item["id"], "analyzed")
            analyzed += 1
        except Exception as exc:
            logger.error(f"Analysis failed for raw_id={item['id']}: {exc}")
    logger.info(f"Analysis complete: {analyzed} items")


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


@cli.command()
def ui():
    """Launch Streamlit dashboard."""
    import subprocess
    from pathlib import Path
    app = Path(__file__).parent / "ui" / "app.py"
    subprocess.run(["streamlit", "run", str(app)])


def json_dumps_safe(obj) -> str:
    import json
    def default(o):
        return str(o)
    return json.dumps(obj, ensure_ascii=False, default=default)


if __name__ == "__main__":
    cli()
