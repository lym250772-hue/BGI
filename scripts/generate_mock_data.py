#!/usr/bin/env python3
"""Generate realistic mock black/grey-market intelligence data for demo purposes.

Produces synthetic Telegram-style messages with known entities (phone numbers,
WeChat IDs, URLs, QQ groups), passes them through the full analysis pipeline,
and seeds all three databases (MySQL / Neo4j / Milvus) so the Streamlit
dashboard shows a convincing end-to-end workflow.

Usage:
    python scripts/generate_mock_data.py            # generate 50 intel items
    python scripts/generate_mock_data.py -n 200     # generate 200 items
    python scripts/generate_mock_data.py --seed 42  # reproducible output
"""

import argparse
import random
import sys
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from schema import Platform, ContentType, Priority, IntentLabel

# ── Mock data templates ──────────────────────────────────────────────────────

_TEMPLATES: list[dict] = [
    # 诈骗 (Fraud) — 8 items
    {
        "content": "最新刷单返利项目，日赚500+，无需押金。加微信 {wechat} 了解详情，名额有限！链接：{url}",
        "platform": "telegram",
        "intent_label": "诈骗",
        "priority": "critical",
        "entities": [
            {"type": "wechat", "value": "shuadan666"},
            {"type": "url", "value": "https://shuadan-hui.com/join?ref=abc123"},
        ],
    },
    {
        "content": "信用贷款秒批，黑户可做，手续费仅5%。联系电话 {phone}，QQ群 {qq}",
        "platform": "tieba",
        "intent_label": "诈骗",
        "priority": "high",
        "entities": [
            {"type": "phone", "value": "13812345678"},
            {"type": "qq", "value": "85234671"},
        ],
    },
    {
        "content": "兼职打字员，每小时80元，在家办公。先交保证金200元。联系QQ：{qq}",
        "platform": "weibo",
        "intent_label": "诈骗",
        "priority": "high",
        "entities": [
            {"type": "qq", "value": "77321654"},
        ],
    },
    {
        "content": "内部股票消息，跟单稳赚。免费推荐牛股，加群 {qq} 领取每日金股。直播间 {url}",
        "platform": "telegram",
        "intent_label": "诈骗",
        "priority": "critical",
        "entities": [
            {"type": "qq", "value": "99651234"},
            {"type": "url", "value": "https://niugu-live.com/room/888"},
        ],
    },
    # 引流 (Traffic Driving) — 6 items
    {
        "content": "抖音无人直播技术，全套教程+工具，包教包会。详情看主页，联系微信 {wechat}",
        "platform": "telegram",
        "intent_label": "引流",
        "priority": "high",
        "entities": [
            {"type": "wechat", "value": "douyin_pro888"},
            {"type": "url", "value": "https://linktr.ee/douyin_pro"},
        ],
    },
    {
        "content": "色流精准粉丝，日引500+，转化率高。QQ群：{qq}，进群看效果数据",
        "platform": "forum",
        "intent_label": "引流",
        "priority": "high",
        "entities": [
            {"type": "qq", "value": "44567890"},
        ],
    },
    {
        "content": "小红书笔记代发，千粉账号矩阵，曝光10w+。合作加V：{wechat}",
        "platform": "xiaohongshu",
        "intent_label": "引流",
        "priority": "normal",
        "entities": [
            {"type": "wechat", "value": "xhs_seo_vip"},
        ],
    },
    # 作弊 (Cheating) — 6 items
    {
        "content": "抖音直播间挂铁，真人互动，在线人数瞬间破千。软件下载：{url}，客服QQ：{qq}",
        "platform": "telegram",
        "intent_label": "作弊",
        "priority": "high",
        "entities": [
            {"type": "url", "value": "https://douyin-bot.pro/download"},
            {"type": "qq", "value": "55321987"},
        ],
    },
    {
        "content": "薅羊毛自动化脚本，支持淘宝/京东/拼多多全平台。支持定制规则，联系 {wechat}",
        "platform": "telegram",
        "intent_label": "作弊",
        "priority": "high",
        "entities": [
            {"type": "wechat", "value": "haoyangmao_tool"},
        ],
    },
    {
        "content": "游戏外挂/辅助，支持吃鸡/王者/原神，稳定不封号。购买地址 {url}",
        "platform": "forum",
        "intent_label": "作弊",
        "priority": "critical",
        "entities": [
            {"type": "url", "value": "https://gamecheat.club/buy/hack2024"},
        ],
    },
    # 账号黑产 (Account Fraud) — 6 items
    {
        "content": "出售微信号/QQ号/抖音号，实名已过，可换绑手机。大量现货，价格美丽。联系 {wechat}",
        "platform": "telegram",
        "intent_label": "账号黑产",
        "priority": "critical",
        "entities": [
            {"type": "wechat", "value": "accounts_shop"},
            {"type": "phone", "value": "13987654321"},
        ],
    },
    {
        "content": "接码平台，支持国内+海外，一码一用，价格低至0.1元。注册地址：{url}",
        "platform": "telegram",
        "intent_label": "账号黑产",
        "priority": "high",
        "entities": [
            {"type": "url", "value": "https://jiema.pro/register?invite=abc"},
        ],
    },
    {
        "content": "支付宝/微信实名认证服务，无需本人。三要素/四要素均有。QQ群 {qq} 下单",
        "platform": "forum",
        "intent_label": "账号黑产",
        "priority": "critical",
        "entities": [
            {"type": "qq", "value": "77894561"},
        ],
    },
    # 内容违规 (Content Violation) — 4 items
    {
        "content": "全套高清影视资源，包含最新院线片。网盘群共享，加微信 {wechat} 进群",
        "platform": "weibo",
        "intent_label": "内容违规",
        "priority": "normal",
        "entities": [
            {"type": "wechat", "value": "movies_share_2024"},
            {"type": "url", "value": "https://pan.baidu.com/s/1abc123def"},
        ],
    },
    {
        "content": "政治敏感内容代发，覆盖全网平台，按条计费。渠道稳定，联系TG：{wechat}",
        "platform": "telegram",
        "intent_label": "内容违规",
        "priority": "high",
        "entities": [
            {"type": "wechat", "value": "political_sender"},
        ],
    },
    # 工具交易 (Tool Trading) — 4 items
    {
        "content": "出售Web漏洞扫描器/脱库工具/SQL注入工具包。支持担保交易。下载地址 {url}，联系 {qq}",
        "platform": "telegram",
        "intent_label": "工具交易",
        "priority": "critical",
        "entities": [
            {"type": "url", "value": "https://hacktoolz.org/dl/scanner_pro"},
            {"type": "qq", "value": "33456789"},
        ],
    },
    {
        "content": "IP代理池，支持HTTP/SOCKS5，每日更新10w+IP，可用于爬虫/注册/刷量。购买：{url}",
        "platform": "telegram",
        "intent_label": "工具交易",
        "priority": "high",
        "entities": [
            {"type": "url", "value": "https://proxy-pool.io/buy/10w-ips"},
        ],
    },
    # 直播违规 (Live Streaming Violation) — 4 items
    {
        "content": "抖音直播色情引流技术教学，规避平台审核。全套教程+话术，价格199。加微信 {wechat}",
        "platform": "telegram",
        "intent_label": "直播违规",
        "priority": "high",
        "entities": [
            {"type": "wechat", "value": "live_se_tech"},
        ],
    },
    {
        "content": "直播间内诱导未成年人打赏话术合集，已验证高转化。QQ群文件下载：{qq}",
        "platform": "forum",
        "intent_label": "直播违规",
        "priority": "critical",
        "entities": [
            {"type": "qq", "value": "55678901"},
        ],
    },
]


# ── Entity value pools ───────────────────────────────────────────────────────

_WECHAT_POOL  = [f"wx_pro_{i}" for i in range(100, 199)]
_QQ_POOL      = [str(random.randint(10000000, 99999999)) for _ in range(50)]
_PHONE_POOL   = [f"1{random.randint(30, 99)}{random.randint(10000000, 99999999)}" for _ in range(30)]
_URL_POOL     = [
    f"https://bad{i}-site.com/page?id={i}" for i in range(20)
] + [
    f"http://evil{i}.xyz/download" for i in range(20)
]


def _fill_placeholders(template: dict) -> dict:
    """Replace {wechat}, {qq}, {phone}, {url} with random pool values."""
    content = template["content"]
    entities = []

    for entity in template["entities"]:
        etype = entity["type"]
        if etype == "wechat":
            val = random.choice(_WECHAT_POOL)
        elif etype == "qq":
            val = random.choice(_QQ_POOL)
        elif etype == "phone":
            val = random.choice(_PHONE_POOL)
        elif etype == "url":
            val = random.choice(_URL_POOL)
        else:
            val = entity["value"]

        content = content.replace(f"{{{etype}}}", str(val), 1)
        entities.append({"type": etype, "value": str(val)})

    return {
        "content": content,
        "platform": template["platform"],
        "intent_label": template["intent_label"],
        "priority": template["priority"],
        "entities": entities,
    }


def generate_items(count: int = 50, seed: int = None) -> list[dict]:
    """Generate `count` mock intel items with varied content and entities."""
    if seed is not None:
        random.seed(seed)

    items = []
    base_time = datetime.now() - timedelta(days=7)

    for i in range(count):
        template = random.choice(_TEMPLATES)
        filled = _fill_placeholders(template)

        # Vary the timestamp
        offset_minutes = random.randint(0, 7 * 24 * 60)
        ts = base_time + timedelta(minutes=offset_minutes)

        items.append({
            "content_raw": filled["content"],
            "source_platform": filled["platform"],
            "content_type": "text",
            "intent_label": filled["intent_label"],
            "priority": filled["priority"],
            "collected_at": ts,
            "entities": filled["entities"],
        })

    # Sort by time for realistic ordering
    items.sort(key=lambda x: x["collected_at"])
    return items


# ── Data injector ────────────────────────────────────────────────────────────

def inject_to_mysql(items: list[dict]) -> int:
    """Insert mock intel items and their entities into MySQL.

    Returns the number of items inserted.
    """
    from storage.mysql_store import mysql

    inserted = 0
    for item in items:
        try:
            raw_id = mysql.insert_raw({
                "content_raw": item["content_raw"],
                "source_platform": item["source_platform"],
                "content_type": item["content_type"],
                "status": "pending",
                "priority": item["priority"],
                "collected_at": item["collected_at"].strftime("%Y-%m-%d %H:%M:%S"),
            })

            # Insert analysis result (simulated classification)
            mysql.insert_analysis({
                "raw_data_id": raw_id,
                "intent_label": item["intent_label"],
                "sub_label": "",
                "confidence": round(random.uniform(0.75, 0.98), 3),
                "classification_method": "mock",
                "is_high_risk": item["priority"] in ("high", "critical"),
            })

            # Update raw_data status to analyzed
            with mysql.cursor() as c:
                c.execute(
                    "UPDATE raw_data SET status='analyzed' WHERE id=%s",
                    (raw_id,),
                )

            # Insert entities
            for ent in item.get("entities", []):
                mysql.insert_entity({
                    "raw_data_id": raw_id,
                    "entity_type": ent["type"],
                    "entity_value": ent["value"],
                    "extraction_method": "mock",
                    "context": item["content_raw"][:200],
                })

            inserted += 1
        except Exception as exc:
            print(f"  [WARN] Failed to insert item: {exc}")

    return inserted


def inject_to_neo4j(items: list[dict]) -> int:
    """Sync intel items and entities to Neo4j knowledge graph.

    Uses refined schema: Account, Tool, Contact, Link nodes with
    MENTIONS, PROMOTES, USES_CONTACT relationships.
    """
    from storage.neo4j_store import neo4j

    count = 0
    try:
        with neo4j.driver.session() as sess:
            for item in items:
                content = item["content_raw"]
                platform = item["source_platform"]
                item_id = f"mock_{item['collected_at'].strftime('%Y%m%d%H%M%S')}_{count}"

                # Create Intel node
                sess.run(
                    """
                    MERGE (i:Intel {raw_id: $rid})
                    SET i.text = $text, i.platform = $plat, i.priority = $pri
                    """,
                    rid=item_id, text=content[:200], plat=platform,
                    pri=item["priority"],
                )

                # Create entity nodes with refined types + relationships
                for ent in item.get("entities", []):
                    etype = ent["type"]
                    evalue = ent["value"]
                    eid = f"{etype}:{evalue}"

                    # Map entity type to refined node label
                    label_map = {
                        "wechat": "Account",
                        "qq": "Account",
                        "phone": "Contact",
                        "url": "Link",
                        "ip": "Link",
                        "email": "Contact",
                        "tool": "Tool",
                        "slang": "Contact",
                    }
                    node_label = label_map.get(etype, "Contact")

                    # Map entity type to refined relationship
                    rel_map = {
                        "wechat": "MENTIONS",
                        "qq": "MENTIONS",
                        "phone": "MENTIONS",
                        "url": "PROMOTES",
                        "tool": "PROMOTES",
                    }
                    rel_type = rel_map.get(etype, "MENTIONS")

                    # Create entity node with specific label
                    sess.run(
                        f"""
                        MERGE (e:{node_label} {{value: $val}})
                        SET e.type = $etype, e.uuid = $eid
                        """,
                        val=evalue, etype=etype, eid=eid,
                    )

                    # Create relationship between Intel and Entity
                    sess.run(
                        f"""
                        MATCH (i:Intel {{raw_id: $rid}})
                        MATCH (e:{node_label} {{value: $val}})
                        MERGE (i)-[:{rel_type}]->(e)
                        """,
                        rid=item_id, val=evalue,
                    )

                    # For Contact entities shared across Accounts, create USES_CONTACT
                    if node_label == "Contact":
                        sess.run(
                            f"""
                            MATCH (e:Contact {{value: $val}})
                            MATCH (a:Account)
                            WHERE a.value IN $accounts
                            MERGE (a)-[:USES_CONTACT]->(e)
                            """,
                            val=evalue,
                            accounts=[e["value"] for e in item.get("entities", [])
                                      if e["type"] in ("wechat", "qq")],
                        )

                count += 1

        # Create gang-detection co-occurrence edges
        with neo4j.driver.session() as sess:
            sess.run("""
                MATCH (c:Contact)
                MATCH (a1:Account)-[:USES_CONTACT]->(c)<-[:USES_CONTACT]-(a2:Account)
                WHERE a1.value < a2.value
                MERGE (a1)-[:CO_OCCURS]-(a2)
            """)

    except Exception as exc:
        print(f"  [WARN] Neo4j injection error: {exc}")

    return count


# ── CLI ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Generate mock black-market intel for demo purposes"
    )
    parser.add_argument("-n", "--count", type=int, default=50,
                        help="Number of intel items to generate")
    parser.add_argument("--seed", type=int, default=42,
                        help="Random seed for reproducibility")
    parser.add_argument("--no-neo4j", action="store_true",
                        help="Skip Neo4j injection")
    parser.add_argument("--dry-run", action="store_true",
                        help="Generate items but don't inject into databases")
    args = parser.parse_args()

    print(f"Generating {args.count} mock intel items (seed={args.seed})...")
    items = generate_items(args.count, args.seed)
    print(f"  Generated {len(items)} items")

    # Distribution summary
    labels = {}
    for item in items:
        lbl = item["intent_label"]
        labels[lbl] = labels.get(lbl, 0) + 1
    print("  Distribution:")
    for lbl, cnt in sorted(labels.items(), key=lambda x: -x[1]):
        print(f"    {lbl}: {cnt}")

    total_entities = sum(len(item.get("entities", [])) for item in items)
    print(f"  Total entities: {total_entities}")

    if args.dry_run:
        print("\n[Dry run — no data injected]")
        print("Sample items:")
        for item in items[:3]:
            print(f"  [{item['intent_label']}] {item['content_raw'][:80]}...")
        return

    print("\nInjecting into MySQL...")
    mysql_count = inject_to_mysql(items)
    print(f"  MySQL: {mysql_count} items inserted")

    if not args.no_neo4j:
        print("Injecting into Neo4j...")
        neo4j_count = inject_to_neo4j(items)
        print(f"  Neo4j: {neo4j_count} items synced")

    print(f"\nDone. Run 'python main.py ui' and check the dashboard.")


if __name__ == "__main__":
    main()
