"""Cheat script generation — LLM-powered abuse chain analysis."""

import streamlit as st
import json

import ui.theme as T

EXAMPLES = [
    "抖音无人直播刷量",
    "刷单返利诈骗",
    "微信账号买卖",
    "薅羊毛众包",
]


def _generate(kw: str) -> dict | None:
    from config.settings import settings
    if not kw or not settings.llm_api_key:
        return None

    prompt = f"""你是黑灰产情报分析专家。基于关键词生成作弊剧本分析报告。

关键词：{kw}

仅返回JSON：
{{
  "title": "标题",
  "risk_type": "风险类型（诈骗/引流/作弊/账号黑产/内容违规/工具交易/直播违规）",
  "abuse_chain": "完整滥用链路，3-5步",
  "tools_used": ["工具1"],
  "defense_suggestions": ["建议1", "建议2", "建议3"]
}}"""

    try:
        from openai import OpenAI
        client = OpenAI(api_key=settings.llm_api_key, base_url=settings.llm_api_base)
        resp = client.chat.completions.create(
            model=settings.llm_model, messages=[{"role": "user", "content": prompt}],
            temperature=0.3, max_tokens=800,
        )
        return json.loads(resp.choices[0].message.content)
    except Exception as exc:
        return {"error": str(exc)}


def _render_result(result: dict):
    st.markdown(f"### {result.get('title', '')}")

    risk = result.get("risk_type", "")
    risk_colors = {
        "诈骗": T.ROSE, "引流": T.GOLD, "作弊": T.SLATE,
        "账号黑产": T.ROSE_DARK, "内容违规": T.SAGE_DARK,
        "工具交易": "#9A8A7A", "直播违规": "#8A7A8A",
    }
    bg = risk_colors.get(risk, T.SLATE)
    st.markdown(
        f'<span style="background:{bg};color:white;padding:4px 14px;border-radius:20px;font-size:0.85rem;font-weight:500">{risk}</span>',
        unsafe_allow_html=True,
    )

    st.divider()

    st.markdown("#### 滥用链路")
    chain = result.get("abuse_chain", "")
    steps = [s.strip() for s in chain.split("\n") if s.strip()] or [chain]
    for i, step in enumerate(steps, 1):
        st.markdown(
            f"""<div style="display:flex;align-items:flex-start;gap:0.8rem;
            background:{T.BG_CARD};border:1px solid {T.BORDER};border-radius:8px;
            padding:0.65rem 0.9rem;margin-bottom:0.4rem">
            <div style="background:{T.SAGE};color:white;min-width:26px;height:26px;
            border-radius:50%;display:flex;align-items:center;justify-content:center;
            font-size:0.78rem;font-weight:600">{i}</div>
            <div style="color:{T.TEXT_MAIN};font-size:0.88rem">{step}</div></div>""",
            unsafe_allow_html=True,
        )

    tools = result.get("tools_used", [])
    if tools:
        st.markdown("#### 涉及工具")
        st.markdown(" ".join(
            f'<span style="background:{T.BG_SIDEBAR};color:{T.TEXT_SOFT};padding:3px 12px;border-radius:16px;font-size:0.8rem;margin-right:6px">{t}</span>'
            for t in tools
        ), unsafe_allow_html=True)

    st.markdown("#### 对抗建议")
    for sug in result.get("defense_suggestions", []):
        st.markdown(
            f"""<div style="background:{T.BG_CARD};border-left:3px solid {T.SLATE};
            padding:0.55rem 0.9rem;margin-bottom:0.35rem;border-radius:0 6px 6px 0;
            color:{T.TEXT_MAIN};font-size:0.88rem">🛡 {sug}</div>""",
            unsafe_allow_html=True,
        )


def show():
    st.markdown("## 作弊剧本生成")
    st.caption("基于 LLM 自动生成黑灰产滥用链路与对抗方案")

    # Example chips — clicking sets the keyword in session state
    st.markdown("#### 示例场景")
    ex_cols = st.columns(len(EXAMPLES))
    for i, ex in enumerate(EXAMPLES):
        with ex_cols[i]:
            if st.button(ex, key=f"ex_{ex}", width="stretch"):
                st.session_state.cheat_kw = ex
                st.rerun()

    st.divider()

    # Input row
    c1, c2 = st.columns([3, 1])
    with c1:
        kw = st.text_input(
            "关键词",
            value=st.session_state.get("cheat_kw", ""),
            placeholder="如：抖音直播刷量、刷单套利、账号买卖...",
            label_visibility="collapsed",
            key="cheat_kw",
        )
    with c2:
        go = st.button("生成剧本", type="primary", width="stretch", key="cheat_go")

    # Handle generate
    if go and kw:
        with st.spinner(f"分析「{kw}」中..."):
            result = _generate(kw)
        if result is None:
            st.error("LLM API Key 未配置，请在 .env 中设置 BGI_LLM_API_KEY")
        elif "error" in result:
            st.error(f"生成失败: {result['error']}")
        else:
            st.divider()
            _render_result(result)

    elif go and not kw:
        st.warning("请输入关键词")

    elif not go and not kw:
        st.markdown(T.empty("📝", "点击示例或输入关键词", "LLM 自动分析黑灰产链路并生成对抗方案"), unsafe_allow_html=True)
