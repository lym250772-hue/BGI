"""Slang dictionary page — browse, search, and manage black-market slang."""

import streamlit as st
import pandas as pd

from ui.theme import empty_state


def _mysql():
    from storage.mysql_store import mysql as m
    return m


def show():
    st.markdown("## 黑话词典")
    st.caption("黑灰产领域黑话术语库，支持搜索和分类浏览")

    # ---- Fetch from MySQL ----
    try:
        mysql = _mysql()
        slangs = mysql.list_slang()
    except Exception:
        slangs = []

    if not slangs:
        st.markdown(
            empty_state("📖", "黑话词典为空", "运行 python main.py init-db 加载种子数据"),
            unsafe_allow_html=True,
        )
        return

    # ---- Stats bar ----
    total = len(slangs)
    categories = {}
    for s in slangs:
        cat = s.get("category", "未分类")
        categories[cat] = categories.get(cat, 0) + 1

    stats_cols = st.columns(len(categories) + 1)
    with stats_cols[0]:
        st.metric("总计", total)
    for i, (cat, cnt) in enumerate(sorted(categories.items())):
        with stats_cols[i + 1]:
            st.metric(cat, cnt)

    st.divider()

    # ---- Search + Filter ----
    c1, c2 = st.columns([3, 1.5])
    with c1:
        search = st.text_input("搜索黑话", placeholder="输入关键词搜索…", label_visibility="collapsed")
    with c2:
        cat_filter = st.selectbox(
            "分类筛选",
            ["全部"] + sorted(categories.keys()),
            label_visibility="collapsed",
        )

    # ---- Filter ----
    filtered = slangs
    if search:
        filtered = [
            s for s in filtered
            if search in s.get("slang", "")
            or search in s.get("normalized_meaning", "")
        ]
    if cat_filter != "全部":
        filtered = [s for s in filtered if s.get("category") == cat_filter]

    st.caption(f"共 {len(filtered)} 条")

    if not filtered:
        st.markdown(
            empty_state("🔍", "无匹配结果", "尝试其他搜索词"),
            unsafe_allow_html=True,
        )
        return

    # ---- Table ----
    df = pd.DataFrame([
        {
            "黑话": s.get("slang", ""),
            "含义": s.get("normalized_meaning", ""),
            "分类": s.get("category", ""),
            "来源": s.get("source", ""),
            "状态": s.get("status", "active"),
        }
        for s in filtered
    ])

    st.dataframe(
        df,
        use_container_width=True,
        hide_index=True,
        column_config={
            "黑话": st.column_config.TextColumn("黑话", width="small"),
            "含义": st.column_config.TextColumn("含义", width="large"),
            "分类": st.column_config.TextColumn("分类", width="small"),
            "来源": st.column_config.TextColumn("来源", width="small"),
            "状态": st.column_config.TextColumn("状态", width="small"),
        },
    )
