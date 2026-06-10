from __future__ import annotations

import pandas as pd
import streamlit as st

import ui.labels as L
import ui.theme as T
from ui import data
from ui.components import empty_panel, page_header


STATUS_OPTIONS = {
    "全部": None,
    "已清洗待研判": "CLEANED",
    "待复核/待升级": "SCREENED",
    "已研判": "ANALYZED",
    "研判失败": "FAILED",
    "已丢弃": "DISCARDED",
}

DECISION_OPTIONS = {
    "全部": None,
    "低风险归档": "LOW_RISK_ARCHIVED",
    "建议标准研判": "NEED_STANDARD_ANALYSIS",
    "建议扩线研判": "NEED_GRAPH_ANALYSIS",
    "待人工复核": "SCREENED_REVIEW",
}


def _table(rows: list[dict]) -> pd.DataFrame:
    return pd.DataFrame([
        {
            "情报ID": r.get("id"),
            "来源": r.get("source_platform") or "-",
            "频道": r.get("source_channel") or "-",
            "作者": r.get("author_name") or "-",
            "内容摘要": r.get("content_preview") or "",
            "处理状态": L.intel_status_label(r.get("raw_status"), r.get("screen_decision")),
            "风险": (r.get("risk_label") or "未分类")
            + (f" / {r.get('risk_sub_label')}" if r.get("risk_sub_label") else ""),
            "风险分": (
                f"{float(r.get('risk_score') or 0):.2f}"
                if r.get("risk_score") is not None else "-"
            ),
            "初筛结论": L.screen_decision_label(r.get("screen_decision") or ""),
            "判定方式": L.classification_method_label(r.get("classification_method") or ""),
            "接收时间": str(r.get("collect_time") or "")[:19],
        }
        for r in rows
    ])


def _jobs_table(rows: list[dict]) -> pd.DataFrame:
    return pd.DataFrame([
        {
            "情报ID": j.get("raw_id"),
            "原始文本": (j.get("input_text") or "")[:100],
            "状态": L.job_status_label(j.get("status")),
            "进度": f"{j.get('progress') or 0}%",
            "当前步骤": L.job_step_label(j.get("current_step")),
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
        st.markdown("### 情报池")

    c1, c2, c3, c4, c5 = st.columns([1, 1, 1, 1.6, 0.8])
    with c1:
        status_label = st.selectbox("处理状态", list(STATUS_OPTIONS.keys()), key="pool_status")
    with c2:
        decision_label = st.selectbox("初筛结论", list(DECISION_OPTIONS.keys()), key="pool_decision")
    with c3:
        limit = st.number_input("读取数量", min_value=20, max_value=1000, value=300, step=20)
    with c4:
        keyword = st.text_input("搜索", placeholder="内容、作者或频道", key="pool_keyword")
    with c5:
        batch_size = st.number_input("批量数", min_value=1, max_value=50, value=10, step=1)

    rows = data.list_intel(
        status=STATUS_OPTIONS[status_label],
        keyword=keyword,
        limit=int(limit),
        screen_decision=DECISION_OPTIONS[decision_label],
    )
    eligible = [r for r in rows if r.get("raw_status") == "CLEANED"]
    pending_clean = [r for r in rows if r.get("raw_status") == "RAW_COLLECTED"]
    cleaned_ready = [r for r in rows if r.get("raw_status") == "CLEANED"]
    screened = [r for r in rows if r.get("raw_status") == "SCREENED"]
    review_ready = [
        r for r in rows
        if r.get("raw_status") == "SCREENED"
        and r.get("screen_decision") == "SCREENED_REVIEW"
    ]

    # ── 统计指标 ──
    b1, b2, b3, b4, b5 = st.columns([1, 1, 1, 1, 1])
    b1.metric("当前结果", len(rows))
    b2.metric("待清洗", len(pending_clean),
              delta=None if not pending_clean else f"{len(pending_clean)}条需处理")
    b3.metric("待初筛", len(cleaned_ready))
    b4.metric("待复核/升级", len(screened))
    b5.metric("待人工复核", len(review_ready))

    if review_ready:
        st.info(
            f"当前筛选结果中有 {len(review_ready)} 条需要人工复核。"
            "可在“初筛结论”中选择“待人工复核”查看。"
        )

    # ── 一键清洗按钮 ──
    if pending_clean:
        clean_col, _ = st.columns([1, 3])
        with clean_col:
            if st.button(
                "一键清洗",
                type="primary",
                disabled=not pending_clean,
                use_container_width=True,
                key="pool_clean_btn",
                help=f"对当前筛选结果中 {len(pending_clean)} 条待清洗数据执行清洗管道",
            ):
                raw_ids = [int(r["id"]) for r in pending_clean]
                with st.spinner(f"正在清洗 {len(raw_ids)} 条数据..."):
                    result = data.run_cleaning(raw_ids)
                st.session_state["pool_clean_result"] = result
                st.rerun()

        # 显示清洗结果
        if st.session_state.get("pool_clean_result"):
            cr = st.session_state["pool_clean_result"]
            rc1, rc2, rc3 = st.columns(3)
            rc1.metric("已处理", cr["total"])
            rc2.metric("保留", cr["cleaned"], delta=f"{cr['cleaned']}条通过清洗")
            rc3.metric("丢弃", cr["discarded"],
                      delta=f"{cr['discarded']}条噪声/重复" if cr["discarded"] else None)

            # 展示清洗详情
            if cr.get("details"):
                with st.expander(f"清洗详情（{len(cr['details'])} 条）", expanded=False):
                    for d in cr["details"]:
                        icon = "✅" if d["status"] == "CLEANED" else "🗑️"
                        dup_mark = " [重复]" if d.get("is_duplicate") else ""
                        st.markdown(
                            f"""
                            <div style='margin-bottom:8px;padding:8px;border-radius:6px;
                                        background:{'#F3FAF5' if d['status']=='CLEANED' else '#FDF4F4'};
                                        border-left:3px solid {'#26735D' if d['status']=='CLEANED' else '#B83A3A'}'>
                              <div style='font-size:0.8rem;margin-bottom:4px'>
                                {icon} <strong>#{d['id']}</strong> [{d['platform']}]{dup_mark}
                                <span style='color:{T.MUTED}'> — {L.cleaning_status_label(d['status'])}</span>
                                <span style='color:{T.MUTED};float:right'>噪声分: {d['noise_score']:.2f}</span>
                              </div>
                              <div style='font-size:0.7rem;color:{T.MUTED};margin-bottom:4px'>
                                原因: {d.get('noise_reason') or '无'}
                              </div>
                              <div style='font-size:0.68rem;display:flex;gap:10px'>
                                <span style='flex:1;color:{T.AMBER}'>原始: {(d.get('original') or '')[:80]}{'...' if len(d.get('original') or '') > 80 else ''}</span>
                              </div>
                              <div style='font-size:0.68rem;margin-top:2px'>
                                <span style='flex:1;color:{T.GREEN}'>清洗: {(d.get('text') or '')[:80]}{'...' if len(d.get('text') or '') > 80 else ''}</span>
                              </div>
                            </div>
                            """,
                            unsafe_allow_html=True,
                        )
            if cr.get("errors"):
                for err in cr["errors"]:
                    st.warning(err)

            # 清除结果按钮
            if st.button("清除清洗记录", key="pool_clear_result"):
                del st.session_state["pool_clean_result"]
                st.rerun()

    # ── 待处理操作区：SCREENED 情报按初筛结论分组，一键执行 ──────
    if screened:
        st.markdown("---")
        st.markdown("### 待处理操作区")

        need_standard = [r for r in screened if r.get("screen_decision") == "NEED_STANDARD_ANALYSIS"]
        need_graph = [r for r in screened if r.get("screen_decision") == "NEED_GRAPH_ANALYSIS"]
        need_review = [r for r in screened if r.get("screen_decision") == "SCREENED_REVIEW"]
        confirmed = [r for r in screened if r.get("screen_decision") == "CONFIRMED_RISK"]
        low_risk = [r for r in screened if r.get("screen_decision") == "LOW_RISK_ARCHIVED"]

        groups = []
        if need_standard:
            groups.append(("建议标准研判", need_standard, "standard", T.BLUE,
                           "规则命中风险线索但证据不足，需要 LLM/NLP 协同深度研判。"))
        if need_graph:
            groups.append(("建议扩线研判", need_graph, "graph", T.PURPLE,
                           "命中可扩线实体（账号/手机号/链接），建议启用向量检索与图谱扩展。"))
        if need_review:
            groups.append(("待人工复核", need_review, "review", T.AMBER,
                           "初筛无法自动判定，需要人工查看原始内容后决定处理方式。"))
        if confirmed:
            groups.append(("已确认风险", confirmed, "confirmed", T.RED,
                           "高置信规则命中，可视为已确认风险案件。"))
        if low_risk:
            groups.append(("低风险归档", low_risk, "archived", T.MUTED,
                           "风险分低于阈值且无关键线索，已自动归档，无需操作。"))

        if groups:
            cols = st.columns(len(groups))
            for col, (title, items, kind, color, desc) in zip(cols, groups):
                with col:
                    st.markdown(
                        f"""
                        <div class='bagi-panel-tight' style='text-align:center;margin-bottom:0.5rem'>
                          <div style='font-size:0.72rem;font-weight:700;color:{color};margin-bottom:0.3rem;
                                      text-transform:uppercase;letter-spacing:0.04em'>{title}</div>
                          <div style='font-size:2rem;font-weight:800;color:{T.INK};line-height:1.1'>{len(items)}</div>
                          <div class='section-note' style='margin-top:0.2rem'>{desc}</div>
                        </div>
                        """,
                        unsafe_allow_html=True,
                    )

                    if kind == "standard":
                        if st.button(
                            "提交标准研判",
                            type="primary",
                            key=f"pool_action_standard",
                            use_container_width=True,
                        ):
                            job_ids = data.submit_batch_jobs(
                                need_standard,
                                options={
                                    "enable_llm": True,
                                    "enable_roberta": True,
                                    "enable_embedding": False,
                                    "enable_graph_expand": False,
                                    "enable_report": False,
                                    "analysis_mode": "情报池升级标准研判",
                                    "auto_escalate": False,
                                },
                                max_items=len(need_standard),
                            )
                            st.success(f"已提交 {len(job_ids)} 条标准研判任务")
                            st.rerun()

                    elif kind == "graph":
                        if st.button(
                            "提交扩线研判",
                            type="primary",
                            key=f"pool_action_graph",
                            use_container_width=True,
                        ):
                            job_ids = data.submit_batch_jobs(
                                need_graph,
                                options={
                                    "enable_llm": True,
                                    "enable_roberta": True,
                                    "enable_embedding": True,
                                    "enable_graph_expand": True,
                                    "enable_report": False,
                                    "analysis_mode": "情报池升级扩线研判",
                                    "auto_escalate": False,
                                },
                                max_items=len(need_graph),
                            )
                            st.success(f"已提交 {len(job_ids)} 条扩线研判任务")
                            st.rerun()

                    elif kind == "review":
                        if st.button(
                            "前往研判工作台",
                            type="secondary",
                            key=f"pool_action_review",
                            use_container_width=True,
                        ):
                            st.session_state.nav_page = "workbench"
                            try:
                                st.query_params["page"] = "workbench"
                            except Exception:
                                pass
                            st.rerun()

                    # confirmed and archived — no action needed
                    if kind in ("confirmed", "archived"):
                        st.caption("无需操作")

    # ── 批量处理按钮（仅已清洗数据可提交）──
    st.markdown("---")
    submit_disabled = not eligible
    if st.button(
        "批量处理",
        type="primary" if cleaned_ready else "secondary",
        disabled=submit_disabled,
        use_container_width=True,
        key="pool_submit_btn",
        help="将已清洗数据送入智能分层管道：先快速初筛，根据结果自动归档或升级。完成后会出现在上方的待处理操作区。",
    ):
        job_ids = data.submit_batch_jobs(
            eligible,
            options={
                "enable_llm": False,
                "enable_roberta": False,
                "enable_embedding": False,
                "enable_graph_expand": False,
                "enable_report": False,
                "analysis_mode": "批量分层处理",
                "auto_escalate": True,
                "low_risk_threshold": 0.2,
                "standard_threshold": 0.45,
                "graph_threshold": 0.55,
                "confirm_threshold": 0.72,
            },
            max_items=int(batch_size),
        )
        st.session_state.pool_last_jobs = job_ids
        st.success(
            f"已提交 {len(job_ids)} 条已清洗情报进入批量处理；系统会先初筛，再按条件自动结束、标准研判或扩线研判。"
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

    _jobs_panel()


def show():
    render_pool(include_header=True)


@st.fragment(run_every="3s")
def _jobs_panel():
    st.markdown("### 后台任务")
    jobs = data.list_jobs(limit=12)
    if jobs:
        st.dataframe(_jobs_table(jobs), hide_index=True, use_container_width=True)
    else:
        st.info("暂无后台任务。")
