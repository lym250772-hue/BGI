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

# --- Page Router ---
if page == "仪表盘":
    dashboard.show()
elif page == "情报列表":
    intel_list.show()
elif page == "实体库":
    entities.show()
elif page == "知识图谱":
    graph.show()
elif page == "作弊剧本":
    cheat_scripts.show()
elif page == "黑话词典":
    slang_dict.show()
