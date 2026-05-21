"""BGI Intelligence Analysis Dashboard — Morandi-themed Streamlit UI."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import streamlit as st

from ui.theme import inject_theme, render_sidebar
from ui.pages import dashboard, intel_list, entities, graph, cheat_scripts, slang_dict

st.set_page_config(
    page_title="BGI 情报分析",
    page_icon="🔍",
    layout="wide",
    initial_sidebar_state="expanded",
)

inject_theme()

page = render_sidebar()

ROUTES = {
    "dashboard":     dashboard.show,
    "intel_list":    intel_list.show,
    "entities":      entities.show,
    "graph":         graph.show,
    "cheat_scripts": cheat_scripts.show,
    "slang_dict":    slang_dict.show,
}

ROUTES.get(page, dashboard.show)()
