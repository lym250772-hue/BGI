"""BGI Intelligence Analysis Dashboard."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import streamlit as st
from datetime import datetime

import ui.theme as T
from ui.pages import dashboard, intel_list, entities, graph, cheat_scripts, slang_dict

st.set_page_config(
    page_title="BGI 情报分析",
    page_icon="🔍",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.markdown(T.CSS, unsafe_allow_html=True)

# ---- Sidebar ----
with st.sidebar:
    # Brand
    st.markdown(
        f"""<div style="display:flex;align-items:center;gap:10px;padding:0.2rem 0 1rem 0">
        <div style="width:32px;height:32px;background:{T.SAGE};border-radius:7px;
        display:flex;align-items:center;justify-content:center;color:white;
        font-weight:700;font-size:1rem">B</div>
        <div>
        <div style="font-weight:600;color:{T.TEXT_MAIN};font-size:0.95rem">BGI</div>
        <div style="font-size:0.65rem;color:{T.TEXT_MUTED}">Intelligence Analysis</div>
        </div></div>""",
        unsafe_allow_html=True,
    )

    # Navigation
    nav = [
        ("dashboard",     "📊", "仪表盘"),
        ("intel_list",    "📋", "情报列表"),
        ("entities",      "🔗", "实体库"),
        ("graph",         "🕸", "知识图谱"),
        ("cheat_scripts", "📝", "作弊剧本"),
        ("slang_dict",    "📖", "黑话词典"),
    ]

    cur = st.session_state.get("nav_page", "dashboard")
    for nid, icon, label in nav:
        is_on = cur == nid
        if st.sidebar.button(
            f"  {icon}   {label}",
            key=f"nav_{nid}",
            type="primary" if is_on else "secondary",
            width="stretch",
        ):
            st.session_state.nav_page = nid
            st.rerun()

    # Footer
    st.sidebar.markdown(
        f"""<div style="margin-top:1.5rem;padding:0.7rem 0.2rem;border-top:1px solid {T.BORDER};
        font-size:0.7rem;color:{T.TEXT_MUTED}">BGI v0.3 · {datetime.now().strftime('%Y-%m-%d %H:%M')}</div>""",
        unsafe_allow_html=True,
    )

page = st.session_state.get("nav_page", "dashboard")

ROUTES = {
    "dashboard":     dashboard.show,
    "intel_list":    intel_list.show,
    "entities":      entities.show,
    "graph":         graph.show,
    "cheat_scripts": cheat_scripts.show,
    "slang_dict":    slang_dict.show,
}

ROUTES.get(page, dashboard.show)()
