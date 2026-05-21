"""Intel list page — browse, filter, and search intelligence items."""

import streamlit as st
import pandas as pd

from ui.theme import empty_state, priority_badge


def _mysql():
    from storage.mysql_store import mysql as m
    return m


def show():
    st.markdown("## 情报列表")
    st.caption("浏览、筛选和检索采集到的黑灰产情报")

    # ---- Filters ----
    c1, c2, c3, c4 = st.columns([2, 2, 2, 1.5])
    with c1:
        keyword = st.text_input("关键词搜索", placeholder="输入搜索内容...", label_visibility="collapsed")
    with c2:
        platform = st.selectbox(
            "平台", ["全部", "telegram", "tieba", "weibo", "zhihu", "xiaohongshu", "forum"],
            label_visibility="collapsed",
        )
    with c3:
        risk = st.selectbox(
            "风险类型",
            ["全部", "诈骗", "引流", "作弊", "账号黑产", "内容违规", "工具交易", "直播违规"],
            label_visibility="collapsed",
        )
    with c4:
        priority = st.selectbox(
            "优先级", ["全部", "high", "critical", "normal"],
            label_visibility="collapsed",
        )

    st.divider()

    # ---- Fetch data ----
    try:
        filters = {"limit": 200}
        if priority != "全部":
            filters["priority"] = priority
        if platform != "全部":
            filters["platform"] = platform

        mysql = _mysql()
        items = mysql.list_raw(**filters)

        if not items:
            st.markdown(
                empty_state("🔍", "暂无情报数据", "运行 python main.py collect 采集数据"),
                unsafe_allow_html=True,
            )
            return

        # Apply client-side keyword + risk filtering
        rows = []
        for item in items:
            text = item.get("content") or item.get("content_raw", "")
            if keyword and keyword not in text:
                continue
            if risk != "全部":
                intent = item.get("intent_label", "")
                if intent != risk:
                    continue
            rows.append(item)

        if not rows:
            st.markdown(
                empty_state("🔍", "无匹配结果", "尝试调整筛选条件"),
                unsafe_allow_html=True,
            )
            return

        st.caption(f"共 {len(rows)} 条记录")

        # ---- Table ----
        df = pd.DataFrame([
            {
                "ID": r.get("id", ""),
                "内容": (r.get("content") or r.get("content_raw", ""))[:80],
                "来源": r.get("source_platform", ""),
                "风险标签": r.get("intent_label", "") or "未分类",
                "优先级": r.get("priority", "normal"),
                "时间": str(r.get("collected_at", ""))[:19],
            }
            for r in rows
        ])

        # Style the priority column
        st.dataframe(
            df,
            use_container_width=True,
            hide_index=True,
            column_config={
                "ID": st.column_config.NumberColumn("ID", width="small"),
                "内容": st.column_config.TextColumn("内容", width="large"),
                "来源": st.column_config.TextColumn("来源", width="small"),
                "风险标签": st.column_config.TextColumn("风险标签", width="small"),
                "优先级": st.column_config.TextColumn("优先级", width="small"),
                "时间": st.column_config.TextColumn("采集时间", width="medium"),
            },
        )
    except Exception as exc:
        st.markdown(
            empty_state("⚠️", "数据库连接失败", f"请确认 MySQL 服务已启动 · {exc}"),
            unsafe_allow_html=True,
        )
