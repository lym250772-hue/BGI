from __future__ import annotations

import pandas as pd
import streamlit as st

import ui.labels as L
import ui.theme as T
from ui import data
from ui.components import (
    auto_refresh,
    empty_panel,
    page_header,
    raw_status_badge,
    risk_badge,
)


STATUS_OPTIONS = {
    "已清洗待研判": "CLEANED",
    "研判失败": "FAILED",
    "已研判": "ANALYZED",
    "全部": None,
}

MODE_OPTIONS = {
    "快速筛查": {
        "desc": "规则和已有词典优先，关闭 LLM、向量检索与图谱扩线，可继续升级为标准研判。",
        "options": {
            "enable_llm": False,
            "enable_roberta": False,
            "enable_embedding": False,
            "enable_graph_expand": False,
            "enable_report": False,
        },
    },
    "标准研判": {
        "desc": "规则/NLP/LLM 协同，关闭高成本向量扩展，产出分类、实体、证据和风险评分。",
        "options": {
            "enable_llm": True,
            "enable_roberta": True,
            "enable_embedding": False,
            "enable_graph_expand": False,
            "enable_report": False,
        },
    },
    "扩线研判": {
        "desc": "启用向量相似检索与 Neo4j 扩线；只对账号、链接、联系方式明确的样本有增量。",
        "options": {
            "enable_llm": True,
            "enable_roberta": True,
            "enable_embedding": True,
            "enable_graph_expand": True,
            "enable_report": False,
        },
    },
}


def _query_int(name: str) -> int | None:
    try:
        value = st.query_params.get(name)
        if isinstance(value, list):
            value = value[0] if value else None
        return int(value) if value else None
    except Exception:
        return None


def _option_label(row: dict) -> str:
    author = row.get("author_name") or "-"
    return (
        f"#{row['id']} [{row.get('source_platform') or '-'}] @{author} "
        f"{L.raw_status_label(row.get('raw_status'))} | {row.get('content_preview') or ''}"
    )


def _render_result(raw_id: int):
    result = data.get_analysis_bundle(raw_id)
    if not result:
        empty_panel("尚未完成研判", "提交后台任务后，任务完成会自动写回 MySQL、Neo4j 和 Milvus。")
        return

    risk_label = result.get("risk_label") or "未分类"
    score = float(result.get("risk_score") or 0)

    st.markdown(f"### 研判结论 · #{raw_id}")
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
        st.info("暂无证据片段。可能是规则路径未产生证据，或样本风险较低。")

    st.markdown("### 历史相似情报")
    similar_rows = result.get("similar_intel") or []
    if similar_rows:
        df = pd.DataFrame([
            {
                "情报ID": r.get("id"),
                "相似度": (
                    f"{float(r.get('similarity')):.2f}"
                    if r.get("similarity") is not None else "-"
                ),
                "向量距离": (
                    f"{float(r.get('distance')):.4f}"
                    if r.get("distance") is not None else "-"
                ),
                "来源": r.get("source_platform") or "-",
                "风险": (r.get("risk_label") or "未分类")
                + (f" / {r.get('risk_sub_label')}" if r.get("risk_sub_label") else ""),
                "风险分": (
                    f"{float(r.get('risk_score')):.2f}"
                    if r.get("risk_score") is not None else "-"
                ),
                "内容摘要": r.get("content_preview") or "",
                "研判时间": str(r.get("analyzed_at") or r.get("collect_time") or "")[:19],
            }
            for r in similar_rows[:8]
        ])
        st.dataframe(df, hide_index=True, use_container_width=True)
    else:
        st.info("暂无历史相似情报。快速筛查和标准研判默认不启用向量检索，扩线研判才会尝试召回历史相似样本。")

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
        return []
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
    return rows


def _render_pending_result(raw_id: int, selected: dict):
    latest = data.latest_job_for_raw(raw_id)
    status = L.raw_status_label(selected.get("raw_status"))
    if latest:
        status = L.job_status_label(latest.get("status"))
    progress = latest.get("progress") if latest else 0
    step = latest.get("current_step") or "-"
    error = latest.get("error_message") or ""

    st.markdown("### 当前研判状态")
    c1, c2, c3 = st.columns(3)
    c1.metric("情报ID", f"#{raw_id}")
    c2.metric("状态", status)
    c3.metric("进度", f"{progress or 0}%")
    st.markdown(
        f"""
        <div class='intel-card' style='margin-top:0.6rem'>
          <div class='section-note'>当前步骤：{step}</div>
          <div style='margin-top:0.4rem'>{selected.get('content_raw') or ''}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )
    if error:
        st.error(error)
    else:
        st.info("任务尚未完成。页面会在后台任务执行期间自动刷新。")


def _active_result_id(current_raw_id: int) -> int:
    active = _query_int("result_raw_id") or st.session_state.get("wb_active_raw_id")
    try:
        return int(active or current_raw_id)
    except Exception:
        return current_raw_id


def _should_render_result(raw_id: int, raw_status: str, latest_job: dict) -> bool:
    if latest_job.get("status") == "success":
        return True
    return raw_status in ("ANALYZED",)


def _render_active_result(active_raw_id: int, selected: dict | None = None):
    active_raw = data.get_raw(active_raw_id) or {}
    fallback = selected or {}
    active_status = active_raw.get("raw_status") or fallback.get("raw_status") or ""
    latest_job = data.latest_job_for_raw(active_raw_id)

    if _should_render_result(active_raw_id, active_status, latest_job):
        result = data.get_analysis_bundle(active_raw_id)
        if result:
            _render_result(active_raw_id)
        else:
            _render_pending_result(active_raw_id, active_raw or fallback)
    elif active_status == "FAILED" or latest_job.get("status") == "failed":
        error_msg = latest_job.get("error_message") or ""
        meta = active_raw.get("metadata") or {}
        if isinstance(meta, dict):
            error_msg = error_msg or meta.get("last_error", "")
        st.error(error_msg or "研判失败，请查看后台任务错误。")
    else:
        _render_pending_result(active_raw_id, active_raw or fallback)


def show():
    data.recover_unfinished_jobs(limit=20)
    page_header(
        "Analysis Workbench",
        "研判工作台",
        "从队列选择情报并提交后台研判；页面不阻塞，可以连续处理多条黑话数据。",
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
        active_raw_id = _query_int("result_raw_id") or st.session_state.get("wb_active_raw_id")
        if active_raw_id:
            st.divider()
            st.markdown("### 当前提交")
            _render_active_result(int(active_raw_id))
        st.markdown("### 后台任务")
        job_rows = _jobs_table()
        if any(j.get("status") in ("pending", "running") for j in job_rows):
            auto_refresh(interval_ms=2500)
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
                <span style='color:{T.MUTED}'>@{selected.get('author_name') or '-'}</span>
              </div>
              <div>{selected.get('content_raw') or ''}</div>
            </div>
            """,
            unsafe_allow_html=True,
        )
    with top_right:
        st.markdown("### 提交后台研判")
        st.caption("不会阻塞页面。提交后可以继续切换其他情报。")
        if st.button("提交研判任务", type="primary", use_container_width=True, key="submit_job"):
            text = data.preferred_text(raw_id, fallback=selected.get("content_raw") or "")
            job_id = data.submit_analysis_job(
                raw_id=raw_id,
                text=text,
                platform=selected.get("source_platform") or "unknown",
                options={**mode["options"], "analysis_mode": mode_label},
            )
            st.session_state.wb_active_raw_id = raw_id
            st.session_state.wb_last_job_id = job_id
            try:
                st.query_params["page"] = "workbench"
                st.query_params["result_raw_id"] = str(raw_id)
            except Exception:
                pass
            st.success(f"已提交任务：{job_id}")
            st.rerun()

    st.divider()
    tab_result, tab_jobs = st.tabs(["研判结果", "后台任务"])
    with tab_result:
        active_raw_id = _active_result_id(raw_id)
        _render_active_result(active_raw_id, selected if active_raw_id == raw_id else None)
    with tab_jobs:
        _jobs_table()

    if data.has_active_jobs():
        auto_refresh(interval_ms=2500)
