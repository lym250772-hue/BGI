from __future__ import annotations

import pandas as pd
import streamlit as st

import ui.labels as L
import ui.theme as T
from ui import data
from ui.components import (
    empty_panel,
    job_status_badge,
    page_header,
    raw_status_badge,
    risk_badge,
)


STATUS_OPTIONS = {
    "待研判": "RAW_COLLECTED",
    "已清洗待研判": "CLEANED",
    "研判失败": "FAILED",
    "已研判": "ANALYZED",
    "全部": None,
}

MODE_OPTIONS = {
    "快速筛查": {
        "desc": "规则和已有词典优先，关闭 LLM 与图谱扩线，适合批量初筛。",
        "options": {"enable_llm": False, "enable_graph_expand": False, "enable_report": False},
    },
    "标准研判": {
        "desc": "规则/NLP/LLM 协同，产出分类、实体、证据和风险评分。",
        "options": {"enable_llm": True, "enable_graph_expand": False, "enable_report": False},
    },
    "扩线研判": {
        "desc": "在标准研判基础上启用 Neo4j 扩线，适合账号、链接、联系方式明确的样本。",
        "options": {"enable_llm": True, "enable_graph_expand": True, "enable_report": False},
    },
}


def _option_label(row: dict) -> str:
    return (
        f"#{row['id']} [{row.get('source_platform') or '-'}] "
        f"{L.raw_status_label(row.get('raw_status'))} | {row.get('content_preview') or ''}"
    )


def _render_result(raw_id: int):
    result = data.get_analysis_bundle(raw_id)
    risk_label = result.get("risk_label") or "未分类"
    score = float(result.get("risk_score") or 0)

    st.markdown("### 研判结论")
    a, b, c, d = st.columns(4)
    a.metric("风险大类", risk_label)
    b.metric("细分类型", result.get("risk_sub_label") or "-")
    c.metric("风险分", f"{score:.2f}")
    d.markdown(
        f"<div style='padding-top:1.2rem'>{risk_badge(result.get('risk_level'))}</div>",
        unsafe_allow_html=True,
    )

    st.markdown("### 证据片段")
    evidence = result.get("evidence_spans") or []
    if evidence:
        for idx, ev in enumerate(evidence[:8], start=1):
            if isinstance(ev, dict):
                text = ev.get("text") or ev.get("evidence") or ev.get("span") or str(ev)
                reason = ev.get("reason") or ev.get("label") or ""
            else:
                text = str(ev)
                reason = ""
            st.markdown(
                f"""
                <div class='bagi-panel-tight' style='margin-bottom:7px'>
                  <div class='mono' style='color:{T.ACCENT};font-size:0.72rem'>Evidence {idx}</div>
                  <div style='margin-top:3px'>{text}</div>
                  <div class='section-note'>{reason}</div>
                </div>
                """,
                unsafe_allow_html=True,
            )
    else:
        st.info("暂无证据片段，可能是未研判或降级路径未产出。")

    left, right = st.columns([1.1, 1])
    with left:
        st.markdown("### 抽取实体")
        entities = result.get("entities") or []
        if entities:
            df = pd.DataFrame([
                {
                    "类型": L.entity_type_label(e.get("entity_type")),
                    "值": e.get("entity_value"),
                    "方式": L.extraction_method_label(e.get("extraction_method")),
                    "置信度": f"{float(e.get('confidence') or 0):.2f}",
                    "上下文": e.get("context") or "",
                }
                for e in entities
            ])
            st.dataframe(df, hide_index=True, use_container_width=True)
        else:
            st.info("暂无实体。")

    with right:
        st.markdown("### 新黑话候选")
        candidates = result.get("new_slang_candidates") or []
        if candidates:
            for item in candidates[:5]:
                term = item.get("term") or ""
                meaning = item.get("suggested_meaning") or item.get("normalized_meaning") or ""
                st.markdown(
                    f"""
                    <div class='bagi-panel-tight' style='margin-bottom:7px'>
                      <strong>{term}</strong>
                      <div class='section-note'>{meaning}</div>
                    </div>
                    """,
                    unsafe_allow_html=True,
                )
        else:
            st.info("本条情报没有待审核新黑话。")

    if result.get("agent_summary"):
        st.markdown("### 摘要")
        st.write(result.get("agent_summary"))


def _jobs_table():
    rows = data.list_jobs(limit=12)
    if not rows:
        st.info("暂无后台任务。")
        return
    df = pd.DataFrame([
        {
            "任务ID": r.get("job_id"),
            "情报ID": r.get("raw_id"),
            "状态": L.job_status_label(r.get("status")),
            "进度": f"{r.get('progress') or 0}%",
            "当前步骤": r.get("current_step") or "-",
            "错误": (r.get("error_message") or "")[:80],
            "创建时间": str(r.get("created_at") or "")[:19],
        }
        for r in rows
    ])
    st.dataframe(df, hide_index=True, use_container_width=True)


def show():
    page_header(
        "Analysis Workbench",
        "研判工作台",
        "从待研判队列选择情报，提交后台任务；页面不阻塞，可以连续处理多条黑话数据。",
    )

    q1, q2, q3 = st.columns([1, 1, 1.4])
    with q1:
        status_label = st.selectbox("队列", list(STATUS_OPTIONS.keys()), key="wb_status")
    with q2:
        mode_label = st.selectbox("研判模式", list(MODE_OPTIONS.keys()), key="wb_mode")
    with q3:
        keyword = st.text_input("搜索", placeholder="内容、作者、频道关键词", key="wb_keyword")

    mode = MODE_OPTIONS[mode_label]
    st.caption(mode["desc"])

    rows = data.list_intel(status=STATUS_OPTIONS[status_label], keyword=keyword, limit=120)
    if not rows:
        empty_panel("当前队列没有情报", "可以切换到其他队列，或等待搭档导入新的结构化数据。")
        st.markdown("### 后台任务")
        _jobs_table()
        return

    options = {_option_label(r): r["id"] for r in rows}
    selected_label = st.selectbox("选择情报", list(options.keys()), key="wb_selected")
    raw_id = int(options[selected_label])
    selected = next(r for r in rows if int(r["id"]) == raw_id)

    top_left, top_right = st.columns([1.15, 0.85])
    with top_left:
        st.markdown(
            f"""
            <div class='intel-card'>
              <div style='display:flex;gap:8px;align-items:center;margin-bottom:8px'>
                {raw_status_badge(selected.get('raw_status'))}
                <span class='mono' style='color:{T.MUTED}'>#{raw_id}</span>
                <span style='color:{T.MUTED}'>{selected.get('source_platform') or '-'}</span>
              </div>
              <div>{selected.get('content_raw') or ''}</div>
            </div>
            """,
            unsafe_allow_html=True,
        )
    with top_right:
        st.markdown("<div class='bagi-panel'>", unsafe_allow_html=True)
        st.markdown("<div class='section-title'>提交后台研判</div>", unsafe_allow_html=True)
        st.caption("不会阻塞页面。提交后可以继续切换其他情报。")
        if st.button("提交研判任务", type="primary", use_container_width=True, key="submit_job"):
            text = data.preferred_text(raw_id, fallback=selected.get("content_raw") or "")
            job_id = data.submit_analysis_job(
                raw_id=raw_id,
                text=text,
                platform=selected.get("source_platform") or "unknown",
                options={**mode["options"], "analysis_mode": mode_label},
            )
            st.success(f"已提交任务：{job_id}")
            st.rerun()
        st.markdown("</div>", unsafe_allow_html=True)

    st.divider()
    tab_result, tab_jobs = st.tabs(["研判结果", "后台任务"])
    with tab_result:
        if selected.get("risk_label") or selected.get("raw_status") == "ANALYZED":
            _render_result(raw_id)
        else:
            empty_panel("尚未完成研判", "提交后台任务后，任务完成会自动写回 MySQL、Neo4j、Milvus 和 Doris。")
    with tab_jobs:
        _jobs_table()
