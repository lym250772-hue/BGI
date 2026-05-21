"""Entity library — browse extracted entities by type."""

import streamlit as st
import pandas as pd

import ui.theme as T


def show():
    st.markdown("## 实体库")
    st.caption("提取的实体：账号、链接、黑话、工具等")

    # ---- Fetch ----
    try:
        from storage.mysql_store import mysql
        with mysql.cursor() as c:
            c.execute("SELECT entity_type, COUNT(*) as cnt FROM entities GROUP BY entity_type ORDER BY cnt DESC")
            stats = c.fetchall()
            c.execute("SELECT COUNT(*) as total FROM entities")
            total = c.fetchone()["total"]
            c.execute("SELECT * FROM entities ORDER BY id DESC LIMIT 200")
            all_ents = c.fetchall()
    except Exception:
        stats, total, all_ents = [], 0, []

    # ---- Summary bar ----
    if stats:
        cols = st.columns(len(stats) + 1)
        with cols[0]:
            st.metric("总计", total)
        for i, row in enumerate(stats):
            with cols[i + 1]:
                st.metric(row["entity_type"], row["cnt"])
    else:
        st.metric("总计", 0)

    st.divider()

    if not all_ents:
        st.markdown(T.empty("🔗", "暂无实体数据", "分析情报后将自动提取实体"), unsafe_allow_html=True)
        return

    # ---- Tabs by type ----
    types = sorted({e["entity_type"] for e in all_ents})
    tabs = st.tabs(["全部"] + types)

    for i, tab_name in enumerate(tabs):
        with tab_name:
            subset = all_ents if tab_name == "全部" else [e for e in all_ents if e["entity_type"] == tab_name]
            if not subset:
                st.caption("暂无此类实体")
                continue

            df = pd.DataFrame([{
                "ID":    e["id"],
                "实体值": e["entity_value"],
                "方式":   e["extraction_method"],
                "上下文": (e.get("context") or "")[:50],
                "时间":   str(e.get("created_at", ""))[:19] if e.get("created_at") else "",
            } for e in subset])
            st.dataframe(df, use_container_width=True, hide_index=True)
