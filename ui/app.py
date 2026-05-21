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
    # Brand block
    st.markdown(
        f"""<div style="padding:0.2rem 0.5rem 0.8rem 0.5rem">
        <div style="display:flex;align-items:center;gap:10px;">
        <div style="width:30px;height:30px;background:{T.SAGE};border-radius:6px;
        display:flex;align-items:center;justify-content:center;color:white;
        font-weight:700;font-size:0.95rem">B</div>
        <div>
        <div style="font-weight:600;color:{T.TEXT_MAIN};font-size:0.93rem">BGI</div>
        <div style="font-size:0.62rem;color:{T.TEXT_MUTED};letter-spacing:0.03em">INTELLIGENCE ANALYSIS</div>
        </div></div></div>""",
        unsafe_allow_html=True,
    )

    st.markdown(
        f"""<div style="font-size:0.6rem;color:{T.TEXT_MUTED};letter-spacing:0.08em;
        text-transform:uppercase;padding:0.3rem 0.5rem 0.4rem 0.5rem">Navigation</div>""",
        unsafe_allow_html=True,
    )

    # Navigation via radio — always shows current page, no JS tricks needed
    nav_labels = [
        "📊  仪表盘 Dashboard",
        "📋  情报列表 Intel List",
        "🔗  实体库 Entities",
        "🕸  知识图谱 Graph",
        "📝  作弊剧本 Cheat Scripts",
        "📖  黑话词典 Slang Dictionary",
    ]
    nav_keys = ["dashboard", "intel_list", "entities", "graph", "cheat_scripts", "slang_dict"]

    current_page = st.session_state.get("nav_page", "dashboard")
    current_idx = nav_keys.index(current_page) if current_page in nav_keys else 0

    selected = st.sidebar.radio(
        "Navigation",
        nav_labels,
        index=current_idx,
        label_visibility="collapsed",
        key="nav_radio",
    )

    new_page = nav_keys[nav_labels.index(selected)]
    if new_page != current_page:
        st.session_state.nav_page = new_page
        st.rerun()

    # Footer
    st.sidebar.markdown(
        f"""<div style="position:fixed;bottom:1rem;left:0;right:0;padding:0.7rem 1rem;
        border-top:1px solid {T.BORDER};margin:0 0.5rem;
        font-size:0.65rem;color:{T.TEXT_MUTED}">
        BGI v0.3 · {datetime.now().strftime('%Y-%m-%d %H:%M')}</div>""",
        unsafe_allow_html=True,
    )

# ---- Router ----
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
