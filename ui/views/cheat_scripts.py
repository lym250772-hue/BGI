"""Attack Chain — abuse chain analysis grounded in real intelligence data."""

import streamlit as st
import json

import ui.theme as T

MODE_LABELS = ["从情报生成", "从案件生成", "自由探索"]


def _load_analyzed_intel(limit=50):
    try:
        from storage.mysql_store import mysql
        with mysql.cursor() as c:
            c.execute(
                """SELECT a.raw_id, a.risk_label, a.risk_sub_label, o.content_raw,
                          o.source_platform, o.author_name
                   FROM dwd_intel_analysis a
                   JOIN ods_raw_intel o ON a.raw_id = o.id
                   ORDER BY a.id DESC LIMIT %s""",
                (limit,),
            )
            return c.fetchall()
    except Exception:
        return []


def _load_cases(limit=20):
    try:
        from storage.mysql_store import mysql
        with mysql.cursor() as c:
            c.execute(
                "SELECT case_id, case_name, main_risk_type, risk_level, summary "
                "FROM ads_risk_case ORDER BY id DESC LIMIT %s",
                (limit,),
            )
            return c.fetchall()
    except Exception:
        return []


def _load_intel_entities(raw_id: int) -> list:
    try:
        from storage.mysql_store import mysql
        with mysql.cursor() as c:
            c.execute(
                "SELECT entity_type, entity_value FROM dwd_entity WHERE raw_id=%s",
                (raw_id,),
            )
            return c.fetchall()
    except Exception:
        return []


def _generate_from_intel(item: dict, entities: list) -> dict | None:
    from config.settings import settings
    if not settings.llm_api_key:
        return None

    entity_str = ", ".join(
        f"{e.get('entity_type', '')}:{e.get('entity_value', '')}" for e in entities[:15]
    )
    text = (item.get("content_raw") or "")[:500]

    prompt = f"""你是黑灰产情报分析专家。基于以下真实情报数据，分析该黑灰产的完整作恶链路。

情报原文: {text}

已提取实体: {entity_str}

风险分类: {item.get('risk_label', '未知')} / {item.get('risk_sub_label', '')}

仅返回JSON:
{{
  "title": "作恶链路标题",
  "risk_type": "风险类型",
  "abuse_chain": ["步骤1: 准备阶段...", "步骤2: ...", "步骤3: ...", "步骤4: ...", "步骤5: 变现阶段..."],
  "entities_involved": [{{"type": "wechat", "value": "xxx"}}],
  "tools_used": ["工具1"],
  "defense_suggestions": ["建议1", "建议2", "建议3"]
}}"""

    return _call_llm(prompt)


def _generate_from_case(case: dict) -> dict | None:
    from config.settings import settings
    if not settings.llm_api_key:
        return None

    prompt = f"""你是黑灰产情报分析专家。基于以下案件数据，生成团伙级别的作恶链路分析。

案件: {case.get('case_name', '')}
风险类型: {case.get('main_risk_type', '')}
风险等级: {case.get('risk_level', '')}
案件摘要: {case.get('summary', '')[:500]}

仅返回JSON:
{{
  "title": "案件作恶链路标题",
  "risk_type": "风险类型",
  "abuse_chain": ["步骤1: ...", "步骤2: ...", "..."],
  "entities_involved": [],
  "tools_used": [],
  "defense_suggestions": []
}}"""

    return _call_llm(prompt)


def _generate_free(kw: str) -> dict | None:
    from config.settings import settings
    if not settings.llm_api_key:
        return None

    prompt = f"""你是黑灰产情报分析专家。基于关键词生成作恶链路分析。

关键词：{kw}

仅返回JSON:
{{
  "title": "标题",
  "risk_type": "风险类型（诈骗/引流/作弊/账号黑产/内容违规/工具交易/直播违规）",
  "abuse_chain": ["步骤1: ...", "步骤2: ...", "步骤3: ..."],
  "tools_used": ["工具1"],
  "defense_suggestions": ["建议1", "建议2", "建议3"]
}}"""

    return _call_llm(prompt)


def _call_llm(prompt: str) -> dict | None:
    from config.settings import settings
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


def _render_result(result: dict, source_label: str = ""):
    st.markdown(f"### {result.get('title', '')}")

    risk = result.get("risk_type", "")
    risk_colors = {
        "诈骗": T.RED_CRIT, "引流": T.ORANGE_HI, "作弊": T.AMBER_MED,
        "账号黑产": T.ROSE_DARK, "内容违规": T.SAGE_DARK,
        "工具交易": T.GOLD, "直播违规": T.SLATE,
    }
    bg = risk_colors.get(risk, T.SLATE)
    st.markdown(
        f'<span style="background:{bg};color:white;padding:4px 14px;border-radius:20px;font-size:0.85rem;font-weight:500">{risk}</span>',
        unsafe_allow_html=True,
    )

    st.divider()

    # Abuse chain
    st.markdown("#### 作恶链路")
    chain = result.get("abuse_chain", [])
    if isinstance(chain, str):
        chain = [s.strip() for s in chain.split("\n") if s.strip()]
    for i, step in enumerate(chain, 1):
        arrow = "" if i == len(chain) else '<div style="text-align:center;font-size:1.2rem;color:#C4A35A;margin:0.1rem 0">&#8595;</div>'
        st.markdown(
            f"""<div style="display:flex;align-items:flex-start;gap:0.8rem;
            background:{T.BG_CARD};border:1px solid {T.BORDER};border-radius:6px;
            padding:0.55rem 0.8rem;margin-bottom:0.2rem">
            <div style="background:{T.ACCENT};color:white;min-width:26px;height:26px;
            border-radius:50%;display:flex;align-items:center;justify-content:center;
            font-size:0.76rem;font-weight:600;flex-shrink:0">{i}</div>
            <div style="color:{T.TEXT_MAIN};font-size:0.86rem">{step}</div></div>{arrow}""",
            unsafe_allow_html=True,
        )

    # Entities involved
    entities = result.get("entities_involved", [])
    if entities:
        st.markdown("#### 涉及实体")
        chips = ""
        for ent in entities:
            et = ent.get("type", "")
            ev = ent.get("value", "")
            chips += T.entity_chip(et, ev)
        st.markdown(f'<div style="line-height:2">{chips}</div>', unsafe_allow_html=True)

    # Tools
    tools = result.get("tools_used", [])
    if tools:
        st.markdown("#### 涉及工具")
        st.markdown(" ".join(
            f'<span style="background:{T.BG_SIDEBAR};color:{T.TEXT_SOFT};padding:3px 12px;border-radius:16px;font-size:0.8rem;margin-right:6px">{t}</span>'
            for t in tools
        ), unsafe_allow_html=True)

    # Defense
    st.markdown("#### 对抗建议")
    for sug in result.get("defense_suggestions", []):
        st.markdown(
            f"""<div class="evidence-highlight" style="border-left-color:{T.ACCENT}">
            <span style="font-size:0.84rem">{sug}</span></div>""",
            unsafe_allow_html=True,
        )

    if source_label:
        st.caption(f"数据来源: {source_label}")


def show():
    st.markdown("## 作恶链路")
    st.caption("基于真实情报数据，自动生成黑灰产滥用链路与对抗方案")

    mode = st.radio(
        "模式", MODE_LABELS, horizontal=True,
        label_visibility="collapsed", key="cheat_mode",
    )

    st.divider()

    # Mode 1: From Intel
    if mode == "从情报生成":
        intel_items = _load_analyzed_intel()
        if not intel_items:
            st.markdown(T.empty("📋", "暂无已分析情报", "先运行 python main.py analyze 分析数据"), unsafe_allow_html=True)
            return

        options = {
            f"#{it['raw_id']} [{it.get('risk_label', '?')}] {(it.get('content_raw') or '')[:45]}": it
            for it in intel_items
        }
        selected = st.selectbox("选择已分析情报", list(options.keys()), label_visibility="collapsed")
        item = options[selected]

        c1, c2 = st.columns([2, 1])
        with c1:
            if st.button("生成作恶链路", type="primary", key="gen_intel"):
                with st.spinner("分析中..."):
                    entities = _load_intel_entities(item["raw_id"])
                    result = _generate_from_intel(item, entities)
                    if result is None:
                        st.error("LLM API Key 未配置")
                    elif "error" in result:
                        st.error(f"生成失败: {result['error']}")
                    else:
                        st.divider()
                        _render_result(result, f"情报 #{item['raw_id']}")
        with c2:
            st.markdown(
                f"""<div class="intel-card">
                <div style="font-size:0.78rem;color:{T.TEXT_MUTED}">风险分类</div>
                <div style="font-weight:550">{item.get('risk_label', '?')} / {item.get('risk_sub_label', '')}</div>
                <div style="font-size:0.78rem;color:{T.TEXT_MUTED};margin-top:0.3rem">平台</div>
                <div>{item.get('source_platform', '?')}</div>
                </div>""",
                unsafe_allow_html=True,
            )

    # Mode 2: From Case
    elif mode == "从案件生成":
        cases = _load_cases()
        if not cases:
            st.markdown(T.empty("📁", "暂无案件数据", "当情报命中团伙关联时，自动创建案件"), unsafe_allow_html=True)
            return

        options = {
            f"{c['case_name']} [{c.get('main_risk_type', '?')}]": c
            for c in cases
        }
        selected = st.selectbox("选择案件", list(options.keys()), label_visibility="collapsed")
        case = options[selected]

        c1, c2 = st.columns([2, 1])
        with c1:
            if st.button("生成作恶链路", type="primary", key="gen_case"):
                with st.spinner("分析中..."):
                    result = _generate_from_case(case)
                    if result is None:
                        st.error("LLM API Key 未配置")
                    elif "error" in result:
                        st.error(f"生成失败: {result['error']}")
                    else:
                        st.divider()
                        _render_result(result, f"案件 {case.get('case_id', '')}")
        with c2:
            st.markdown(
                f"""<div class="intel-card">
                <div style="font-size:0.78rem;color:{T.TEXT_MUTED}">案件</div>
                <div style="font-weight:550">{case.get('case_name', '')}</div>
                <div style="margin-top:0.3rem">{T.badge(case.get('risk_level', 'normal'))}</div>
                <div style="font-size:0.8rem;margin-top:0.3rem">{case.get('summary', '')[:150]}</div>
                </div>""",
                unsafe_allow_html=True,
            )

    # Mode 3: Free exploration
    else:
        kw = st.text_input(
            "关键词",
            placeholder="输入黑灰产关键词，如：抖音无人直播刷量、刷单套利...",
            label_visibility="collapsed",
            key="cheat_kw",
        )
        if st.button("生成作恶链路", type="primary", key="gen_free") and kw:
            with st.spinner(f"分析「{kw}」中..."):
                result = _generate_free(kw)
                if result is None:
                    st.error("LLM API Key 未配置")
                elif "error" in result:
                    st.error(f"生成失败: {result['error']}")
                else:
                    st.divider()
                    _render_result(result)
        elif not kw:
            st.markdown(T.empty("📝", "输入关键词或切换到其他模式", "从情报/案件生成可获得更准确的结果"), unsafe_allow_html=True)
