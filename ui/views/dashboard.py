"""Dashboard — asymmetric editorial layout: dossier-style KPIs, risk chart, recent intel."""

import streamlit as st
import pandas as pd

import ui.theme as T


def _check_db():
    status = {"MySQL": False, "Neo4j": False, "Milvus": False, "Doris": False}
    try:
        from storage.mysql_store import mysql
        with mysql.cursor() as c:
            c.execute("SELECT 1")
        status["MySQL"] = True
    except Exception:
        pass
    try:
        from storage.neo4j_store import neo4j
        with neo4j.driver.session() as s:
            s.run("RETURN 1")
        status["Neo4j"] = True
    except Exception:
        pass
    try:
        from storage.milvus_store import milvus
        from pymilvus import utility
        utility.has_collection("slang_embeddings")
        status["Milvus"] = True
    except Exception:
        pass
    try:
        from storage.doris_store import doris
        with doris.cursor() as c:
            c.execute("SELECT 1")
        status["Doris"] = True
    except Exception:
        pass
    return status


def _fetch():
    """Fetch dashboard stats. Primary: Doris OLAP, fallback: MySQL."""
    # Try Doris first for analytical queries
    try:
        from storage.doris_store import doris
        doris_stats = doris.dashboard_stats()
        # Include MySQL data for pending count (not in Doris)
        from storage.mysql_store import mysql
        with mysql.cursor() as c:
            c.execute("SELECT COUNT(*) as cnt FROM ods_raw_intel WHERE raw_status IN ('RAW_COLLECTED','CLEANED')")
            pending = c.fetchone()["cnt"]
        doris_stats["pending_count"] = pending
        # Enrich recent items with content from MySQL
        recent_ids = [ri["raw_id"] for ri in doris_stats.get("recent_items", [])]
        if recent_ids:
            from storage.mysql_store import mysql
            with mysql.cursor() as c:
                format_strings = ",".join(["%s"] * len(recent_ids))
                c.execute(
                    f"SELECT id, content_raw, source_platform, collect_time FROM ods_raw_intel WHERE id IN ({format_strings})",
                    recent_ids,
                )
                mysql_recent = {r["id"]: r for r in c.fetchall()}
            for ri in doris_stats["recent_items"]:
                mr = mysql_recent.get(ri["raw_id"], {})
                ri["content"] = mr.get("content_raw", "")
                ri["source_platform"] = mr.get("source_platform", ri.get("platform", ""))
                ri["collected_at"] = mr.get("collect_time", "") or str(ri.get("collect_time", ""))
        return doris_stats
    except Exception:
        pass

    # Fallback to MySQL
    try:
        from storage.mysql_store import mysql
        return mysql.daily_stats()
    except Exception:
        return {}

def _fetch_trend():
    """Daily trend from Doris."""
    try:
        from storage.doris_store import doris
        return doris.daily_trend(days=7)
    except Exception:
        return []


def show():
    s = _fetch()
    svc = _check_db()

    # ── Header ──
    st.markdown("## 情报仪表盘")
    st.caption("黑灰产情报采集与分析实时概览")

    # ── KPI row ──
    left, mid, right = st.columns([2, 1, 1])

    with left:
        high_risk = s.get("high_risk_count", 0)
        st.metric("⚠️ 高危情报", high_risk)

    with mid:
        st.metric("今日采集", s.get("today_count", 0))
        st.metric("待分析", s.get("pending_count", 0))

    with right:
        st.metric("累计实体", s.get("entity_count", 0))

    st.divider()

    # ── Content: distribution chart + trend + recent ──
    a, b = st.columns([1.4, 1])

    with a:
        st.markdown("#### 风险类型分布")
        dist = s.get("label_distribution", {})
        if dist:
            df = pd.DataFrame(dist.items(), columns=["类型", "数量"]).sort_values("数量", ascending=False)
            st.bar_chart(df.set_index("类型"), width="stretch")
        else:
            st.markdown(T.empty("📊", "暂无分类数据", "采集并分析情报后自动展示"), unsafe_allow_html=True)

        # ── Daily trend (Doris) ──
        trend = _fetch_trend()
        if trend:
            st.markdown("#### 近7日趋势")
            trend_df = pd.DataFrame(trend)
            trend_df["dt"] = pd.to_datetime(trend_df["dt"])
            trend_df = trend_df.set_index("dt")
            st.bar_chart(trend_df[["cnt", "high_cnt"]], width="stretch")

    with b:
        st.markdown("#### 最近情报")
        recent = s.get("recent_items", [])
        if recent:
            for r in recent:
                txt = (r.get("content") or r.get("content_raw", ""))[:56]
                p = r.get("risk_level", "normal")
                plat = r.get("source_platform", r.get("platform", ""))
                when = str(r.get("collected_at", ""))[:19]
                st.markdown(
                    f"""<div class="dossier-card" style="padding:0.65rem 0.8rem;margin-bottom:0.4rem">
                    <div style="display:flex;justify-content:space-between;align-items:center">
                    <span style="font-size:0.84rem;color:{T.TEXT_MAIN}">{txt}{'...' if len(txt) >= 56 else ''}</span>
                    {T.badge(p)}</div>
                    <div style="font-size:0.68rem;color:{T.TEXT_MUTED};margin-top:0.25rem">{plat} · {when}</div></div>""",
                    unsafe_allow_html=True,
                )
        else:
            st.markdown(T.empty("📋", "暂无情报", "运行 python main.py collect 采集数据"), unsafe_allow_html=True)

    st.divider()

    # ── System status ──
    st.markdown("#### 系统状态")

    svc_info = [
        ("MySQL",   "业务数据存储",     "localhost:3306"),
        ("Neo4j",   "知识图谱引擎",     "localhost:7687"),
        ("Milvus",  "向量检索引擎",     "localhost:19530"),
        ("Doris",   "OLAP分析引擎",     "localhost:9030"),
    ]

    cols = st.columns(4)
    for col, (name, desc, host) in zip(cols, svc_info):
        up = svc.get(name, False)
        dot = T.SAGE if up else T.ROSE
        label = "运行中" if up else "未连接"
        with col:
            st.markdown(
                f"""<div style="display:flex;align-items:center;gap:0.6rem;
                padding:0.5rem 0.8rem;font-size:0.82rem">
                <span style="width:6px;height:6px;border-radius:50%;background:{dot};display:inline-block;flex-shrink:0"></span>
                <span style="font-weight:500;color:{T.TEXT_MAIN}">{name}</span>
                <span style="color:{dot};font-size:0.72rem;font-weight:500">{label}</span>
                <span style="color:{T.TEXT_MUTED};font-size:0.7rem;margin-left:auto">{host}</span>
                </div>""",
                unsafe_allow_html=True,
            )
