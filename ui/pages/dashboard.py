"""Dashboard page — KPI cards, risk distribution, recent activity."""

import streamlit as st
import pandas as pd

from ui.theme import empty_state, priority_badge


def _mysql():
    from storage.mysql_store import mysql as m
    return m


def _fetch_stats():
    """Fetch dashboard stats from MySQL."""
    mysql = _mysql()
    try:
        return mysql.daily_stats()
    except Exception:
        return None


def show():
    st.markdown("## 情报仪表盘")
    st.caption("实时监控黑灰产情报采集与分析状态")

    stats = _fetch_stats()

    # ---- KPI Row ----
    col1, col2, col3, col4 = st.columns(4)
    with col1:
        st.metric("今日采集", stats.get("today_count", 0) if stats else 0, delta=None)
    with col2:
        st.metric("待分析", stats.get("pending_count", 0) if stats else 0, delta=None)
    with col3:
        st.metric("高危情报", stats.get("high_risk_count", 0) if stats else 0, delta=None)
    with col4:
        st.metric("累计实体", stats.get("entity_count", 0) if stats else 0, delta=None)

    st.divider()

    # ---- Risk Distribution + Recent Intel ----
    left, right = st.columns([1, 1])

    with left:
        st.markdown("#### 风险类型分布")
        if stats and stats.get("label_distribution"):
            df = pd.DataFrame(
                stats["label_distribution"].items(),
                columns=["类别", "数量"],
            ).sort_values("数量", ascending=False)
            st.bar_chart(df.set_index("类别"), use_container_width=True)
        else:
            st.markdown(
                empty_state("📊", "暂无分类数据", "采集并分析情报后将自动展示风险类型分布"),
                unsafe_allow_html=True,
            )

    with right:
        st.markdown("#### 最近情报")
        if stats and stats.get("recent_items"):
            for item in stats["recent_items"]:
                priority_html = priority_badge(item.get("priority", "normal"))
                st.markdown(
                    f"""<div style="background:#FDFBF9;border:1px solid #D8D3CB;
                    border-radius:8px;padding:0.8rem;margin-bottom:0.5rem">
                    <div style="display:flex;justify-content:space-between;align-items:center">
                    <span style="font-size:0.85rem;color:#3D3929">
                    {item.get('content', '')[:60]}{'...' if len(item.get('content', '')) > 60 else ''}
                    </span>{priority_html}</div>
                    <div style="font-size:0.7rem;color:#8E8A83;margin-top:0.3rem">
                    {item.get('source_platform','')} · {item.get('collected_at','')}
                    </div></div>""",
                    unsafe_allow_html=True,
                )
        else:
            st.markdown(
                empty_state("📋", "暂无情报数据", "运行采集器后将在此展示最新情报"),
                unsafe_allow_html=True,
            )

    st.divider()

    # ---- System Status ----
    st.markdown("#### 系统状态")
    s1, s2, s3 = st.columns(3)
    with s1:
        st.markdown(
            """<div style="background:#FDFBF9;border:1px solid #D8D3CB;border-radius:8px;
            padding:1rem;display:flex;align-items:center;gap:0.8rem">
            <div style="width:10px;height:10px;border-radius:50%;background:#8B9D83"></div>
            <div><div style="font-weight:500;color:#3D3929">MySQL</div>
            <div style="font-size:0.75rem;color:#8E8A83">运行中 · localhost:3306</div></div></div>""",
            unsafe_allow_html=True,
        )
    with s2:
        st.markdown(
            """<div style="background:#FDFBF9;border:1px solid #D8D3CB;border-radius:8px;
            padding:1rem;display:flex;align-items:center;gap:0.8rem">
            <div style="width:10px;height:10px;border-radius:50%;background:#8B9D83"></div>
            <div><div style="font-weight:500;color:#3D3929">Neo4j</div>
            <div style="font-size:0.75rem;color:#8E8A83">运行中 · localhost:7687</div></div></div>""",
            unsafe_allow_html=True,
        )
    with s3:
        st.markdown(
            """<div style="background:#FDFBF9;border:1px solid #D8D3CB;border-radius:8px;
            padding:1rem;display:flex;align-items:center;gap:0.8rem">
            <div style="width:10px;height:10px;border-radius:50%;background:#8B9D83"></div>
            <div><div style="font-weight:500;color:#3D3929">Milvus</div>
            <div style="font-size:0.75rem;color:#8E8A83">运行中 · localhost:19530</div></div></div>""",
            unsafe_allow_html=True,
        )
