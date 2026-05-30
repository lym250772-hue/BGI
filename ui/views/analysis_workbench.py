"""Analysis Workbench — the hero page for one-click intelligence analysis.

Shows an auditable execution trace for every analysis step: decision,
tool, input/output, and evidence. This is process telemetry, not raw LLM
chain-of-thought.
"""

import streamlit as st
import pandas as pd
import time
from datetime import datetime

import ui.theme as T
import ui.labels as L


def _load_intel_list(limit=50):
    try:
        from storage.mysql_store import mysql
        with mysql.cursor() as c:
            c.execute(
                "SELECT id, source_platform, content_raw, author_name, collect_time, "
                "raw_status, metadata FROM ods_raw_intel ORDER BY id DESC LIMIT %s",
                (limit,),
            )
            st.session_state.pop("workbench_db_error", None)
            return c.fetchall()
    except Exception as exc:
        st.session_state.workbench_db_error = str(exc)
        return []


def _load_analysis(raw_id: int) -> dict | None:
    try:
        from storage.mysql_store import mysql
        with mysql.cursor() as c:
            c.execute(
                "SELECT * FROM dwd_intel_analysis WHERE raw_id=%s AND is_latest=1 ORDER BY id DESC LIMIT 1",
                (raw_id,),
            )
            return c.fetchone()
    except Exception:
        return None


def _load_cleaned_text(raw_id: int) -> str:
    """Get the best available text for analysis: merged_text > clean_text > content_raw."""
    try:
        from storage.mysql_store import mysql
        with mysql.cursor() as c:
            c.execute(
                "SELECT merged_text, clean_text FROM dwd_clean_intel WHERE raw_id=%s",
                (raw_id,),
            )
            clean = c.fetchone()
            if clean:
                return clean.get("merged_text") or clean.get("clean_text") or ""
            c.execute(
                "SELECT content_raw FROM ods_raw_intel WHERE id=%s",
                (raw_id,),
            )
            raw = c.fetchone()
            return raw.get("content_raw", "") if raw else ""
    except Exception:
        return ""


def _load_result_bundle(raw_id: int) -> dict:
    try:
        from storage.mysql_store import mysql
        return mysql.get_analysis_bundle(raw_id)
    except Exception:
        return {"raw_id": raw_id}


def _json_loads(val):
    """Safely parse a JSON value that may be str, list, or None."""
    import json as _json
    if val is None:
        return []
    if isinstance(val, (list, dict)):
        return val
    try:
        return _json.loads(val)
    except (TypeError, ValueError):
        return []


def _load_entities_for_raw(raw_id: int) -> list[dict]:
    """Load entities for a raw_id from dwd_entity."""
    try:
        from storage.mysql_store import mysql
        with mysql.cursor() as c:
            c.execute(
                "SELECT entity_type, entity_value, extract_method, confidence "
                "FROM dwd_entity WHERE raw_id=%s",
                (raw_id,),
            )
            return [dict(r) for r in c.fetchall()]
    except Exception:
        return []


def _submit_annotation(raw_id: int, annotator: str, field: str,
                       old_value: str, new_value: str, note: str):
    """Submit a HITL correction via the new feedback-loop API.

    Maps UI field names → target_type / field_name:
      - 风险分类 → target_type="classification", field_name=old_value (intent_label)
      - 实体     → target_type="entity"
      - 黑话释义 → target_type="slang"
      - 处置建议 → target_type="disposal_advice"
      - 其他     → target_type="other"
    """
    field_map = {
        "风险分类": ("classification", old_value),  # old_value IS the intent_label
        "实体": ("entity", field.lower()),
        "黑话释义": ("slang", old_value),
    }
    target_type, field_name = field_map.get(field, ("other", field))

    try:
        from storage.mysql_store import mysql
        result = mysql.log_annotation(
            target_type=target_type,
            target_id=raw_id,
            field_name=field_name,
            old_value=old_value,
            new_value=new_value,
            annotator=annotator,
            reason=note,
        )
        return result
    except Exception:
        return None


# ── Execution trace rendering ───────────────────────────────────────────────

def _approve_slang_candidate(term: str, meaning: str, category: str, reviewer: str = "analyst") -> bool:
    try:
        from storage.mysql_store import mysql
        return mysql.approve_slang_candidate(
            term=term,
            meaning=meaning,
            category=category,
            reviewer=reviewer,
        )
    except Exception:
        return False


def _reject_slang_candidate(term: str, reviewer: str = "analyst", reason: str = "") -> bool:
    try:
        from storage.mysql_store import mysql
        return mysql.reject_slang_candidate(term=term, reviewer=reviewer, reason=reason)
    except Exception:
        return False


def _entity_rows(entities: list[dict]) -> pd.DataFrame:
    rows = []
    for ent in entities:
        et = ent.get("entity_type", "")
        et_s = et.value if hasattr(et, "value") else str(et)
        method = ent.get("extraction_method", "")
        method_s = method.value if hasattr(method, "value") else str(method)
        rows.append({
            L.field_label("entity_type"): L.entity_type_label(et_s),
            L.field_label("entity_value"): ent.get("entity_value", "")[:80],
            L.field_label("extraction_method"): L.extraction_method_label(method_s),
            L.field_label("confidence"): f"{float(ent.get('confidence') or 0):.2f}",
        })
    return pd.DataFrame(rows)


def _slang_rows(slang_terms: list[dict]) -> pd.DataFrame:
    rows = []
    for slang in slang_terms:
        rows.append({
            L.field_label("term"): slang.get("term", ""),
            L.field_label("meaning"): slang.get("meaning", "") or "-",
            L.field_label("source"): L.extraction_method_label(str(slang.get("source", ""))),
        })
    return pd.DataFrame(rows)


_STEP_ICONS = {
    "classify": "🏷️",
    "extract_entities": "🔍",
    "decide_tools": "🧠",
    "extract_evidence": "📋",
    "risk_score": "⚖️",
    "generate_report": "📝",
    "persist": "💾",
    "done": "✅",
}

_STEP_LABELS = {
    "classify": "分类识别",
    "extract_entities": "实体抽取",
    "decide_tools": "Agent 自主决策",
    "extract_evidence": "证据提取",
    "risk_score": "风险评分",
    "generate_report": "处置建议",
    "persist": "结果持久化",
    "done": "研判完成",
}


_MODE_CONFIG = {
    "快速筛查": {
        "enable_llm": False,
        "enable_graph_expand": False,
        "enable_report": True,
        "desc": "规则 + 黑话词典 + 实体证据，适合批量快查。",
    },
    "关系扩线": {
        "enable_llm": False,
        "enable_graph_expand": True,
        "enable_report": True,
        "desc": "在快查基础上查询 Neo4j，判断是否命中历史团伙或共享线索。",
    },
    "深度复核": {
        "enable_llm": True,
        "enable_graph_expand": True,
        "enable_report": True,
        "desc": "规则不足时启用 LLM 兜底，速度较慢，适合少量疑难样本。",
    },
}


def _render_think_chain(steps: list[dict]):
    """Render the Agent's execution trace as a vertical timeline of step cards."""

    st.markdown("### Agent 研判轨迹")

    for i, step in enumerate(steps):
        step_name = step.get("step", "")
        status = step.get("status", "")
        thinking = step.get("thinking", "")
        result_summary = step.get("result_summary") or {}
        is_final = step.get("final", False)
        icon = _STEP_ICONS.get(step_name, "⚙️")
        label = _STEP_LABELS.get(step_name, step_name)

        # Status indicator
        if status == "running":
            status_badge = "🔄 执行中..."
            border_color = T.ACCENT
        elif is_final:
            status_badge = "✅ 完成"
            border_color = T.SAGE
        else:
            status_badge = "✅ 完成"
            border_color = T.SAGE

        # Build the card
        with st.container():
            st.markdown(
                f"""<div style="border-left:3px solid {border_color};
                padding:0.6rem 0.8rem;margin:0.4rem 0 0.8rem 0;
                background:{T.BG_CARD};border-radius:0 6px 6px 0;
                font-size:0.88rem">
                <div style="display:flex;align-items:center;gap:0.5rem;
                margin-bottom:0.4rem">
                <span style="font-size:1.1rem">{icon}</span>
                <span style="font-weight:600;color:{T.TEXT_MAIN}">{label}</span>
                <span style="font-size:0.72rem;color:{T.TEXT_MUTED};
                margin-left:auto">{status_badge}</span>
                </div>""",
                unsafe_allow_html=True,
            )

            # Thinking text (expandable for non-decision steps)
            if thinking:
                if step_name == "decide_tools":
                    # Decision step: always show
                    st.markdown(
                        f"""<div style="white-space:pre-wrap;font-size:0.8rem;
                        color:{T.TEXT_SOFT};line-height:1.5;padding:0.3rem 0 0 0.2rem;
                        font-family:'JetBrains Mono',monospace">{thinking}</div>""",
                        unsafe_allow_html=True,
                    )
                else:
                    with st.expander("查看判定依据", expanded=False):
                        st.markdown(
                            f"""<div style="white-space:pre-wrap;font-size:0.8rem;
                            color:{T.TEXT_SOFT};line-height:1.5;
                            font-family:'JetBrains Mono',monospace">{thinking}</div>""",
                            unsafe_allow_html=True,
                        )

            # Result summary table
            if result_summary:
                summary_rows = "\n".join(
                    f'<tr><td style="padding:2px 10px 2px 0;font-size:0.76rem;'
                    f'color:{T.TEXT_MUTED}">{k}</td>'
                    f'<td style="padding:2px 0;font-size:0.78rem;font-weight:500;'
                    f'color:{T.TEXT_MAIN}">{v}</td></tr>'
                    for k, v in result_summary.items()
                )
                st.markdown(
                    f"""<table style="margin:0.3rem 0 0 0.5rem">{summary_rows}</table>""",
                    unsafe_allow_html=True,
                )

            st.markdown("</div>", unsafe_allow_html=True)


# ── Final result display ───────────────────────────────────────────────────

def _render_final_result(result: dict, selected_item: dict):
    """Render the 3-column final result layout after analysis completes."""
    st.divider()
    st.markdown("### 最终研判结果")

    left, center, right = st.columns([1, 1.3, 1])

    # ═══ LEFT: Raw Intel ═══
    with left:
        st.markdown("##### 原始情报")
        meta = selected_item.get("metadata", "")
        if isinstance(meta, str) and meta:
            try:
                import json
                meta = json.loads(meta)
            except Exception:
                meta = {}
        group_id = meta.get("group_id", "") if isinstance(meta, dict) else ""

        st.markdown(
            f"""<div class="intel-card">
            <div style="display:flex;gap:1rem;margin-bottom:0.3rem;">
            <span style="color:{T.TEXT_MUTED};font-size:0.7rem">平台</span>
            <span style="font-weight:500;font-size:0.82rem">{selected_item.get('source_platform', '?')}</span>
            <span style="color:{T.TEXT_MUTED};font-size:0.7rem;margin-left:auto">作者</span>
            <span style="font-size:0.82rem">{selected_item.get('author_name', '-') or '-'}</span>
            </div>""",
            unsafe_allow_html=True,
        )
        if group_id:
            st.markdown(
                f'<div style="font-size:0.78rem;color:{T.TEXT_MUTED};margin-bottom:0.3rem">群组: {group_id}</div>',
                unsafe_allow_html=True,
            )
        st.markdown(
            f"""<div style="font-size:0.7rem;color:{T.TEXT_MUTED};margin-bottom:0.5rem">
            采集时间: {str(selected_item.get('collect_time', ''))[:19]}</div>
            <div style="background:{T.BG_BASE};padding:0.6rem 0.7rem;border-radius:4px;
            font-size:0.84rem;line-height:1.55;max-height:300px;overflow-y:auto;
            white-space:pre-wrap;word-break:break-word">{selected_item.get('content_raw', '')}</div>
            </div>""",
            unsafe_allow_html=True,
        )

    # ═══ CENTER: AI Analysis ═══
    with center:
        st.markdown("##### AI 研判")

        risk_label = result.get("risk_label", "?")
        risk_sub = result.get("risk_sub_label", "")
        risk_score_val = result.get("risk_score", 0)
        risk_level = result.get("risk_level", "normal")

        risk_text = risk_label
        if risk_sub:
            risk_text += f" / {risk_sub}"

        st.markdown(
            f"""<div class="intel-card" style="text-align:center">
            <div style="font-size:0.95rem;font-weight:600;margin-bottom:0.3rem">{risk_text}</div>
            {T.risk_score_html(risk_score_val)}
            <div style="margin-top:0.3rem">{T.badge(risk_level)}</div>
            </div>""",
            unsafe_allow_html=True,
        )

        evidence = result.get("evidence_spans", [])
        if evidence:
            st.markdown("**证据片段**")
            for ev in evidence[:5]:
                method = ev.get("method", "")
                risk_pt = ev.get("risk_point", "")
                text_snippet = ev.get("text", "")[:120]
                reason = ev.get("reason", "")[:120]
                st.markdown(
                    f"""<div class="evidence-highlight">
                    <div style="display:flex;gap:0.5rem;align-items:center;margin-bottom:0.2rem">
                    <span style="font-size:0.68rem;background:{T.ACCENT};color:white;padding:1px 8px;
                    border-radius:8px">{method}</span>
                    <span style="font-size:0.76rem;font-weight:550;color:{T.TEXT_MAIN}">{risk_pt}</span></div>
                    <div style="font-size:0.82rem;margin-bottom:0.15rem">「{text_snippet}」</div>
                    <div style="font-size:0.74rem;color:{T.TEXT_SOFT}">{reason}</div></div>""",
                    unsafe_allow_html=True,
                )

        entities = result.get("entities", [])
        if entities:
            st.markdown("**抽取实体**")
            rows = []
            for ent in entities[:20]:
                et = ent.get("entity_type", "")
                et_s = et.value if hasattr(et, "value") else str(et)
                rows.append({
                    "类型": et_s,
                    "值": ent.get("entity_value", "")[:60],
                    "方式": str(ent.get("extraction_method", ""))[:12],
                })
            st.dataframe(_entity_rows(entities[:20]), width="stretch", hide_index=True)

        slang = result.get("slang_terms", [])
        if slang:
            st.markdown("**黑话解释**")
            srows = []
            for sl in slang[:10]:
                srows.append({
                    "术语": sl.get("term", ""),
                    "释义": sl.get("meaning", "") or "-",
                })
            st.dataframe(_slang_rows(slang[:10]), width="stretch", hide_index=True)

        candidates = result.get("new_slang_candidates", []) or []
        if candidates:
            st.markdown("**疑似新黑话**")
            st.caption("模型发现这些词可能是新黑话，确认后会进入正式黑话词典。")
            for idx, item in enumerate(candidates[:5]):
                term = item.get("term", "")
                default_meaning = item.get("suggested_meaning", "") or "待人工确认"
                evidence = item.get("evidence", "") or "-"
                reason = item.get("reason", "") or "-"
                confidence = float(item.get("confidence") or 0)
                st.markdown(
                    f"""<div class="intel-card" style="border-left:3px solid {T.AMBER_MED}">
                    <div style="display:flex;align-items:center;gap:0.5rem;margin-bottom:0.25rem">
                    <span style="font-weight:650;color:{T.TEXT_MAIN}">{term}</span>
                    <span style="font-size:0.72rem;color:{T.TEXT_SOFT}">置信度 {confidence:.2f}</span>
                    </div>
                    <div style="font-size:0.78rem;color:{T.TEXT_MAIN};line-height:1.55">{default_meaning}</div>
                    <div style="font-size:0.72rem;color:{T.TEXT_SOFT};margin-top:0.25rem">证据：{evidence}</div>
                    <div style="font-size:0.72rem;color:{T.TEXT_SOFT};margin-top:0.15rem">原因：{reason}</div>
                    </div>""",
                    unsafe_allow_html=True,
                )
                meaning = st.text_input(
                    "确认释义",
                    value=default_meaning,
                    key=f"candidate_meaning_{result.get('raw_id')}_{idx}_{term}",
                )
                b1, b2 = st.columns(2)
                with b1:
                    if st.button("加入黑话词典", key=f"approve_candidate_{result.get('raw_id')}_{idx}_{term}"):
                        ok = _approve_slang_candidate(
                            term=term,
                            meaning=meaning,
                            category=item.get("risk_category", ""),
                        )
                        st.success("已加入正式黑话词典") if ok else st.warning("加入失败或候选词不存在")
                        st.rerun()
                with b2:
                    if st.button("忽略该候选", key=f"reject_candidate_{result.get('raw_id')}_{idx}_{term}"):
                        ok = _reject_slang_candidate(term=term, reason="人工忽略")
                        st.info("已忽略该候选") if ok else st.warning("忽略失败或候选词不存在")
                        st.rerun()

    # ═══ RIGHT: Disposal & Expansion ═══
    with right:
        st.markdown("##### 处置与扩线")

        graph = result.get("graph_result", {}) or {}
        if graph.get("is_gang_related"):
            st.markdown(
                f"""<div class="intel-card" style="border-left:3px solid {T.RED_CRIT}">
                <div style="font-weight:600;color:{T.RED_CRIT};margin-bottom:0.3rem">命中历史团伙</div>
                <div style="font-size:0.8rem">案件编号：{graph.get('case_id', '-')}</div>
                <div style="font-size:0.8rem">团伙簇编号：{graph.get('cluster_id', '-')}</div>
                </div>""",
                unsafe_allow_html=True,
            )
        elif graph:
            st.markdown(
                f"""<div class="intel-card">
                <div style="font-size:0.82rem;color:{T.TEXT_SOFT}">关联实体: {graph.get('related_entities_count', 0)}</div>
                <div style="font-size:0.82rem;color:{T.TEXT_SOFT}">共享联系人: {len(graph.get('shared_contacts', []))}</div>
                </div>""",
                unsafe_allow_html=True,
            )

        advice = result.get("disposal_advice", [])
        if advice:
            st.markdown("**处置建议**")
            for a in advice[:8]:
                prio = a.get("priority", "medium")
                color = {
                    "critical": T.RED_CRIT,
                    "high": T.ORANGE_HI,
                    "medium": T.AMBER_MED,
                    "low": T.SLATE_LO,
                }.get(prio, T.SLATE_LO)
                st.markdown(
                    f"""<div class="intel-card" style="border-left:3px solid {color}">
                    <div style="font-weight:550;font-size:0.82rem">{a.get('action', '?')}</div>
                    <div style="font-size:0.74rem;color:{T.TEXT_SOFT}">{a.get('detail', '')}</div>
                    </div>""",
                    unsafe_allow_html=True,
                )

    summary = result.get("agent_summary", "")
    if summary:
        st.markdown("#### 研判摘要")
        st.markdown(
            f"""<div class="intel-card" style="padding:0.8rem 1rem;margin-bottom:0.6rem">
            <div style="font-size:0.88rem;line-height:1.65">{summary}</div></div>""",
            unsafe_allow_html=True,
        )

    with st.expander("人工修正", expanded=False):
        st.markdown("对研判结果有异议？在此提交修正，系统会写入标注日志。")
        c1, c2 = st.columns(2)
        with c1:
            hitl_field = st.selectbox(
                "修正字段",
                ["风险分类", "实体", "黑话释义", "处置建议", "其他"],
                key="hitl_field",
            )
            hitl_old = st.text_input("原值", key="hitl_old")
        with c2:
            hitl_annotator = st.text_input("标注人", value="analyst", key="hitl_annotator")
            hitl_new = st.text_input("修正值", key="hitl_new")
        hitl_note = st.text_area("备注", key="hitl_note", height=80)
        if st.button("提交修正", key="hitl_submit"):
            result = _submit_annotation(
                raw_id=result.get("raw_id", st.session_state.get("wb_raw_id", 0)),
                annotator=hitl_annotator,
                field=hitl_field,
                old_value=hitl_old,
                new_value=hitl_new,
                note=hitl_note,
            )
            if result:
                synced = result.get("synced", False)
                if synced:
                    st.success(f"修正已提交并回流 (annotation #{result.get('annotation_id')})")
                else:
                    st.info(f"修正已记录 (annotation #{result.get('annotation_id')})，将在同步后回流")
            else:
                st.warning("提交失败，请检查数据库连接")


# ── Main show() ─────────────────────────────────────────────────────────────

def show():
    st.markdown("## 研判工作台")
    st.caption("先判断风险，再解释证据，最后给出处置和扩线结果。")

    # ── Top bar: select intel ──
    intel_items = _load_intel_list()
    if not intel_items:
        db_error = st.session_state.get("workbench_db_error")
        if db_error:
            st.error("数据库暂不可用，无法加载情报池。请先确认 MySQL 容器运行并监听 localhost:3306。")
            st.code(db_error, language="text")
            st.caption("提示：Doris 是分析增强组件，MySQL 是工作台必需组件；MySQL 未启动时无法研判新数据。")
            return
        st.markdown(
            T.empty("📋", "暂无情报数据", "运行 python scripts/demo/demo_one.py 导入示例数据"),
            unsafe_allow_html=True,
        )
        return

    options = {
        f"#{item['id']} [{item.get('source_platform', '?')}] {(item.get('content_raw', '') or '')[:50]}": item["id"]
        for item in intel_items
    }

    c_top1, c_top2, c_top3 = st.columns([2.8, 0.8, 0.8])
    with c_top1:
        selected_label = st.selectbox(
            "选择情报",
            list(options.keys()),
            label_visibility="collapsed",
            key="workbench_intel_select",
        )
    selected_id = options[selected_label]

    with c_top2:
        async_mode = st.checkbox("后台执行", value=True, key="cb_async_mode",
                                 help="异步提交任务，可关闭页面稍后查看结果")
    with c_top3:
        analyze_btn = st.button("一键研判", type="primary", width="stretch", key="btn_analyze")

    mode = st.radio(
        "研判模式",
        list(_MODE_CONFIG.keys()),
        index=0,
        horizontal=True,
        key="wb_mode",
        help="快速筛查用于大量数据；关系扩线用于查团伙；深度复核用于疑难样本。",
    )
    mode_cfg = _MODE_CONFIG[mode]
    st.caption(mode_cfg["desc"])

    selected_item = next((it for it in intel_items if it["id"] == selected_id), None)

    # ── State ──
    if "wb_result" not in st.session_state:
        st.session_state.wb_result = None
    if "wb_raw_id" not in st.session_state:
        st.session_state.wb_raw_id = None
    if "wb_show_report" not in st.session_state:
        st.session_state.wb_show_report = False
    if "wb_think_steps" not in st.session_state:
        st.session_state.wb_think_steps = None
    if "wb_job_id" not in st.session_state:
        st.session_state.wb_job_id = None

    # ── Async job polling — check and auto-refresh ──
    if st.session_state.wb_job_id and st.session_state.wb_result is None:
        from storage.mysql_store import mysql
        job = mysql.get_job(st.session_state.wb_job_id)
        if job:
            status = job.get("status", "pending")
            progress_val = job.get("progress", 0) or 0

            st.markdown("### 异步研判任务")
            cj1, cj2 = st.columns([3, 1])
            with cj1:
                st.markdown(f"**任务 ID**: `{st.session_state.wb_job_id}`")
                st.markdown(f"**状态**: {status} | **步骤**: {job.get('current_step', '—')}")
                st.progress(min(progress_val / 100, 1.0))
            with cj2:
                st.metric("进度", f"{progress_val}%")
                if st.button("手动刷新", key="btn_refresh_job"):
                    st.rerun()

            if status == "success":
                st.success("研判完成！")
                st.session_state.wb_job_id = None
                # Read result from MySQL directly — do NOT re-run engine
                raw_id = job.get("raw_id")
                if raw_id:
                    st.session_state.wb_result = _load_result_bundle(raw_id)
                    st.session_state.wb_raw_id = raw_id
                    st.session_state.wb_think_steps = None
                    st.session_state.wb_show_report = False
                time.sleep(0.5)
                st.rerun()
            elif status == "failed":
                st.error(f"研判失败: {job.get('error_message', '未知错误')}")
                st.session_state.wb_job_id = None
            else:
                st.caption("任务正在后台运行。你可以切换页面或继续提交其他任务，稍后点击刷新查看结果。")
        else:
            st.warning("任务不存在或已过期")
            st.session_state.wb_job_id = None

    # ── Run analysis — async or sync ──
    if analyze_btn and selected_item:
        raw_id = selected_item["id"]
        text = _load_cleaned_text(raw_id) or selected_item.get("content_raw", "") or ""
        platform = selected_item.get("source_platform", "unknown")
        options = {
            "enable_llm": mode_cfg["enable_llm"],
            "enable_graph_expand": mode_cfg["enable_graph_expand"],
            "enable_report": mode_cfg["enable_report"],
            "analysis_mode": mode,
        }

        if async_mode:
            # Async: submit to worker pool, poll via st.rerun
            from storage.mysql_store import mysql
            from analyzer.worker import submit_analysis
            job_id = mysql.create_job(raw_id, text, platform, options=options)
            submit_analysis(job_id, raw_id, text, platform, options=options)
            st.session_state.wb_job_id = job_id
            st.session_state.wb_result = None
            st.session_state.wb_think_steps = None
            st.rerun()
        else:
            # Sync: live execution trace (current flow)
            steps = []
            final_result = None

            with st.spinner("Agent 正在分析..."):
                try:
                    from analyzer.engine import engine
                    if not mode_cfg["enable_llm"]:
                        engine.set_circuit_open(True)
                    try:
                        for step in engine.run_stream(
                            raw_data_id=raw_id,
                            text=text,
                            platform=platform,
                            enable_graph_expand=mode_cfg["enable_graph_expand"],
                            enable_report=mode_cfg["enable_report"],
                        ):
                            steps.append(step)
                            if step.get("final"):
                                final_result = step.get("result")
                                break
                    finally:
                        if not mode_cfg["enable_llm"]:
                            engine.reset_circuit()

                    st.session_state.wb_result = final_result
                    st.session_state.wb_raw_id = raw_id
                    st.session_state.wb_show_report = False
                    st.session_state.wb_think_steps = steps
                    st.session_state.wb_job_id = None
                except Exception as exc:
                    st.error(f"研判失败: {exc}")
                    st.session_state.wb_result = None
                    st.session_state.wb_think_steps = None

    result = st.session_state.wb_result
    steps = st.session_state.wb_think_steps

    # ── Show execution trace OR prompt ──
    if steps and result:
        _render_think_chain(steps)
        _render_final_result(result, selected_item)
    elif result and selected_item:
        _render_final_result(result, selected_item)
    elif result is None and selected_item and not st.session_state.wb_job_id:
        existing = _load_analysis(selected_item["id"])
        if existing:
            st.info(f"该情报已有分析记录（判定方式：{L.classification_method_label(existing.get('classification_method', 'unknown'))}），点击「一键研判」重新分析")
            _render_final_result(_load_result_bundle(selected_item["id"]), selected_item)
        else:
            st.markdown(
                T.empty("🔍", "点击「一键研判」开始分析", "Agent 将逐步展示执行轨迹，包括分类、实体抽取、自主决策、证据提取、风险评分等"),
                unsafe_allow_html=True,
            )
