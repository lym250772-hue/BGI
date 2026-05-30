"""Batch slang analysis workbench."""

from __future__ import annotations

import json
from datetime import datetime

import pandas as pd
import streamlit as st

import ui.labels as L
import ui.theme as T


MODE_CONFIG = {
    "快速筛查": {
        "enable_llm": False,
        "enable_graph_expand": False,
        "enable_report": True,
        "desc": "规则、词典和实体证据优先，适合一次处理大量样本。",
    },
    "关系扩线": {
        "enable_llm": False,
        "enable_graph_expand": True,
        "enable_report": True,
        "desc": "额外查询 Neo4j，发现共享账号、联系方式、域名和历史团伙。",
    },
    "深度复核": {
        "enable_llm": True,
        "enable_graph_expand": True,
        "enable_report": True,
        "desc": "启用大模型兜底，适合少量疑难样本和疑似新黑话发现。",
    },
}


def _ensure_state():
    if "slang_jobs" not in st.session_state:
        st.session_state.slang_jobs = []
    if "slang_selected_job" not in st.session_state:
        st.session_state.slang_selected_job = None


def _create_manual_raw(text: str, source_keyword: str = "manual_slang") -> int:
    from storage.mysql_store import mysql

    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    return mysql.insert_raw({
        "source_platform": "manual",
        "source_channel": "slang_workbench",
        "source_keyword": source_keyword,
        "source_url": "",
        "author_id": "analyst",
        "author_name": "manual_input",
        "publish_time": now,
        "collect_time": now,
        "content_type": "text",
        "content_raw": text,
        "raw_status": "RAW_COLLECTED",
        "metadata": json.dumps({"source": "slang_workbench"}, ensure_ascii=False),
    })


def _submit_jobs(lines: list[str], mode: str) -> list[dict]:
    from analyzer.worker import submit_analysis
    from storage.mysql_store import mysql

    options = dict(MODE_CONFIG[mode])
    options["analysis_mode"] = mode
    options.pop("desc", None)

    created = []
    for text in lines:
        raw_id = _create_manual_raw(text)
        job_id = mysql.create_job(raw_id, text, "manual", options=options)
        submit_analysis(job_id, raw_id, text, "manual", options=options)
        created.append({"job_id": job_id, "raw_id": raw_id, "text": text})
    return created


def _load_jobs(job_ids: list[str]) -> list[dict]:
    from storage.mysql_store import mysql

    jobs = []
    for job_id in job_ids:
        job = mysql.get_job(job_id)
        if job:
            jobs.append(job)
    return jobs


def _load_result(raw_id: int) -> dict:
    from storage.mysql_store import mysql
    return mysql.get_analysis_bundle(raw_id)


def _slang_rows(slang_terms: list[dict]) -> pd.DataFrame:
    return pd.DataFrame([
        {
            "黑话": s.get("term", ""),
            "释义": s.get("meaning", "") or "-",
            "来源": L.extraction_method_label(str(s.get("source", ""))),
        }
        for s in slang_terms
    ])


def _entity_rows(entities: list[dict]) -> pd.DataFrame:
    return pd.DataFrame([
        {
            "线索类型": L.entity_type_label(e.get("entity_type", "")),
            "线索值": e.get("entity_value", ""),
            "抽取方式": L.extraction_method_label(e.get("extraction_method", "")),
        }
        for e in entities
    ])


def _job_rows(jobs: list[dict]) -> pd.DataFrame:
    return pd.DataFrame([
        {
            "任务编号": job.get("job_id"),
            "情报ID": job.get("raw_id"),
            "状态": job.get("status"),
            "进度": job.get("progress"),
            "当前步骤": job.get("current_step") or "-",
        }
        for job in jobs
    ])


def _render_candidates(result: dict):
    candidates = result.get("new_slang_candidates") or []
    if not candidates:
        return
    st.markdown("**疑似新黑话**")
    st.caption("候选词已进入黑话词典页的「待审核候选」列表，可统一确认或忽略。")
    df = pd.DataFrame([
        {
            "候选词": c.get("term", ""),
            "建议释义": c.get("suggested_meaning", ""),
            "置信度": f"{float(c.get('confidence') or 0):.2f}",
            "发现原因": c.get("reason", ""),
        }
        for c in candidates
    ])
    st.dataframe(df, width="stretch", hide_index=True)


def _render_result(result: dict):
    risk_label = result.get("risk_label") or "未分类"
    risk_sub = result.get("risk_sub_label") or ""
    risk_score = float(result.get("risk_score") or 0)
    risk_level = result.get("risk_level") or "normal"

    c1, c2, c3 = st.columns([1.1, 1.2, 1.3])
    with c1:
        st.markdown(
            f"""<div class="intel-card" style="text-align:center">
            <div style="font-size:0.78rem;color:{T.TEXT_MUTED};margin-bottom:0.3rem">风险结论</div>
            <div style="font-size:1rem;font-weight:650;color:{T.TEXT_MAIN}">{risk_label}</div>
            <div style="font-size:0.78rem;color:{T.TEXT_SOFT};margin:0.25rem 0 0.5rem 0">{risk_sub}</div>
            {T.risk_score_html(risk_score)}
            <div style="margin-top:0.4rem">{T.badge(risk_level)}</div>
            </div>""",
            unsafe_allow_html=True,
        )

    with c2:
        st.markdown("**黑话解释**")
        slang_terms = result.get("slang_terms") or []
        if slang_terms:
            st.dataframe(_slang_rows(slang_terms[:20]), width="stretch", hide_index=True)
        else:
            st.markdown(T.empty("SL", "未命中已知黑话", "疑似新黑话会进入候选池"), unsafe_allow_html=True)

    with c3:
        st.markdown("**实体线索**")
        entities = result.get("entities") or []
        if entities:
            st.dataframe(_entity_rows(entities[:30]), width="stretch", hide_index=True)
        else:
            st.markdown(T.empty("ID", "未抽取到实体", "可检查规则或词典覆盖"), unsafe_allow_html=True)

    _render_candidates(result)

    evidence = result.get("evidence_spans") or []
    if evidence:
        st.markdown("**证据片段**")
        for ev in evidence[:8]:
            st.markdown(
                f"""<div class="evidence-highlight">
                <div style="font-size:0.82rem;font-weight:550;color:{T.TEXT_MAIN}">{ev.get('text', '')}</div>
                <div style="font-size:0.74rem;color:{T.TEXT_SOFT};margin-top:0.15rem">
                {ev.get('reason', '')} · {ev.get('method', '')}</div>
                </div>""",
                unsafe_allow_html=True,
            )

    if result.get("agent_summary"):
        st.markdown("**研判摘要**")
        st.markdown(
            f"""<div class="intel-card" style="line-height:1.65;font-size:0.88rem">
            {result.get('agent_summary')}</div>""",
            unsafe_allow_html=True,
        )


def show():
    _ensure_state()
    st.markdown("## 批量黑话研判")
    st.caption("粘贴多条黑话或黑产广告，后台并发研判，完成一条即可查看一条。")

    left, right = st.columns([1.05, 1.35])

    with left:
        st.markdown("#### 输入队列")
        default_text = (
            "高价收料，接码稳定，跑分通道，飞机详聊 @safe_pay888\n"
            "抖音无人直播技术，全套教程+工具，联系微信 douyin_pro888"
        )
        raw_text = st.text_area(
            "每行一条情报",
            value=default_text,
            height=190,
            label_visibility="collapsed",
            key="slang_batch_input",
        )
        mode = st.radio(
            "研判模式",
            list(MODE_CONFIG.keys()),
            index=0,
            horizontal=True,
            key="slang_analysis_mode",
        )
        st.caption(MODE_CONFIG[mode]["desc"])

        if st.button("提交批量研判", type="primary", width="stretch", key="slang_submit"):
            lines = [line.strip() for line in raw_text.splitlines() if line.strip()]
            if not lines:
                st.warning("请输入至少一条文本")
            else:
                created = _submit_jobs(lines, mode)
                st.session_state.slang_jobs = [j["job_id"] for j in created] + list(st.session_state.slang_jobs)
                st.success(f"已提交 {len(created)} 个研判任务")
                st.rerun()

        if st.button("清空当前任务列表", width="stretch", key="slang_clear_jobs"):
            st.session_state.slang_jobs = []
            st.session_state.slang_selected_job = None
            st.rerun()

    with right:
        st.markdown("#### 任务状态")
        job_ids = st.session_state.slang_jobs[:50]
        if not job_ids:
            st.markdown(T.empty("JOB", "暂无任务", "提交批量研判后，这里会显示每条任务的状态"), unsafe_allow_html=True)
            return

        jobs = _load_jobs(job_ids)
        if st.button("刷新任务状态", key="slang_refresh"):
            st.rerun()

        st.dataframe(_job_rows(jobs), width="stretch", hide_index=True)

        completed = [j for j in jobs if j.get("status") == "success"]
        if completed:
            labels = {
                f"任务 {j['job_id']} · 情报 {j.get('raw_id')}": j
                for j in completed
            }
            selected = st.selectbox("查看已完成结果", list(labels.keys()), key="slang_result_select")
            if selected:
                job = labels[selected]
                st.session_state.slang_selected_job = job.get("job_id")
                result = _load_result(job["raw_id"])
                _render_result(result)
