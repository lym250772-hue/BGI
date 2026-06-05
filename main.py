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
@click.option("--platform", "-p", default="weibo", help="Platform: weibo/tieba/zhihu/xiaohongshu/douyin/xianyu/qq_group")
@click.option("--keywords", "-k", default="", help="Comma-separated search keywords")
@click.option("--max-pages", default=3, help="Max pages per keyword")
@click.option("--fetch-replies/--no-fetch-replies", default=True, help="Fetch post replies")
@click.option("--qq-groups", default="", help="Comma-separated QQ group IDs (for qq_group platform)")
@click.option("--duration", default=60, help="Collection duration in minutes (for qq_group)")
def collect(platform: str, keywords: str, max_pages: int, fetch_replies: bool,
            qq_groups: str, duration: int):
    """Run data collectors and save to ods_raw_intel."""
    from collectors.registry import get_collector
    from storage.mysql_store import mysql
    import json as _json

    kwargs = {}
    if platform in ("weibo", "tieba", "zhihu", "xiaohongshu", "douyin", "xianyu") and keywords:
        kwargs["keywords"] = [k.strip() for k in keywords.split(",")]
        kwargs["max_pages_per_keyword"] = max_pages
        if platform in ("tieba", "zhihu"):
            kwargs["fetch_replies"] = fetch_replies
    elif platform == "qq_group" and qq_groups:
        kwargs["group_ids"] = [g.strip() for g in qq_groups.split(",")]
        kwargs["collection_duration_minutes"] = duration
    elif platform == "forum":
        kwargs["urls"] = keywords.split(",") if keywords else []

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
# login
# ============================================================================

@cli.command(name="login-xianyu")
def login_xianyu():
    """Interactive login for Xianyu (saves cookies to persistent browser profile)."""
    from collectors.spiders.xianyu_spider import XianyuSearchSpider
    XianyuSearchSpider.interactive_login(headless=False)


# ============================================================================
# persona — AI人物钓鱼式情报收集
# ============================================================================

@cli.group()
def persona():
    """AI Persona-based intelligence collection."""


@persona.command("list")
def persona_list():
    """List available persona profiles."""
    from persona.registry import list_personas, PERSONA_MAP
    personas = list_personas()
    if not personas:
        logger.warning("No personas found in persona/personas/")
        return
    logger.info(f"Available personas ({len(personas)}):")
    for name in personas:
        p = PERSONA_MAP.get(name, {})
        logger.info(f"  - {name}: {p.get('display_name', '')} — {p.get('identity', {}).get('role', '')}")


@persona.command("run")
@click.option("--persona", "-p", required=True,
              help="Persona name (e.g., ecommerce_buyer, brusher_seeker, account_unban)")
@click.option("--target", "-t", required=True,
              help="Target: 'platform:uid:username:description'")
@click.option("--message", "-m", default=None,
              help="Optional initial message (otherwise LLM generates)")
def persona_run(persona_name: str, target: str, message: str):
    """Run a persona conversation against a target.

    Example:
      python main.py persona run \\
        --persona ecommerce_buyer \\
        --target "xianyu:user123:张三:提供抖音涨粉服务，真人粉丝不掉，50元1000粉"

    Target format: platform:uid:username:description
    The 'description' is the seller's listing/bio that the persona will engage with.
    """
    import json as _json

    parts = target.split(":", 3)
    if len(parts) < 4:
        logger.error("Target format: platform:uid:username:description")
        logger.error("Example: xianyu:user123:张三:提供抖音涨粉服务，真人粉不掉")
        return

    platform, uid, username, context = parts

    from persona.engine import PersonaEngine
    engine = PersonaEngine()

    logger.info(f"Persona [{persona_name}] engaging target [{username}] on [{platform}]...")
    logger.info(f"Target context: {context[:100]}...")

    result = engine.run_conversation(
        persona_name=persona_name,
        target_platform=platform,
        target_uid=uid,
        target_username=username,
        target_context=context,
        initial_message=message,
    )

    # Store result (if MySQL is available)
    try:
        from persona.collector import PersonaCollector
        from storage.mysql_store import mysql
        intel_item = PersonaCollector._to_intel(result)
        mysql.insert_raw({
            "source_platform": "persona",
            "source_url": f"persona://{result.conversation_id}",
            "author_id": result.target_uid,
            "author_name": result.target_username,
            "content_type": "conversation",
            "content_raw": result.conversation_summary,
            "raw_status": STATUS_PENDING,
            "collect_time": result.collected_at,
            "metadata": _json.dumps(intel_item.metadata, ensure_ascii=False, default=str),
        })
        logger.info("Persona conversation stored to database")
    except Exception as exc:
        logger.warning(f"Database storage skipped: {exc}")

    # Print summary
    logger.info("=" * 60)
    logger.info(f"  Persona: {result.persona_name}")
    logger.info(f"  Turns: {len(result.raw_messages)}")
    logger.info(f"  Safety flags: {len(result.safety_flags)}")
    logger.info(f"  Summary: {result.conversation_summary[:200]}...")
    if result.extracted_info:
        logger.info(f"  Extracted intel:")
        for k, v in result.extracted_info.items():
            if v and v != "未知":
                logger.info(f"    - {k}: {v}")
    if result.safety_flags:
        logger.warning(f"  ⚠️  Safety triggers: {result.safety_flags}")
    logger.info("=" * 60)


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
