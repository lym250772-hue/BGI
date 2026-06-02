from __future__ import annotations

import pandas as pd
import streamlit as st

import ui.labels as L
import ui.theme as T
from ui import data
from ui.components import page_header, raw_status_badge, risk_badge, service_strip


QUICK_QUESTIONS = [
    "当前风险类型分布怎么样？",
    "哪个平台高危情报最多？",
    "最近 30 天热门黑话有哪些？",
    "给我 10 条高危典型样本。",
    "当前待研判队列还有多少？",
]


def _recent_table(rows: list[dict]) -> pd.DataFrame:
    return pd.DataFrame([
        {
            "情报ID": r.get("id"),
            "来源": r.get("source_platform") or "-",
            "内容摘要": r.get("content_preview") or "",
            "处理状态": L.raw_status_label(r.get("raw_status")),
            "风险类型": r.get("risk_label") or "未分类",
            "风险等级": L.risk_level_label(r.get("risk_level") or ""),
            "接收时间": str(r.get("collect_time") or "")[:19],
        }
        for r in rows
    ])


def _render_chatbi_result(result: dict):
    rows = result.get("rows") or []
    st.markdown(
        f"""
        <div class='bagi-panel' style='margin-top:0.8rem'>
          <div style='display:flex;justify-content:space-between;gap:12px;align-items:center'>
            <div>
              <div class='section-title'>{result.get('intent', '态势问答')}</div>
              <div style='font-size:0.94rem;line-height:1.65;color:{T.TEXT}'>{result.get('answer', '')}</div>
            </div>
            {T.badge(result.get('source', '规则'), T.ACCENT)}
          </div>
        </div>
        """,
        unsafe_allow_html=True,
    )
    if not rows:
        st.info("没有查询到明细数据。")
        return

    df = pd.DataFrame(rows)
    chart = result.get("chart")
    x_col = result.get("x")
    y_col = result.get("y")

    if chart in ("bar", "line") and x_col in df.columns and y_col in df.columns:
        chart_df = df[[x_col, y_col]].copy()
        chart_df[y_col] = pd.to_numeric(chart_df[y_col], errors="coerce").fillna(0)
        if chart == "line":
            st.line_chart(chart_df.set_index(x_col), width="stretch")
    else:
        st.bar_chart(chart_df.set_index(x_col), width="stretch")

    st.dataframe(df, hide_index=True, width="stretch")


def _chatbi_panel():
    st.markdown("### ChatBI 态势问答")

    cols = st.columns(len(QUICK_QUESTIONS))
    for idx, prompt in enumerate(QUICK_QUESTIONS):
        if cols[idx].button(prompt, key=f"chatbi_quick_{idx}", width="stretch"):
            st.session_state.chatbi_question = prompt
            st.session_state.chatbi_result = data.chatbi_answer(prompt)
            st.rerun()

    question = st.text_input(
        "输入问题",
        key="chatbi_question",
        placeholder="例如：上周贴吧哪个风险分类最活跃？主要涉及什么黑话？",
    )
    ask_left, ask_right = st.columns([0.8, 4])
    with ask_left:
        ask = st.button("查询", type="primary", width="stretch", key="chatbi_ask")

    if ask:
        st.session_state.chatbi_result = data.chatbi_answer(question)

    result = st.session_state.get("chatbi_result")
    if result:
        _render_chatbi_result(result)


def show():
    page_header(
        "Command Center",
        "BGI 情报研判控制台",
        "面向比赛演示的主控台：连接状态、处理队列、风险态势、ChatBI 问答集中在一屏。",
    )

    stats = data.overview_stats()
    c1, c2, c3, c4, c5, c6 = st.columns(6)
    c1.metric("接收总量", stats["total_raw"])
    c2.metric("待研判", stats["pending"])
    c3.metric("研判中", stats["running"])
    c4.metric("已研判", stats["analyzed"])
    c5.metric("高危情报", stats["high_risk"])
    c6.metric("候选黑话", stats["slang_candidates"])

    left, right = st.columns([1.25, 1])
    with left:
        st.markdown("### 风险类型分布")
        risk_rows = data.risk_distribution()
        if risk_rows:
            df = pd.DataFrame(risk_rows)
            st.bar_chart(df.set_index("risk_label"), width="stretch")
        else:
            st.info("暂无已研判风险分布。")

        st.markdown("### 近 7 日研判趋势")
        trend = data.daily_trend(days=7)
        if trend:
            df = pd.DataFrame(trend)
            df["dt"] = pd.to_datetime(df["dt"])
            st.line_chart(df.set_index("dt")[["cnt", "high_cnt"]], width="stretch")
        else:
            st.info("暂无近 7 日趋势数据；这通常表示样本时间不在最近 7 天内。")

    with right:
        st.markdown("### 处理状态")
        status_counts = stats["status_counts"]
        if status_counts:
            for raw_status, count in status_counts.items():
                st.markdown(
                    f"""
                    <div class='bagi-panel-tight' style='margin-bottom:8px'>
                      <div style='display:flex;justify-content:space-between;align-items:center'>
                        {raw_status_badge(raw_status)}
                        <strong class='mono'>{count}</strong>
                      </div>
                    </div>
                    """,
                    unsafe_allow_html=True,
                )
        else:
            st.info("暂无状态数据。")

        st.markdown("### 来源平台")
        platform_rows = data.platform_distribution()
        if platform_rows:
            st.dataframe(
                pd.DataFrame(platform_rows).rename(columns={"platform": "平台", "cnt": "数量"}),
                hide_index=True,
                width="stretch",
            )
        else:
            st.info("暂无来源平台数据。")

    st.divider()

    st.markdown("### 近期情报")
    recent = data.list_intel(limit=12)
    if recent:
        st.dataframe(_recent_table(recent), hide_index=True, width="stretch")
        top = recent[0]
        st.markdown(
            f"""
            <div class='intel-card' style='margin-top:0.8rem'>
              <div style='display:flex;gap:8px;align-items:center;margin-bottom:6px'>
                {raw_status_badge(top.get('raw_status'))}
                {risk_badge(top.get('risk_level'))}
                <span class='mono' style='color:{T.MUTED}'>#{top.get('id')}</span>
              </div>
              <div style='font-size:0.92rem;color:{T.TEXT}'>{top.get('content_preview') or ''}</div>
            </div>
            """,
            unsafe_allow_html=True,
        )
    else:
        st.info("暂无情报数据。")

    st.divider()
    _chatbi_panel()

    st.divider()
    st.markdown("### 连接状态")
    service_strip(compact=True)
