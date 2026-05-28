#!/usr/bin/env python3
"""BGI — Black/Grey-market Intelligence Analysis Agent.

Usage:
    python main.py init-db          # Initialize all databases
    python main.py collect          # Run collectors and save raw data
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

    logger.info("Loading seed slang dictionary...")
    _load_seed_slang()

    logger.info("All databases initialized!")


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


# ============================================================================
# collect
# ============================================================================

@cli.command()
@click.option("--platform", "-p", default="telegram", help="Platform to collect from")
@click.option("--tg-groups", default="", help="Comma-separated Telegram group usernames")
@click.option("--keywords", "-k", default="", help="Comma-separated search keywords")
@click.option("--max-pages", default=3, help="Max pages per keyword")
@click.option("--fetch-replies/--no-fetch-replies", default=True, help="Fetch post replies")
def collect(platform: str, tg_groups: str, keywords: str, max_pages: int, fetch_replies: bool):
    """Run data collectors and save to ods_raw_intel."""
    from collectors.registry import get_collector
    from storage.mysql_store import mysql
    import json as _json

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
            "author_id": item.author_uid,
            "author_name": item.author_username,
            "content_type": item.content_type,
            "content_raw": item.content_raw,
            "raw_status": STATUS_PENDING,
            "collect_time": item.collected_at,
            "metadata": _json.dumps(
                {**item.metadata,
                 "group_id": item.group_id,
                 "message_id": item.message_id},
                ensure_ascii=False, default=str,
            ),
        })
        count += 1
        if count % 10 == 0:
            logger.info(f"Collected {count} items...")
    logger.info(f"Collection complete: {count} items from {platform}")


# ============================================================================
# clean
# ============================================================================

@cli.command()
@click.option("--limit", "-l", default=500, help="Max items to clean per run")
def clean(limit: int):
    """Run cleaning pipeline on raw intel."""
    from cleaner.pipeline import CleaningPipeline
    from storage.mysql_store import mysql

    pipeline = CleaningPipeline()
    pending = mysql.list_raw(status=STATUS_PENDING, limit=limit)

    cleaned, discarded = 0, 0
    for item in pending:
        text = item.get("content_raw", "")
        result = pipeline.process(text)
        if result["should_discard"]:
            mysql.update_raw_status(item["id"], STATUS_DISCARDED,
                                    clean_text=result["text"])
            discarded += 1
        else:
            mysql.update_raw_status(
                item["id"], STATUS_CLEANED,
                clean_text=result["text"],
                simhash=result["simhash"],
            )
            cleaned += 1

        if (cleaned + discarded) % 20 == 0:
            logger.info(f"Cleaned {cleaned + discarded} items...")

    logger.info(f"Cleaning complete: {cleaned} kept, {discarded} discarded")


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

    analyzed = 0
    for item in items:
        text = item.get("content_raw", "")
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
