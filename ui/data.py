"""Data access helpers for the Streamlit analyst console."""

from __future__ import annotations

import re

import ui.labels as L


def _truncate(value: str | None, limit: int = 120) -> str:
    text = (value or "").replace("\n", " ").strip()
    return text if len(text) <= limit else text[:limit] + "..."


def service_status() -> list[dict]:
    """Live status for every backend component. No cache on purpose."""
    items = []

    try:
        from storage.mysql_store import mysql
        with mysql.cursor() as c:
            c.execute("SELECT COUNT(*) AS cnt FROM ods_raw_intel")
            cnt = c.fetchone()["cnt"]
        items.append({
            "name": "MySQL",
            "role": "控制面与业务数据",
            "endpoint": "localhost:3306",
            "ok": True,
            "detail": f"原始情报 {cnt} 条",
        })
    except Exception as exc:
        items.append({
            "name": "MySQL",
            "role": "控制面与业务数据",
            "endpoint": "localhost:3306",
            "ok": False,
            "detail": str(exc),
        })

    try:
        from storage.neo4j_store import neo4j
        with neo4j.driver.session() as s:
            row = s.run("MATCH (n) RETURN count(n) AS cnt").single()
            cnt = row["cnt"] if row else 0
        items.append({
            "name": "Neo4j",
            "role": "关系扩线与图谱",
            "endpoint": "localhost:7687",
            "ok": True,
            "detail": f"图节点 {cnt} 个",
        })
    except Exception as exc:
        items.append({
            "name": "Neo4j",
            "role": "关系扩线与图谱",
            "endpoint": "localhost:7687",
            "ok": False,
            "detail": str(exc),
        })

    try:
        from storage.milvus_store import milvus
        ok = milvus.healthcheck()
        detail = "集合已就绪"
        if ok:
            detail = "slang_embeddings / intel_embeddings 已就绪"
        items.append({
            "name": "Milvus",
            "role": "黑话相似检索",
            "endpoint": "localhost:19530",
            "ok": ok,
            "detail": detail if ok else "集合缺失或服务不可达",
        })
    except Exception as exc:
        items.append({
            "name": "Milvus",
            "role": "黑话相似检索",
            "endpoint": "localhost:19530",
            "ok": False,
            "detail": str(exc),
        })

    try:
        from storage.doris_store import doris
        ok = doris.healthcheck()
        detail = "已禁用或不可达"
        if ok:
            with doris.cursor() as c:
                c.execute("SELECT COUNT(*) AS cnt FROM bagi_olap.intel_analysis_wide")
                detail = f"宽表 {c.fetchone()['cnt']} 条"
        items.append({
            "name": "Doris",
            "role": "OLAP 聚合分析",
            "endpoint": "localhost:9030",
            "ok": ok,
            "detail": detail,
        })
    except Exception as exc:
        items.append({
            "name": "Doris",
            "role": "OLAP 聚合分析",
            "endpoint": "localhost:9030",
            "ok": False,
            "detail": str(exc),
        })

    return items


def overview_stats() -> dict:
    try:
        from storage.mysql_store import mysql
        with mysql.cursor() as c:
            c.execute("SELECT raw_status, COUNT(*) AS cnt FROM ods_raw_intel GROUP BY raw_status")
            status_counts = {r["raw_status"] or "UNKNOWN": r["cnt"] for r in c.fetchall()}
            c.execute(
                """SELECT COUNT(*) AS cnt
                   FROM dwd_intel_analysis
                   WHERE is_latest=1 AND risk_level IN ('high','critical')"""
            )
            high = c.fetchone()["cnt"]
            c.execute("SELECT COUNT(*) AS cnt FROM dwd_entity")
            entities = c.fetchone()["cnt"]
            c.execute("SELECT COUNT(*) AS cnt FROM dim_slang_dict WHERE status='candidate'")
            candidates = c.fetchone()["cnt"]
            c.execute("SELECT COUNT(*) AS cnt FROM analysis_job WHERE status IN ('pending','running')")
            active_jobs = c.fetchone()["cnt"]
            c.execute(
                """SELECT COUNT(*) AS cnt
                   FROM dwd_intel_analysis
                   WHERE is_latest=1
                     AND DATE(DATE_ADD(created_at, INTERVAL 8 HOUR)) =
                         DATE(DATE_ADD(NOW(), INTERVAL 8 HOUR))"""
            )
            today_analyzed = c.fetchone()["cnt"]
            c.execute(
                """SELECT COUNT(*) AS cnt
                   FROM ods_raw_intel
                   WHERE DATE(DATE_ADD(collect_time, INTERVAL 8 HOUR)) =
                         DATE(DATE_ADD(NOW(), INTERVAL 8 HOUR))"""
            )
            today_received = c.fetchone()["cnt"]
        return {
            "status_counts": status_counts,
            "total_raw": sum(status_counts.values()),
            "pending": status_counts.get("RAW_COLLECTED", 0) + status_counts.get("CLEANED", 0),
            "running": status_counts.get("ANALYZING", 0),
            "screened": status_counts.get("SCREENED", 0),
            "analyzed": status_counts.get("ANALYZED", 0),
            "failed": status_counts.get("FAILED", 0),
            "today_analyzed": today_analyzed,
            "today_received": today_received,
            "high_risk": high,
            "entities": entities,
            "slang_candidates": candidates,
            "active_jobs": active_jobs,
        }
    except Exception:
        return {
            "status_counts": {},
            "total_raw": 0,
            "pending": 0,
            "running": 0,
            "screened": 0,
            "analyzed": 0,
            "failed": 0,
            "today_analyzed": 0,
            "today_received": 0,
            "high_risk": 0,
            "entities": 0,
            "slang_candidates": 0,
            "active_jobs": 0,
        }


def risk_distribution() -> list[dict]:
    try:
        from storage.mysql_store import mysql
        with mysql.cursor() as c:
            c.execute(
                """SELECT COALESCE(risk_label, '未分类') AS risk_label, COUNT(*) AS cnt
                   FROM dwd_intel_analysis
                   WHERE is_latest=1
                   GROUP BY risk_label
                   ORDER BY cnt DESC"""
            )
            return [dict(r) for r in c.fetchall()]
    except Exception:
        return []


def platform_distribution() -> list[dict]:
    try:
        from storage.mysql_store import mysql
        with mysql.cursor() as c:
            c.execute(
                """SELECT source_platform AS platform, COUNT(*) AS cnt
                   FROM ods_raw_intel
                   GROUP BY source_platform
                   ORDER BY cnt DESC"""
            )
            return [dict(r) for r in c.fetchall()]
    except Exception:
        return []


def daily_trend(days: int = 7) -> list[dict]:
    try:
        from storage.mysql_store import mysql
        with mysql.cursor() as c:
            c.execute(
                """SELECT DATE(DATE_ADD(created_at, INTERVAL 8 HOUR)) AS dt,
                          COUNT(*) AS cnt,
                          SUM(CASE WHEN risk_level IN ('high','critical') THEN 1 ELSE 0 END) AS high_cnt
                   FROM dwd_intel_analysis
                   WHERE is_latest=1
                     AND DATE(DATE_ADD(created_at, INTERVAL 8 HOUR)) >=
                         DATE_SUB(DATE(DATE_ADD(NOW(), INTERVAL 8 HOUR)), INTERVAL %s DAY)
                   GROUP BY DATE(DATE_ADD(created_at, INTERVAL 8 HOUR))
                   ORDER BY dt""",
                (days))
            return [dict(r) for r in c.fetchall()]
    except Exception:
        return []


# ---------------------------------------------------------------------------
# Lightweight ChatBI: whitelist natural-language questions -> safe SQL queries
# ---------------------------------------------------------------------------

_PLATFORM_ALIASES = {
    "tieba": ["tieba", "贴吧"],
    "weibo": ["weibo", "微博"],
    "zhihu": ["zhihu", "知乎"],
    "douyin": ["douyin", "抖音"],
    "xiaohongshu": ["xiaohongshu", "小红书"],
    "xianyu": ["xianyu", "闲鱼"],
    "qq_group": ["qq", "qq群", "QQ群"],
}


def _detect_platform(question: str) -> str | None:
    q = question.lower()
    for platform, aliases in _PLATFORM_ALIASES.items():
        if any(alias.lower() in q for alias in aliases):
            return platform
    return None


def _detect_days(question: str) -> int | None:
    q = question.lower()
    match = re.search(r"(?:最近|近|过去)?\s*(\d{1,3})\s*[天日]", q)
    if match:
        return max(1, min(int(match.group(1)), 365))
    if "上周" in q or "最近一周" in q or "近一周" in q:
        return 7
    if "本月" in q or "最近一月" in q or "近一月" in q:
        return 30
    return None


def _doris_ready() -> bool:
    try:
        from storage.doris_store import doris
        return doris.healthcheck()
    except Exception:
        return False


def _where_parts(platform: str | None, days: int | None, field_platform: str = "platform",
                 field_time: str = "collect_time") -> tuple[str, list]:
    parts = []
    params = []
    if platform:
        parts.append(f"{field_platform}=%s")
        params.append(platform)
    if days:
        parts.append(f"{field_time} >= DATE_SUB(CURDATE(), INTERVAL %s DAY)")
        params.append(days)
    clause = "WHERE " + " AND ".join(parts) if parts else ""
    return clause, params


def _chatbi_risk_distribution(platform: str | None, days: int | None) -> dict:
    if _doris_ready():
        from config.settings import settings
        from storage.doris_store import doris
        clause, params = _where_parts(platform, days)
        with doris.cursor() as c:
            c.execute(
                f"""SELECT COALESCE(risk_label, '未分类') AS risk_label,
                           COUNT(*) AS cnt,
                           ROUND(AVG(risk_score), 4) AS avg_score,
                           SUM(CASE WHEN risk_level IN ('high','critical') THEN 1 ELSE 0 END) AS high_cnt
                    FROM {settings.doris_database}.intel_analysis_wide
                    {clause}
                    GROUP BY risk_label
                    ORDER BY cnt DESC
                    LIMIT 12""",
                params)
            rows = [dict(r) for r in c.fetchall()]
        source = "Doris"
    else:
        from storage.mysql_store import mysql
        clause, params = _where_parts(platform, days, field_platform="o.source_platform", field_time="o.collect_time")
        with mysql.cursor() as c:
            c.execute(
                f"""SELECT COALESCE(a.risk_label, '未分类') AS risk_label,
                           COUNT(*) AS cnt,
                           ROUND(AVG(a.risk_score), 4) AS avg_score,
                           SUM(CASE WHEN a.risk_level IN ('high','critical') THEN 1 ELSE 0 END) AS high_cnt
                    FROM ods_raw_intel o
                    LEFT JOIN dwd_intel_analysis a ON a.raw_id=o.id AND a.is_latest=1
                    {clause}
                    GROUP BY a.risk_label
                    ORDER BY cnt DESC
                    LIMIT 12""",
                params)
            rows = [dict(r) for r in c.fetchall()]
        source = "MySQL"

    if rows:
        top = rows[0]
        scope = f"{platform} 平台" if platform else "全部平台"
        window = f"最近 {days} 天" if days else "全量数据"
        answer = (
            f"{window}、{scope}中，最活跃的风险类型是「{top['risk_label']}」，"
            f"共 {top['cnt']} 条；其中高危/严重样本 {top.get('high_cnt') or 0} 条。"
        )
    else:
        answer = "没有查到符合条件的风险分类数据。"

    return {
        "intent": "风险类型分布",
        "source": source,
        "answer": answer,
        "rows": rows,
        "chart": "bar",
        "x": "risk_label",
        "y": "cnt",
    }


def _chatbi_platform_distribution(days: int | None, focus_high: bool = False) -> dict:
    order_expr = "high_cnt DESC, cnt DESC" if focus_high else "cnt DESC"
    if _doris_ready():
        from config.settings import settings
        from storage.doris_store import doris
        clause, params = _where_parts(None, days)
        with doris.cursor() as c:
            c.execute(
                f"""SELECT COALESCE(platform, 'unknown') AS platform,
                           COUNT(*) AS cnt,
                           ROUND(AVG(risk_score), 4) AS avg_score,
                           SUM(CASE WHEN risk_level IN ('high','critical') THEN 1 ELSE 0 END) AS high_cnt
                    FROM {settings.doris_database}.intel_analysis_wide
                    {clause}
                    GROUP BY platform
                    ORDER BY {order_expr}
                    LIMIT 12""",
                params)
            rows = [dict(r) for r in c.fetchall()]
        source = "Doris"
    else:
        from storage.mysql_store import mysql
        clause, params = _where_parts(None, days, field_platform="o.source_platform", field_time="o.collect_time")
        with mysql.cursor() as c:
            c.execute(
                f"""SELECT COALESCE(o.source_platform, 'unknown') AS platform,
                           COUNT(*) AS cnt,
                           ROUND(AVG(a.risk_score), 4) AS avg_score,
                           SUM(CASE WHEN a.risk_level IN ('high','critical') THEN 1 ELSE 0 END) AS high_cnt
                    FROM ods_raw_intel o
                    LEFT JOIN dwd_intel_analysis a ON a.raw_id=o.id AND a.is_latest=1
                    {clause}
                    GROUP BY o.source_platform
                    ORDER BY {order_expr}
                    LIMIT 12""",
                params)
            rows = [dict(r) for r in c.fetchall()]
        source = "MySQL"

    answer = "没有查到平台分布数据。"
    if rows:
        top = rows[0]
        window = f"最近 {days} 天" if days else "全量数据"
        if focus_high:
            answer = (
                f"{window}中，高危/严重情报最多的平台是「{top['platform']}」，"
                f"高危/严重样本 {top.get('high_cnt') or 0} 条，总情报 {top['cnt']} 条。"
            )
        else:
            answer = (
                f"{window}中，情报量最高的平台是「{top['platform']}」，共 {top['cnt']} 条；"
                f"高危/严重样本 {top.get('high_cnt') or 0} 条，平均风险分 {float(top.get('avg_score') or 0):.2f}。"
            )
    return {
        "intent": "来源平台态势",
        "source": source,
        "answer": answer,
        "rows": rows,
        "chart": "bar",
        "x": "platform",
        "y": "cnt",
    }


def _chatbi_high_risk(platform: str | None, days: int | None) -> dict:
    if _doris_ready():
        from config.settings import settings
        from storage.doris_store import doris
        clause, params = _where_parts(platform, days)
        with doris.cursor() as c:
            c.execute(
                f"""SELECT raw_id, platform, risk_label, risk_sub_label, risk_level,
                           risk_score, content_snippet
                    FROM {settings.doris_database}.intel_analysis_wide
                    {clause}
                    ORDER BY CASE risk_level WHEN 'critical' THEN 4 WHEN 'high' THEN 3 ELSE 1 END DESC,
                             risk_score DESC, raw_id DESC
                    LIMIT 10""",
                params)
            rows = [dict(r) for r in c.fetchall()]
        source = "Doris"
    else:
        from storage.mysql_store import mysql
        clause, params = _where_parts(platform, days, field_platform="o.source_platform", field_time="o.collect_time")
        with mysql.cursor() as c:
            c.execute(
                f"""SELECT o.id AS raw_id, o.source_platform AS platform,
                           a.risk_label, a.risk_sub_label, a.risk_level,
                           a.risk_score, LEFT(o.content_raw, 180) AS content_snippet
                    FROM ods_raw_intel o
                    JOIN dwd_intel_analysis a ON a.raw_id=o.id AND a.is_latest=1
                    {clause}
                    ORDER BY CASE a.risk_level WHEN 'critical' THEN 4 WHEN 'high' THEN 3 ELSE 1 END DESC,
                             a.risk_score DESC, o.id DESC
                    LIMIT 10""",
                params)
            rows = [dict(r) for r in c.fetchall()]
        source = "MySQL"
    answer = "没有查到高危样本。"
    if rows:
        answer = f"已筛出 {len(rows)} 条高风险典型样本，优先查看风险分最高和证据最明确的情报。"
    return {
        "intent": "高危样本",
        "source": source,
        "answer": answer,
        "rows": rows,
        "chart": "table",
    }


def _chatbi_hot_slang(platform: str | None, days: int | None) -> dict:
    from storage.mysql_store import mysql
    clause, params = _where_parts(platform, days, field_platform="o.source_platform", field_time="o.collect_time")
    prefix = "WHERE e.entity_type='slang'"
    if clause:
        clause = prefix + " AND " + clause.removeprefix("WHERE ")
    else:
        clause = prefix
    with mysql.cursor() as c:
        c.execute(
            f"""SELECT e.entity_value AS slang,
                       COALESCE(MAX(e.normalized_value), '') AS normalized_value,
                       COUNT(*) AS cnt,
                       MIN(e.raw_id) AS example_raw_id
                FROM dwd_entity e
                JOIN ods_raw_intel o ON o.id=e.raw_id
                {clause}
                GROUP BY e.entity_value
                ORDER BY cnt DESC
                LIMIT 15""",
            params)
        rows = [dict(r) for r in c.fetchall()]
    answer = "没有查到黑话命中记录。"
    if rows:
        top = rows[0]
        answer = f"命中最多的黑话是「{top['slang']}」，出现 {top['cnt']} 次。"
    return {
        "intent": "热门黑话",
        "source": "MySQL",
        "answer": answer,
        "rows": rows,
        "chart": "bar",
        "x": "slang",
        "y": "cnt",
    }


def _chatbi_entity_distribution(platform: str | None, days: int | None) -> dict:
    from storage.mysql_store import mysql
    clause, params = _where_parts(platform, days, field_platform="o.source_platform", field_time="o.collect_time")
    if clause:
        clause = "WHERE " + clause.removeprefix("WHERE ")
    with mysql.cursor() as c:
        c.execute(
            f"""SELECT e.entity_type, COUNT(*) AS cnt,
                       COUNT(DISTINCT e.entity_value) AS unique_cnt
                FROM dwd_entity e
                JOIN ods_raw_intel o ON o.id=e.raw_id
                {clause}
                GROUP BY e.entity_type
                ORDER BY cnt DESC
                LIMIT 15""",
            params)
        rows = [dict(r) for r in c.fetchall()]
    answer = "没有查到实体线索数据。"
    if rows:
        top = rows[0]
        answer = f"抽取最多的实体类型是「{top['entity_type']}」，共 {top['cnt']} 次，去重后 {top['unique_cnt']} 个。"
    return {
        "intent": "实体线索分布",
        "source": "MySQL",
        "answer": answer,
        "rows": rows,
        "chart": "bar",
        "x": "entity_type",
        "y": "cnt",
    }


def _chatbi_queue_status() -> dict:
    stats = overview_stats()
    rows = [
        {"status": key, "cnt": value}
        for key, value in stats.get("status_counts", {}).items()
    ]
    answer = (
        f"当前接收总量 {stats['total_raw']} 条；待研判 {stats['pending']} 条，"
        f"研判中 {stats['running']} 条，已初筛 {stats.get('screened', 0)} 条，"
        f"已研判 {stats['analyzed']} 条，失败 {stats['failed']} 条。"
    )
    return {
        "intent": "处理队列状态",
        "source": "MySQL",
        "answer": answer,
        "rows": rows,
        "chart": "bar",
        "x": "status",
        "y": "cnt",
    }


def _chatbi_risk_slang_samples(platform: str | None, days: int | None) -> dict:
    risk = _chatbi_risk_distribution(platform, days)
    slang = _chatbi_hot_slang(platform, days)
    samples = _chatbi_high_risk(platform, days)
    fallback_note = ""
    if days and not (risk.get("rows") or slang.get("rows") or samples.get("rows")):
        risk = _chatbi_risk_distribution(platform, None)
        slang = _chatbi_hot_slang(platform, None)
        samples = _chatbi_high_risk(platform, None)
        fallback_note = f"最近 {days} 天没有命中数据，已自动回退到同范围的全量样本。"

    rows = []
    for row in (risk.get("rows") or [])[:5]:
        rows.append({
            "类型": "风险分类",
            "名称": row.get("risk_label"),
            "数量": row.get("cnt"),
            "补充": f"高危/严重 {row.get('high_cnt') or 0} 条",
        })
    for row in (slang.get("rows") or [])[:5]:
        rows.append({
            "类型": "黑话",
            "名称": row.get("slang"),
            "数量": row.get("cnt"),
            "补充": row.get("normalized_value") or "",
        })
    for row in (samples.get("rows") or [])[:3]:
        rows.append({
            "类型": "典型样本",
            "名称": f"#{row.get('raw_id')} {row.get('risk_label') or ''}",
            "数量": row.get("risk_score"),
            "补充": row.get("content_snippet") or "",
        })

    top_risk = (risk.get("rows") or [{}])[0].get("risk_label", "未分类")
    top_slang = (slang.get("rows") or [{}])[0].get("slang", "暂无黑话")
    scope = f"{platform} 平台" if platform else "全部平台"
    window = f"最近 {days} 天" if days and not fallback_note else "全量数据"
    answer = (
        f"{fallback_note}{window}、{scope}中，最活跃风险分类是「{top_risk}」；"
        f"主要命中的黑话是「{top_slang}」。下表同时列出风险分类、黑话和典型样本。"
    )
    return {
        "intent": "风险分类 + 黑话 + 典型样本",
        "source": f"{risk.get('source', 'Doris')} + MySQL",
        "answer": answer,
        "rows": rows,
        "chart": "table",
    }


def chatbi_answer(question: str) -> dict:
    """Answer a natural-language BI question using only whitelisted queries."""
    q = (question or "").strip()
    if not q:
        q = "当前风险类型分布"
    platform = _detect_platform(q)
    days = _detect_days(q)
    q_lower = q.lower()

    if any(k in q for k in ["帮助", "示例", "能问", "可以问"]):
        return {
            "intent": "帮助",
            "source": "规则",
            "answer": "你可以问：风险类型分布、哪个平台最多、高危样本、热门黑话、实体线索分布、待研判队列状态。",
            "rows": [
                {"示例问题": "上周贴吧哪个风险分类最活跃？"},
                {"示例问题": "哪个平台高危情报最多？"},
                {"示例问题": "最近 30 天热门黑话有哪些？"},
                {"示例问题": "给我 10 条高危典型样本。"},
                {"示例问题": "当前待研判队列还有多少？"}],
            "chart": "table",
        }

    if any(k in q for k in ["待研判", "队列", "进度", "处理状态", "失败"]):
        return _chatbi_queue_status()
    if "黑话" in q and any(k in q for k in ["风险", "分类", "活跃", "例句", "样本", "典型"]):
        return _chatbi_risk_slang_samples(platform, days)
    if any(k in q for k in ["黑话", "暗语", "术语"]):
        return _chatbi_hot_slang(platform, days)
    if any(k in q for k in ["实体", "线索", "账号", "联系方式", "链接"]):
        return _chatbi_entity_distribution(platform, days)
    if any(k in q for k in ["平台", "来源", "渠道"]):
        return _chatbi_platform_distribution(days, focus_high=any(k in q for k in ["高危", "严重"]))
    if any(k in q for k in ["高危", "严重", "典型", "样本", "例句", "案例", "top"]):
        return _chatbi_high_risk(platform, days)
    if any(k in q for k in ["风险", "分类", "类型", "活跃", "最多", "分布", "态势"]):
        return _chatbi_risk_distribution(platform, days)

    result = _chatbi_risk_distribution(platform, days)
    result["answer"] = "我没有识别到更具体的白名单问题，先按风险类型分布为你查询。 " + result["answer"]
    return result


def list_intel(
    status: str | None = None,
    keyword: str = "",
    limit: int = 200,
    order_by: str = "id_desc",
) -> list[dict]:
    where = []
    params = []
    if status:
        where.append("o.raw_status=%s")
        params.append(status)
    if keyword:
        where.append("(o.content_raw LIKE %s OR o.author_name LIKE %s OR o.source_channel LIKE %s)")
        like = f"%{keyword}%"
        params.extend([like, like, like])
    clause = "WHERE " + " AND ".join(where) if where else ""
    order_sql = "o.id DESC"
    if order_by == "recent_activity":
        order_sql = "COALESCE(a.created_at, o.collect_time) DESC, o.id DESC"
    params.append(limit)
    try:
        from storage.mysql_store import mysql
        with mysql.cursor() as c:
            c.execute(
                f"""
                SELECT o.id, o.source_platform, o.source_channel, o.author_name,
                       o.content_raw, o.raw_status, o.collect_time,
                       a.risk_label, a.risk_sub_label, a.risk_score, a.risk_level,
                       a.classification_method,
                       DATE_ADD(a.created_at, INTERVAL 8 HOUR) AS analyzed_at
                FROM ods_raw_intel o
                LEFT JOIN dwd_intel_analysis a ON a.raw_id=o.id AND a.is_latest=1
                {clause}
                ORDER BY {order_sql}
                LIMIT %s
                """,
                params)
            rows = [dict(r) for r in c.fetchall()]
        for row in rows:
            row["content_preview"] = _truncate(row.get("content_raw"), 150)
        return rows
    except Exception:
        return []


def get_raw(raw_id: int) -> dict | None:
    try:
        from storage.mysql_store import mysql
        return mysql.get_raw_by_id(raw_id)
    except Exception:
        return None


def get_analysis_bundle(raw_id: int) -> dict:
    try:
        from storage.mysql_store import mysql
        return mysql.get_analysis_bundle(raw_id)
    except Exception:
        return {"raw_id": raw_id, "entities": [], "evidence_spans": []}


def preferred_text(raw_id: int, fallback: str = "") -> str:
    try:
        from storage.mysql_store import mysql
        return mysql.get_preferred_analysis_text(raw_id, fallback=fallback)
    except Exception:
        return fallback


def submit_analysis_job(raw_id: int, text: str, platform: str, options: dict | None = None) -> str:
    from storage.mysql_store import mysql
    from analyzer.worker import submit_analysis

    job_id = mysql.create_job(raw_id, text, platform, options=options)
    # Mark synchronously so the item disappears from "submittable" queues
    # immediately, even before the background worker takes its first step.
    mysql.mark_raw_analyzing(raw_id)
    submit_analysis(job_id, raw_id, text, platform, options=options)
    return job_id


def submit_batch_jobs(rows: list[dict], options: dict | None = None, max_items: int = 20) -> list[str]:
    job_ids = []
    for row in rows[:max_items]:
        raw_id = int(row["id"])
        text = preferred_text(raw_id, fallback=row.get("content_raw", ""))
        job_ids.append(
            submit_analysis_job(
                raw_id=raw_id,
                text=text,
                platform=row.get("source_platform") or "unknown",
                options=options)
        )
    return job_ids


def list_jobs(limit: int = 20) -> list[dict]:
    try:
        from storage.mysql_store import mysql
        return mysql.list_jobs(limit=limit)
    except Exception:
        return []


def recover_unfinished_jobs(limit: int = 20) -> int:
    try:
        from analyzer.worker import recover_unfinished_jobs as recover
        return recover(limit=limit)
    except Exception:
        return 0


def has_active_jobs() -> bool:
    try:
        from storage.mysql_store import mysql
        with mysql.cursor() as c:
            c.execute(
                "SELECT COUNT(*) AS cnt FROM analysis_job WHERE status IN ('pending','running')"
            )
            return int(c.fetchone()["cnt"] or 0) > 0
    except Exception:
        return False


def list_entities(limit: int = 300, entity_type: str | None = None) -> list[dict]:
    where = []
    params = []
    if entity_type:
        where.append("entity_type=%s")
        params.append(entity_type)
    clause = "WHERE " + " AND ".join(where) if where else ""
    params.append(limit)
    try:
        from storage.mysql_store import mysql
        with mysql.cursor() as c:
            c.execute(
                f"""SELECT entity_type, entity_value, normalized_value, extract_method,
                           confidence, raw_id, first_seen
                    FROM dwd_entity
                    {clause}
                    ORDER BY first_seen DESC, id DESC
                    LIMIT %s""",
                params)
            return [dict(r) for r in c.fetchall()]
    except Exception:
        return []


def entity_type_counts() -> list[dict]:
    try:
        from storage.mysql_store import mysql
        with mysql.cursor() as c:
            c.execute(
                """SELECT entity_type, COUNT(*) AS cnt
                   FROM dwd_entity
                   GROUP BY entity_type
                   ORDER BY cnt DESC"""
            )
            return [dict(r) for r in c.fetchall()]
    except Exception:
        return []


def list_slang(status: str = "candidate", limit: int = 200) -> list[dict]:
    try:
        from storage.mysql_store import mysql
        with mysql.cursor() as c:
            c.execute(
                """SELECT * FROM dim_slang_dict
                   WHERE status=%s
                   ORDER BY updated_at DESC
                   LIMIT %s""",
                (status, limit))
            rows = [dict(r) for r in c.fetchall()]
        for row in rows:
            row.setdefault("suggested_meaning", row.get("normalized_meaning"))
            row.setdefault("evidence", row.get("candidate_evidence"))
            row.setdefault("reason", row.get("candidate_reason"))
        return rows
    except Exception:
        return []


def approve_slang(term: str, meaning: str, category: str = "", reviewer: str = "analyst") -> bool:
    from storage.mysql_store import mysql
    return mysql.approve_slang_candidate(term, meaning=meaning, category=category, reviewer=reviewer)


def reject_slang(term: str, reviewer: str = "analyst", reason: str = "") -> bool:
    from storage.mysql_store import mysql
    return mysql.reject_slang_candidate(term, reviewer=reviewer, reason=reason)


def graph_neighbors(entity_type: str, value: str, depth: int = 2) -> list[dict]:
    try:
        from storage.neo4j_store import neo4j
        rows = neo4j.find_entity_neighborhood(entity_type, value, depth=depth)
    except Exception:
        return []

    output = []
    seen = set()
    for row in rows:
        related = row.get("related")
        try:
            labels = list(related.labels)
            props = dict(related)
        except Exception:
            labels = []
            props = {}
        rels = row.get("rels") or []
        label_set = set(labels)
        rel_name = "-"
        if rels:
            try:
                rel_name = rels[-1].type
            except Exception:
                rel_name = "-"
        if "Intel" in label_set:
            continue

        raw_type = props.get("type") or (labels[0] if labels else "-")
        clue_type = L.entity_type_label(raw_type)
        clue_value = props.get("value") or props.get("uuid") or "-"
        unique_key = (",".join(labels), str(clue_type), str(clue_value), len(rels), rel_name)
        if unique_key in seen:
            continue
        seen.add(unique_key)
        output.append({
            "图谱标签": ",".join(labels) or "-",
            "关系类型": rel_name,
            "线索类型": clue_type,
            "线索值": clue_value,
            "关系跳数": len(rels),
        })
    return output
