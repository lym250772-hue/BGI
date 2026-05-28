"""Dashboard — asymmetric editorial layout: dossier-style KPIs, risk chart, recent intel."""

import streamlit as st
import pandas as pd

import ui.theme as T


def _check_db():
    status = {"MySQL": False, "Neo4j": False, "Milvus": False}
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
    return status


def _fetch():
    try:
        from storage.mysql_store import mysql
        return mysql.daily_stats()
    except Exception:
        return {}


def show():
    s = _fetch()
    svc = _check_db()

    # ── Header with dossier-style date line ──
    st.markdown("## 情报仪表盘")
    st.caption("黑灰产情报采集与分析实时概览")

    # ── Asymmetric KPI row: primary metric larger, three secondary ──
    # Layout: [hero metric 2x] [secondary metrics 1x] [secondary metrics 1x]
    left, mid, right = st.columns([2, 1, 1])

    with left:
        # Hero metric — "high risk" is the most important signal
        high_risk = s.get("high_risk_count", 0)
        st.metric("⚠️ 高危情报", high_risk)

    with mid:
        st.metric("今日采集", s.get("today_count", 0))
        st.metric("待分析", s.get("pending_count", 0))

    with right:
        st.metric("累计实体", s.get("entity_count", 0))

    st.divider()

    # ── Content area: distribution (wider) + recent (narrower) ──
    a, b = st.columns([1.4, 1])

    with a:
        st.markdown("#### 风险类型分布")
        dist = s.get("label_distribution", {})
        if dist:
            df = pd.DataFrame(dist.items(), columns=["类型", "数量"]).sort_values("数量", ascending=False)
            st.bar_chart(df.set_index("类型"), width="stretch")
        else:
            st.markdown(T.empty("📊", "暂无分类数据", "采集并分析情报后自动展示"), unsafe_allow_html=True)

    with b:
        st.markdown("#### 最近情报")
        recent = s.get("recent_items", [])
        if recent:
            for r in recent:
                txt = (r.get("content") or r.get("content_raw", ""))[:56]
                p = r.get("priority", "normal")
                plat = r.get("source_platform", "")
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

    # ── System status — compact row ──
    st.markdown("#### 系统状态")

    svc_info = [
        ("MySQL",   "业务数据存储",     "localhost:3306"),
        ("Neo4j",   "知识图谱引擎",     "localhost:7687"),
        ("Milvus",  "向量检索引擎",     "localhost:19530"),
    ]

    cols = st.columns(3)
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
