"""Slang dictionary — browse and search black-market terminology."""

import streamlit as st
import pandas as pd

import ui.theme as T


def show():
    st.markdown("## 黑话词典")
    st.caption("黑灰产领域术语库")

    # Fetch
    try:
        from storage.mysql_store import mysql
        slangs = mysql.list_slang()
    except Exception:
        slangs = []

    if not slangs:
        st.markdown(T.empty("📖", "黑话词典为空", "运行 python main.py init-db 加载数据"), unsafe_allow_html=True)
        return

    # Stats
    cats = {}
    for s in slangs:
        c = s.get("category", "未分类")
        cats[c] = cats.get(c, 0) + 1

    stat_cols = st.columns(len(cats) + 1)
    with stat_cols[0]:
        st.metric("总计", len(slangs))
    for i, (cat, cnt) in enumerate(sorted(cats.items())):
        with stat_cols[i + 1]:
            st.metric(cat, cnt)

    st.divider()

    # Search + filter
    c1, c2 = st.columns([3, 1.5])
    with c1:
        search = st.text_input("搜索", placeholder="输入关键词...", label_visibility="collapsed")
    with c2:
        cat_filter = st.selectbox("分类", ["全部"] + sorted(cats.keys()), label_visibility="collapsed")

    # Filter
    rows = slangs
    if search:
        rows = [s for s in rows if search in s.get("slang", "") or search in s.get("normalized_meaning", "")]
    if cat_filter != "全部":
        rows = [s for s in rows if s.get("category") == cat_filter]

    st.caption(f"共 {len(rows)} 条")

    if not rows:
        st.markdown(T.empty("🔍", "无匹配结果", "试试其他搜索词"), unsafe_allow_html=True)
        return

    df = pd.DataFrame([{
        "黑话": s["slang"],
        "含义": s["normalized_meaning"],
        "分类": s.get("category", ""),
        "来源": s.get("source", ""),
        "状态": s.get("status", "active"),
    } for s in rows])

    st.dataframe(df, use_container_width=True, hide_index=True)
