"""Entity library — browse extracted entities by type."""

import streamlit as st
import pandas as pd

import ui.theme as T


def show():
    st.markdown("## 实体库")
    st.caption("提取的实体：账号、链接、黑话、工具等")

    try:
        from storage.mysql_store import mysql
        with mysql.cursor() as c:
            c.execute("SELECT entity_type, COUNT(*) as cnt FROM entities GROUP BY entity_type ORDER BY cnt DESC")
            stats = c.fetchall()
            c.execute("SELECT COUNT(*) as total FROM entities")
            total = c.fetchone()["total"]
            c.execute("SELECT * FROM entities ORDER BY id DESC LIMIT 200")
            all_ents = c.fetchall()
    except Exception:
        stats, total, all_ents = [], 0, []

    # Entity type colors
    type_colors = {
        "phone": T.SLATE, "wechat": T.ROSE, "qq": "#A0ACBA",
        "url": "#B0A0B0", "domain": "#9AAFA0", "ip": "#B0A898",
        "bank_card": "#A5B0A0", "alipay": "#ACA8B0",
        "slang": "#A0AAB0", "tool": "#B0A8A0", "feature": "#9EA8B0",
    }

    # Summary chips
    if stats:
        chips = f'<span style="display:inline-flex;align-items:center;gap:6px;background:{T.BG_CARD};border:1px solid {T.BORDER};border-radius:20px;padding:6px 14px;margin-right:8px;font-size:0.82rem;color:{T.TEXT_MAIN};font-weight:500">总计 <strong>{total}</strong></span>'
        for row in stats:
            et = row["entity_type"]
            color = type_colors.get(et, T.SLATE)
            chips += f'<span style="display:inline-flex;align-items:center;gap:4px;background:{T.BG_CARD};border:1px solid {T.BORDER};border-radius:20px;padding:6px 12px;margin-right:8px;font-size:0.78rem;color:{T.TEXT_SOFT}"><span style="width:7px;height:7px;border-radius:50%;background:{color};display:inline-block"></span>{et} {row["cnt"]}</span>'
        st.markdown(f'<div style="margin-bottom:1rem">{chips}</div>', unsafe_allow_html=True)
    else:
        st.metric("总计", 0)

    st.divider()

    if not all_ents:
        st.markdown(T.empty("🔗", "暂无实体数据", "分析情报后将自动提取实体"), unsafe_allow_html=True)
        return

    # Tabs by type
    types = sorted({e["entity_type"] for e in all_ents})
    tab_labels = ["全部"] + types
    tabs = st.tabs(tab_labels)

    for i, tab in enumerate(tabs):
        label = tab_labels[i]
        with tab:
            subset = all_ents if label == "全部" else [e for e in all_ents if e["entity_type"] == label]
            if not subset:
                st.caption("暂无此类实体")
                continue

            from analyzer.defanger import defang_text

            df = pd.DataFrame([{
                "ID":    e["id"],
                "实体值": defang_text(e["entity_value"]) if e["entity_type"] in ("url", "ip") else e["entity_value"],
                "方式":   e["extraction_method"],
                "上下文": defang_text((e.get("context") or "")[:60]),
                "时间":   str(e.get("created_at", ""))[:19] if e.get("created_at") else "",
            } for e in subset])
            st.dataframe(df, width="stretch", hide_index=True)
