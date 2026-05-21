"""Dashboard — KPI cards, risk distribution, recent activity, system status."""

import streamlit as st
import pandas as pd

import ui.theme as T


def _fetch():
    try:
        from storage.mysql_store import mysql
        return mysql.daily_stats()
    except Exception:
        return {}


def show():
    st.markdown("## 情报仪表盘")
    st.caption("黑灰产情报采集与分析实时概览")

    s = _fetch()

    # ---- KPI row ----
    k1, k2, k3, k4 = st.columns(4)
    with k1:
        st.metric("今日采集", s.get("today_count", 0))
    with k2:
        st.metric("待分析", s.get("pending_count", 0))
    with k3:
        st.metric("高危情报", s.get("high_risk_count", 0))
    with k4:
        st.metric("累计实体", s.get("entity_count", 0))

    st.divider()

    # ---- Distribution + Recent ----
    a, b = st.columns([1, 1])

    with a:
        st.markdown("#### 风险类型分布")
        dist = s.get("label_distribution", {})
        if dist:
            df = pd.DataFrame(dist.items(), columns=["类型", "数量"]).sort_values("数量", ascending=False)
            st.bar_chart(df.set_index("类型"), use_container_width=True)
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
                    f"""<div style="background:{T.BG_CARD};border:1px solid {T.BORDER};
                    border-radius:8px;padding:0.65rem 0.8rem;margin-bottom:0.4rem">
                    <div style="display:flex;justify-content:space-between;align-items:center">
                    <span style="font-size:0.84rem;color:{T.TEXT_MAIN}">{txt}{'...' if len(txt) >= 56 else ''}</span>
                    {T.badge(p)}</div>
                    <div style="font-size:0.68rem;color:{T.TEXT_MUTED};margin-top:0.25rem">{plat} · {when}</div></div>""",
                    unsafe_allow_html=True,
                )
        else:
            st.markdown(T.empty("📋", "暂无情报", "运行采集器后在此展示最新情报"), unsafe_allow_html=True)

    st.divider()

    # ---- System status ----
    st.markdown("#### 系统状态")
    c1, c2, c3 = st.columns(3)
    for col, name, host in [(c1, "MySQL", "localhost:3306"), (c2, "Neo4j", "localhost:7687"), (c3, "Milvus", "localhost:19530")]:
        with col:
            st.markdown(
                f"""<div style="background:{T.BG_CARD};border:1px solid {T.BORDER};border-radius:8px;
                padding:0.8rem 1rem;display:flex;align-items:center;gap:0.7rem">
                <div style="width:8px;height:8px;border-radius:50%;background:{T.SAGE}"></div>
                <div><div style="font-weight:500;color:{T.TEXT_MAIN};font-size:0.88rem">{name}</div>
                <div style="font-size:0.7rem;color:{T.TEXT_MUTED}">运行中 · {host}</div></div></div>""",
                unsafe_allow_html=True,
            )
