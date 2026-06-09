from __future__ import annotations

import pandas as pd
import streamlit as st

import ui.labels as L
from ui import data
from ui.components import auto_refresh, empty_panel, page_header


STATUS_OPTIONS = {
    "全部": None,
    "待研判": "RAW_COLLECTED",
    "已清洗待研判": "CLEANED",
    "研判中": "ANALYZING",
    "已初筛": "SCREENED",
    "已研判": "ANALYZED",
    "研判失败": "FAILED",
    "已丢弃": "DISCARDED",
}


def _table(rows: list[dict]) -> pd.DataFrame:
    return pd.DataFrame([
        {
            "情报ID": r.get("id"),
            "来源": r.get("source_platform") or "-",
            "频道": r.get("source_channel") or "-",
            "作者": r.get("author_name") or "-",
            "内容摘要": r.get("content_preview") or "",
            "处理状态": L.raw_status_label(r.get("raw_status")),
            "风险": (r.get("risk_label") or "未分类")
            + (f" / {r.get('risk_sub_label')}" if r.get("risk_sub_label") else ""),
            "风险分": (
                f"{float(r.get('risk_score') or 0):.2f}"
                if r.get("risk_score") is not None else "-"
            ),
            "判定方式": L.classification_method_label(r.get("classification_method") or ""),
            "接收时间": str(r.get("collect_time") or "")[:19],
        }
        for r in rows
    ])


def _jobs_table(rows: list[dict]) -> pd.DataFrame:
    return pd.DataFrame([
        {
            "任务ID": j.get("job_id"),
            "情报ID": j.get("raw_id"),
            "状态": L.job_status_label(j.get("status")),
            "进度": f"{j.get('progress') or 0}%",
            "当前步骤": j.get("current_step") or "-",
            "错误": (j.get("error_message") or "")[:80],
            "创建时间": str(j.get("created_at") or "")[:19],
        }
        for j in rows
    ])


def render_pool(include_header: bool = True):
    data.recover_unfinished_jobs(limit=20)
    if include_header:
        page_header(
            "Intel Pool",
            "情报池",
            "查看已接收的结构化数据，并按状态批量提交后台研判。",
        )
    else:
        st.markdown("### 情报池 / 批量处理")

    c1, c2, c3, c4 = st.columns([1, 1, 1.7, 0.8])
    with c1:
        status_label = st.selectbox("处理状态", list(STATUS_OPTIONS.keys()), key="pool_status")
    with c2:
        limit = st.number_input("读取数量", min_value=20, max_value=1000, value=300, step=20)
    with c3:
        keyword = st.text_input("搜索", placeholder="内容、作者或频道", key="pool_keyword")
    with c4:
        batch_size = st.number_input("批量数", min_value=1, max_value=50, value=10, step=1)

    rows = data.list_intel(status=STATUS_OPTIONS[status_label], keyword=keyword, limit=int(limit))
    eligible = [r for r in rows if r.get("raw_status") in ("RAW_COLLECTED", "CLEANED", "FAILED")]

    b1, b2, b3 = st.columns([1, 1, 2])
    b1.metric("当前结果", len(rows))
    b2.metric("可提交", len(eligible))
    with b3:
        if st.button(
            "提交当前筛选到智能分层队列",
            type="primary",
            disabled=not eligible,
            use_container_width=True,
        ):
            job_ids = data.submit_batch_jobs(
                eligible,
                options={
                    "enable_llm": False,
                    "enable_roberta": False,
                    "enable_embedding": False,
                    "enable_graph_expand": False,
                    "enable_report": False,
                    "analysis_mode": "批量智能初筛",
                    "auto_escalate": True,
                    "standard_threshold": 0.45,
                    "graph_threshold": 0.55,
                },
                max_items=int(batch_size),
            )
            st.session_state.pool_last_jobs = job_ids
            st.success(
                f"已提交 {len(job_ids)} 个初筛任务；命中条件的样本会自动追加标准研判或扩线研判。"
            )
            st.rerun()

    if not rows:
        empty_panel("没有符合条件的情报", "可以调整筛选条件，或等待新的结构化数据入库。")
    else:
        st.dataframe(
            _table(rows),
            hide_index=True,
            use_container_width=True,
            column_config={
                "情报ID": st.column_config.NumberColumn(width="small"),
                "内容摘要": st.column_config.TextColumn(width="large"),
                "接收时间": st.column_config.TextColumn(width="medium"),
            },
        )

    st.markdown("### 后台任务")
    jobs = data.list_jobs(limit=12)
    if jobs:
        st.dataframe(_jobs_table(jobs), hide_index=True, use_container_width=True)
    else:
        st.info("暂无后台任务。")

    if data.has_active_jobs():
        auto_refresh(interval_ms=2500)


def show():
    render_pool(include_header=True)
