"""Entity library page."""

from __future__ import annotations

import pandas as pd
import streamlit as st

import ui.labels as L
import ui.theme as T


def _load_entities() -> tuple[list[dict], int, list[dict]]:
    try:
        from storage.mysql_store import mysql
        with mysql.cursor() as c:
            c.execute("SELECT entity_type, COUNT(*) AS cnt FROM dwd_entity GROUP BY entity_type ORDER BY cnt DESC")
            stats = c.fetchall()
            c.execute("SELECT COUNT(*) AS total FROM dwd_entity")
            total = c.fetchone()["total"]
            c.execute("SELECT * FROM dwd_entity ORDER BY id DESC LIMIT 300")
            rows = c.fetchall()
        return stats, total, rows
    except Exception as exc:
        st.session_state.entity_page_error = str(exc)
        return [], 0, []


def _defang(entity_type: str, value: str) -> str:
    try:
        from analyzer.defanger import defang_text
        return defang_text(value) if entity_type in {"url", "ip", "domain", "email"} else value
    except Exception:
        return value


def _render_stats(stats: list[dict], total: int):
    if not stats:
        st.metric("线索总数", total)
        return
    chips = [
        f'<span style="display:inline-flex;align-items:center;background:{T.BG_CARD};'
        f'border:1px solid {T.BORDER};border-radius:18px;padding:5px 12px;'
        f'margin-right:8px;font-size:0.8rem;color:{T.TEXT_MAIN}">线索总数 <strong>{total}</strong></span>'
    ]
    for row in stats:
        label = L.entity_type_label(row["entity_type"])
        chips.append(
            f'<span style="display:inline-flex;align-items:center;background:{T.BG_CARD};'
            f'border:1px solid {T.BORDER};border-radius:18px;padding:5px 12px;'
            f'margin-right:8px;font-size:0.78rem;color:{T.TEXT_SOFT}">{label} {row["cnt"]}</span>'
        )
    st.markdown(f'<div style="margin:0.5rem 0 1rem">{"".join(chips)}</div>', unsafe_allow_html=True)


def _rows_to_df(rows: list[dict]) -> pd.DataFrame:
    return pd.DataFrame([
        {
            "线索ID": e.get("id"),
            "情报ID": e.get("raw_id"),
            "线索类型": L.entity_type_label(e.get("entity_type", "")),
            "线索值": _defang(e.get("entity_type", ""), str(e.get("entity_value", ""))),
            "抽取方式": L.extraction_method_label(e.get("extract_method") or e.get("extraction_method") or ""),
            "置信度": f"{float(e.get('confidence') or 0):.2f}",
            "上下文": _defang(e.get("entity_type", ""), (e.get("context") or "")[:80]),
            "首次发现": str(e.get("first_seen", ""))[:19],
        }
        for e in rows
    ])


def show():
    st.markdown("## 线索库")
    st.caption("展示从情报中抽取出的账号、联系方式、链接、黑话、工具等结构化线索。")

    stats, total, all_entities = _load_entities()
    if not all_entities:
        err = st.session_state.get("entity_page_error")
        if err:
            st.error("无法加载线索库，请确认 MySQL 已启动。")
            st.code(err, language="text")
        else:
            st.markdown(T.empty("ID", "暂无线索数据", "完成情报研判后，系统会自动沉淀结构化线索"), unsafe_allow_html=True)
        return

    _render_stats(stats, total)

    c1, c2 = st.columns([2.4, 1.2])
    with c1:
        keyword = st.text_input("搜索线索值或上下文", placeholder="输入微信号、域名、黑话或关键词...", key="entity_search")
    entity_types = sorted({e.get("entity_type", "") for e in all_entities})
    type_options = ["全部"] + [L.entity_type_label(t) for t in entity_types]
    label_to_type = {"全部": None, **{L.entity_type_label(t): t for t in entity_types}}
    with c2:
        selected_type_label = st.selectbox("线索类型", type_options, key="entity_type_filter")

    selected_type = label_to_type[selected_type_label]
    filtered = []
    for row in all_entities:
        if selected_type and row.get("entity_type") != selected_type:
            continue
        if keyword:
            haystack = f"{row.get('entity_value', '')} {row.get('context', '')}"
            if keyword.lower() not in haystack.lower():
                continue
        filtered.append(row)

    st.caption(f"共 {len(filtered)} 条线索")
    st.dataframe(_rows_to_df(filtered), width="stretch", hide_index=True)
