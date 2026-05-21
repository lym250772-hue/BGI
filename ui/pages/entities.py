"""Entity library page — browse extracted entities by type."""

import streamlit as st
import pandas as pd

from ui.theme import empty_state


def _mysql():
    from storage.mysql_store import mysql as m
    return m


def show():
    st.markdown("## 实体库")
    st.caption("提取的情报实体：账号、链接、黑话、工具等")

    # ---- Fetch all entities ----
    try:
        mysql = _mysql()
        # Use raw query to get entities summary
        with mysql.cursor() as c:
            c.execute("""
                SELECT entity_type, COUNT(*) as cnt
                FROM entities
                GROUP BY entity_type
                ORDER BY cnt DESC
            """)
            type_stats = c.fetchall()

            c.execute("SELECT COUNT(*) as total FROM entities")
            total = c.fetchone()["total"]

            c.execute("""
                SELECT e.id, e.raw_data_id, e.entity_type, e.entity_value,
                       e.extraction_method, e.context, e.created_at
                FROM entities e
                ORDER BY e.id DESC
                LIMIT 200
            """)
            entities = c.fetchall()
    except Exception:
        type_stats = []
        total = 0
        entities = []

    # ---- Summary bar ----
    if type_stats:
        cols = st.columns(len(type_stats) + 1)
        with cols[0]:
            st.metric("总计", total)
        for i, row in enumerate(type_stats):
            with cols[i + 1]:
                st.metric(row["entity_type"], row["cnt"])
    else:
        st.metric("总计", 0)

    st.divider()

    # ---- Entity tabs ----
    if not entities:
        st.markdown(
            empty_state("🔗", "暂无实体数据", "分析情报后将自动提取实体"),
            unsafe_allow_html=True,
        )
        return

    tab_names = ["全部"] + sorted(list({e["entity_type"] for e in entities}))
    tabs = st.tabs(tab_names)

    for i, tab_name in enumerate(tab_names):
        with tabs[i]:
            if tab_name == "全部":
                filtered = entities
            else:
                filtered = [e for e in entities if e["entity_type"] == tab_name]

            if not filtered:
                st.caption("暂无此类实体")
                continue

            df = pd.DataFrame([
                {
                    "ID": e["id"],
                    "实体值": e["entity_value"],
                    "提取方式": e["extraction_method"],
                    "上下文": (e.get("context") or "")[:60],
                    "时间": str(e.get("created_at", ""))[:19] if e.get("created_at") else "",
                }
                for e in filtered
            ])

            st.dataframe(
                df,
                use_container_width=True,
                hide_index=True,
            )
