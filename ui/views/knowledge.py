from __future__ import annotations

import pandas as pd
import streamlit as st

import ui.labels as L
from ui import data
from ui.components import empty_panel, page_header


def _entities_tab():
    counts = data.entity_type_counts()
    if counts:
        stat_df = pd.DataFrame([
            {"线索类型": L.entity_type_label(r["entity_type"]), "数量": r["cnt"]}
            for r in counts
        ])
        st.dataframe(stat_df, hide_index=True, width="stretch")

    type_values = [r["entity_type"] for r in counts]
    label_to_type = {"全部": None, **{L.entity_type_label(t): t for t in type_values}}
    selected = st.selectbox("线索类型", list(label_to_type.keys()), key="entity_type_filter")
    rows = data.list_entities(limit=300, entity_type=label_to_type[selected])
    if not rows:
        empty_panel("暂无实体线索", "完成研判后，账号、联系方式、链接、工具和黑话会沉淀在这里。")
        return

    df = pd.DataFrame([
        {
            "类型": L.entity_type_label(r.get("entity_type")),
            "线索值": r.get("entity_value"),
            "归一值": r.get("normalized_value") or "-",
            "抽取方式": L.extraction_method_label(r.get("extract_method") or ""),
            "置信度": f"{float(r.get('confidence') or 0):.2f}",
            "情报ID": r.get("raw_id"),
            "发现时间": str(r.get("first_seen") or "")[:19],
        }
        for r in rows
    ])
    st.dataframe(df, hide_index=True, width="stretch")


def _slang_tab():
    tab_candidate, tab_active = st.tabs(["候选黑话", "正式词典"])

    with tab_candidate:
        rows = data.list_slang(status="candidate", limit=100)
        if not rows:
            empty_panel("暂无候选黑话", "当 LLM 或向量检索发现疑似新黑话时，会进入这里等待人工确认。")
        for idx, row in enumerate(rows):
            term = row.get("term") or ""
            meaning = row.get("suggested_meaning") or row.get("normalized_meaning") or ""
            category = row.get("risk_category") or ""
            with st.container(border=True):
                c1, c2 = st.columns([2.4, 1])
                with c1:
                    st.markdown(f"**{term}**")
                    st.caption(meaning or "暂无建议释义")
                    if row.get("candidate_evidence"):
                        st.write(row.get("candidate_evidence"))
                    if row.get("candidate_reason"):
                        st.caption(f"发现原因：{row.get('candidate_reason')}")
                with c2:
                    new_meaning = st.text_area("确认释义", value=meaning, key=f"slang_meaning_{idx}", height=90)
                    new_category = st.text_input("风险分类", value=category, key=f"slang_category_{idx}")
                    a, b = st.columns(2)
                    if a.button("加入词典", key=f"approve_{idx}", width="stretch"):
                        data.approve_slang(term, new_meaning, category=new_category)
                        st.success(f"已加入词典：{term}")
                        st.rerun()
                    if b.button("忽略", key=f"reject_{idx}", width="stretch"):
                        data.reject_slang(term, reason="人工忽略")
                        st.info(f"已忽略：{term}")
                        st.rerun()

    with tab_active:
        rows = data.list_slang(status="active", limit=300)
        if not rows:
            empty_panel("暂无正式黑话词典", "导入种子词典或审核候选黑话后会显示在这里。")
            return
        df = pd.DataFrame([
            {
                "黑话": r.get("term"),
                "标准释义": r.get("normalized_meaning"),
                "风险分类": r.get("risk_category") or "-",
                "来源": r.get("source") or "-",
                "置信度": f"{float(r.get('confidence') or 0):.2f}",
                "更新时间": str(r.get("updated_at") or "")[:19],
            }
            for r in rows
        ])
        st.dataframe(df, hide_index=True, width="stretch")


def _graph_tab():
    st.caption("关系扩线只作为线索研判工具，不再默认展示全量图。输入一个实体后查看 1-3 跳关联。")
    c1, c2, c3 = st.columns([1, 2, 0.8])
    with c1:
        entity_type = st.selectbox(
            "实体类型",
            ["wechat", "phone", "telegram", "qq", "url", "domain", "tool", "slang", "crypto_wallet"],
            format_func=L.entity_type_label,
        )
    with c2:
        value = st.text_input("实体值", placeholder="例如 douyin_pro888 / example.com / 跑分")
    with c3:
        depth = st.number_input("跳数", min_value=1, max_value=3, value=2)

    if st.button("查询关联关系", type="primary", disabled=not value, width="stretch"):
        rows = data.graph_neighbors(entity_type, value, depth=int(depth))
        st.session_state.graph_rows = rows

    rows = st.session_state.get("graph_rows", [])
    if rows:
        st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch")
    elif value:
        st.info("点击查询后会显示关联节点。")
    else:
        empty_panel("输入实体开始扩线", "建议从微信号、手机号、Telegram 账号、域名或工具名开始。")


def show():
    page_header(
        "Knowledge Base",
        "知识库",
        "实体线索、黑话词典与关系扩线集中管理；这里是研判结果沉淀后的资产层。",
    )
    tab_entities, tab_slang, tab_graph = st.tabs(["实体线索", "黑话词典", "关系扩线"])
    with tab_entities:
        _entities_tab()
    with tab_slang:
        _slang_tab()
    with tab_graph:
        _graph_tab()
