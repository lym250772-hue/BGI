"""Intel list — browse, filter, and search intelligence items."""

import streamlit as st
import pandas as pd

import ui.theme as T

PLATFORMS = ["全部", "telegram", "tieba", "weibo", "zhihu", "xiaohongshu", "forum"]
RISK_LABELS = ["全部", "诈骗", "引流", "作弊", "账号黑产", "内容违规", "工具交易", "直播违规"]
PRIORITIES = ["全部", "high", "critical", "normal"]


def show():
    st.markdown("## 情报列表")
    st.caption("浏览、筛选和检索黑灰产情报")

    # Filter bar
    c1, c2, c3, c4 = st.columns([2.5, 1.5, 1.5, 1.2])
    with c1:
        kw = st.text_input("搜索", placeholder="输入关键词...", label_visibility="collapsed")
    with c2:
        plat = st.selectbox("平台", PLATFORMS, label_visibility="collapsed")
    with c3:
        risk = st.selectbox("风险", RISK_LABELS, label_visibility="collapsed")
    with c4:
        pri = st.selectbox("优先级", PRIORITIES, label_visibility="collapsed")

    st.divider()

    # Fetch
    try:
        from storage.mysql_store import mysql
        filters = {"limit": 200}
        if pri != "全部":
            filters["priority"] = pri
        if plat != "全部":
            filters["platform"] = plat
        raw = mysql.list_raw(**filters)
    except Exception:
        raw = []

    if not raw:
        st.markdown(
            T.empty("🔍", "暂无情报数据", "运行 python main.py collect --platform telegram 开始采集"),
            unsafe_allow_html=True,
        )
        # Quick-start hint
        with st.expander("快速开始采集"):
            st.code("python main.py collect --platform telegram --tg-groups group1", language="bash")
            st.markdown(
                f"""<div style="font-size:0.82rem;color:{T.TEXT_MUTED};margin-top:0.5rem">
                需要先在 <code>.env</code> 中配置 <code>TELEGRAM_API_ID</code> 和 <code>TELEGRAM_API_HASH</code></div>""",
                unsafe_allow_html=True,
            )
        return

    # Client-side keyword filter
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
        "内容": (r.get("content") or r.get("content_raw", ""))[:80],
        "来源": r.get("source_platform", ""),
        "风险": r.get("intent_label", "") or "未分类",
        "优先级": r.get("priority", "normal"),
        "时间": str(r.get("collected_at", ""))[:19],
    } for r in rows])

    st.dataframe(
        df,
        width="stretch",
        hide_index=True,
        column_config={
            "ID": st.column_config.NumberColumn(width="small"),
            "内容": st.column_config.TextColumn(width="large"),
            "来源": st.column_config.TextColumn(width="small"),
            "风险": st.column_config.TextColumn(width="small"),
            "优先级": st.column_config.TextColumn(width="small"),
            "时间": st.column_config.TextColumn(width="medium"),
        },
    )
