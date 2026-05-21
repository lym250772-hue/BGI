"""Slang dictionary — browse and search black-market terminology."""

import streamlit as st
import pandas as pd

import ui.theme as T


def show():
    st.markdown("## 黑话词典")
    st.caption("黑灰产领域术语库 · 共收录 49 条种子数据")

    try:
        from storage.mysql_store import mysql
        slangs = mysql.list_slang()
    except Exception:
        slangs = []

    if not slangs:
        st.markdown(T.empty("📖", "黑话词典为空", "运行 python main.py init-db 加载数据"), unsafe_allow_html=True)
        return

    # Category stats
    cats = {}
    for s in slangs:
        c = s.get("category", "未分类")
        cats[c] = cats.get(c, 0) + 1

    # Category color mapping
    cat_colors = {
        "诈骗": T.ROSE, "引流": T.GOLD, "作弊": T.SLATE,
        "账号黑产": T.ROSE_DARK, "内容违规": T.SAGE_DARK,
        "工具交易": "#9A8A7A", "直播违规": "#8A7A8A",
    }

    # Stats row — styled chips
    chips_html = f'<span style="display:inline-flex;align-items:center;gap:6px;background:{T.BG_CARD};border:1px solid {T.BORDER};border-radius:20px;padding:6px 14px;margin-right:8px;font-size:0.82rem;color:{T.TEXT_MAIN};font-weight:500">总计 <strong>{len(slangs)}</strong></span>'
    for cat, cnt in sorted(cats.items()):
        color = cat_colors.get(cat, T.SLATE)
        chips_html += f'<span style="display:inline-flex;align-items:center;gap:4px;background:{T.BG_CARD};border:1px solid {T.BORDER};border-radius:20px;padding:6px 12px;margin-right:8px;font-size:0.78rem;color:{T.TEXT_SOFT}"><span style="width:7px;height:7px;border-radius:50%;background:{color};display:inline-block"></span>{cat} {cnt}</span>'

    st.markdown(f'<div style="margin-bottom:1rem">{chips_html}</div>', unsafe_allow_html=True)

    st.divider()

    # Search + filter bar
    c1, c2 = st.columns([3, 1.5])
    with c1:
        search = st.text_input("搜索黑话或含义", placeholder="输入关键词...", label_visibility="collapsed")
    with c2:
        cat_filter = st.selectbox("分类筛选", ["全部"] + sorted(cats.keys()), label_visibility="collapsed")

    # Apply filters
    rows = slangs
    if search:
        rows = [s for s in rows if search.lower() in s.get("slang", "").lower() or search.lower() in s.get("normalized_meaning", "").lower()]
    if cat_filter != "全部":
        rows = [s for s in rows if s.get("category") == cat_filter]

    st.caption(f"共 {len(rows)} 条")

    if not rows:
        st.markdown(T.empty("🔍", "无匹配结果", "试试其他搜索词"), unsafe_allow_html=True)
        return

    # Build category-tabbed view
    available_cats = sorted({s.get("category", "") for s in rows})
    tab_labels = ["全部"] + available_cats
    tabs = st.tabs(tab_labels)

    for i, tab in enumerate(tabs):
        label = tab_labels[i]
        with tab:
            subset = rows if label == "全部" else [s for s in rows if s.get("category") == label]
            if not subset:
                st.caption("暂无此类数据")
                continue

            df = pd.DataFrame([{
                "黑话": s["slang"],
                "含义": s["normalized_meaning"],
                "分类": s.get("category", ""),
                "来源": s.get("source", ""),
            } for s in subset])

            st.dataframe(
                df,
                width="stretch",
                hide_index=True,
                column_config={
                    "黑话": st.column_config.TextColumn(width="small"),
                    "含义": st.column_config.TextColumn(width="large"),
                    "分类": st.column_config.TextColumn(width="small"),
                    "来源": st.column_config.TextColumn(width="small"),
                },
            )
