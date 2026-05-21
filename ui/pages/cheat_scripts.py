"""Cheat script generation page — LLM-powered cheat script generation."""

import streamlit as st

from ui.theme import empty_state


def _generate(keyword: str) -> dict | None:
    """Call LLM to generate a cheat script."""
    from config.settings import settings
    if not settings.llm_api_key:
        return None

    prompt = f"""你是黑灰产情报分析专家。请基于关键词生成一份作弊剧本分析报告。

关键词：{keyword}

请按以下JSON格式返回：
{{
  "title": "剧本标题",
  "risk_type": "风险类型（诈骗/引流/作弊/账号黑产/内容违规/工具交易/直播违规）",
  "abuse_chain": "完整的滥用链路描述，3-5个步骤",
  "tools_used": ["工具1", "工具2"],
  "defense_suggestions": ["对抗建议1", "对抗建议2", "对抗建议3"],
  "related_keywords": ["关联关键词1", "关联关键词2"]
}}"""

    try:
        from openai import OpenAI
        client = OpenAI(api_key=settings.llm_api_key, base_url=settings.llm_api_base)
        resp = client.chat.completions.create(
            model=settings.llm_model,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.3,
            max_tokens=800,
        )
        import json
        return json.loads(resp.choices[0].message.content)
    except Exception as exc:
        return {"error": str(exc)}


def show():
    st.markdown("## 作弊剧本生成")
    st.caption("基于 LLM 自动生成黑灰产作弊链路分析与对抗方案")

    # Input area
    c1, c2 = st.columns([3, 1])
    with c1:
        keyword = st.text_input(
            "分析关键词",
            placeholder="输入风险关键词，如：抖音直播刷量、刷单套利、账号买卖…",
            label_visibility="collapsed",
        )
    with c2:
        generate_btn = st.button("生成作弊剧本", type="primary", use_container_width=True)

    st.divider()

    if not generate_btn:
        # Show examples
        st.markdown("#### 示例关键词")
        examples = ["抖音无人直播刷量", "刷单返利诈骗", "微信账号买卖", "薅羊毛众包"]
        cols = st.columns(4)
        for i, ex in enumerate(examples):
            with cols[i]:
                st.button(ex, key=f"ex_{i}", use_container_width=True)

        st.markdown(
            empty_state("📝", "输入关键词生成作弊剧本", "LLM 将自动分析对应的黑灰产链路并生成对抗方案"),
            unsafe_allow_html=True,
        )
        return

    if not keyword:
        st.warning("请输入分析关键词")
        return

    with st.spinner(f"正在分析「{keyword}」..."):
        result = _generate(keyword)

    if result is None:
        st.error("LLM API Key 未配置，请在 .env 中设置 BGI_LLM_API_KEY")
        return

    if "error" in result:
        st.error(f"生成失败: {result['error']}")
        return

    # Display result
    st.markdown(f"### {result.get('title', keyword)}")

    # Risk type badge
    risk = result.get("risk_type", "")
    st.markdown(
        f"""<span style="background:#C4A8A3;color:white;padding:4px 14px;
        border-radius:20px;font-size:0.85rem;font-weight:500">{risk}</span>""",
        unsafe_allow_html=True,
    )

    st.divider()

    # Abuse chain
    st.markdown("#### 滥用链路")
    chain = result.get("abuse_chain", "")
    steps = [s.strip() for s in chain.split("\n") if s.strip()]
    if not steps:
        steps = [chain]
    for i, step in enumerate(steps, 1):
        st.markdown(
            f"""<div style="display:flex;align-items:flex-start;gap:1rem;
            background:#FDFBF9;border:1px solid #D8D3CB;border-radius:8px;
            padding:0.8rem 1rem;margin-bottom:0.5rem">
            <div style="background:#8B9D83;color:white;width:28px;height:28px;
            border-radius:50%;display:flex;align-items:center;justify-content:center;
            font-size:0.8rem;font-weight:600;flex-shrink:0">{i}</div>
            <div style="color:#3D3929;font-size:0.9rem">{step}</div></div>""",
            unsafe_allow_html=True,
        )

    # Tools used
    tools = result.get("tools_used", [])
    if tools:
        st.markdown("#### 涉及工具")
        tags_html = " ".join(
            f'<span style="background:#EBE6DE;color:#6B6760;padding:3px 12px;'
            f'border-radius:16px;font-size:0.8rem;margin-right:6px">{t}</span>'
            for t in tools
        )
        st.markdown(tags_html, unsafe_allow_html=True)

    # Defense suggestions
    st.markdown("#### 对抗建议")
    suggestions = result.get("defense_suggestions", [])
    for sug in suggestions:
        st.markdown(
            f"""<div style="background:#FDFBF9;border-left:3px solid #7E8FA6;
            padding:0.6rem 1rem;margin-bottom:0.4rem;border-radius:0 6px 6px 0;
            color:#3D3929;font-size:0.9rem">🛡 {sug}</div>""",
            unsafe_allow_html=True,
        )

    # Related keywords
    related = result.get("related_keywords", [])
    if related:
        st.markdown("#### 关联关键词")
        tags_html = " ".join(
            f'<span style="background:#F5F1EC;color:#8E8A83;padding:2px 10px;'
            f'border-radius:12px;font-size:0.78rem;margin-right:4px">{k}</span>'
            for k in related
        )
        st.markdown(tags_html, unsafe_allow_html=True)
