"""Intel list — browse, filter, and search intelligence items."""

import streamlit as st
import pandas as pd

import ui.theme as T


def show():
    st.markdown("## 情报列表")
    st.caption("浏览、筛选和检索黑灰产情报")

    # ---- Filter bar ----
    c1, c2, c3, c4 = st.columns([2.5, 1.5, 1.5, 1.2])
    with c1:
        kw = st.text_input("搜索", placeholder="输入关键词...", label_visibility="collapsed")
    with c2:
        plat = st.selectbox("平台", ["全部", "telegram", "tieba", "weibo", "zhihu", "xiaohongshu", "forum"], label_visibility="collapsed")
    with c3:
        risk = st.selectbox("风险", ["全部", "诈骗", "引流", "作弊", "账号黑产", "内容违规", "工具交易", "直播违规"], label_visibility="collapsed")
    with c4:
        pri = st.selectbox("优先级", ["全部", "high", "critical", "normal"], label_visibility="collapsed")

    st.divider()

    # ---- Fetch ----
    try:
        from storage.mysql_store import mysql
        filters = {"limit": 200}
        if pri != "全部": filters["priority"] = pri
        if plat != "全部": filters["platform"] = plat
        raw = mysql.list_raw(**filters)
    except Exception:
        raw = []

    if not raw:
        st.markdown(T.empty("🔍", "暂无情报数据", "运行 python main.py collect 采集数据"), unsafe_allow_html=True)
        return

    # ---- Client-side filter ----
    rows = []
    for r in raw:
        text = r.get("content") or r.get("content_raw", "")
        if kw and kw not in text:
            continue
        if risk != "全部":
            if r.get("intent_label", "") != risk:
                continue
        rows.append(r)

    if not rows:
        st.markdown(T.empty("🔍", "无匹配结果", "调整筛选条件试试"), unsafe_allow_html=True)
        return

    st.caption(f"共 {len(rows)} 条")

    df = pd.DataFrame([{
        "ID":   r["id"],
        "内容": (r.get("content") or r.get("content_raw", ""))[:70],
        "来源": r.get("source_platform", ""),
        "风险": r.get("intent_label", "") or "未分类",
        "优先级": r.get("priority", "normal"),
        "时间": str(r.get("collected_at", ""))[:19],
    } for r in rows])

    st.dataframe(df, use_container_width=True, hide_index=True)
