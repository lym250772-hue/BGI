"""BGI Streamlit analyst console."""

from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import streamlit as st

import ui.theme as T
from ui.views import intel_pool, knowledge, overview, system_status, workbench


st.set_page_config(
    page_title="BGI 黑灰产情报研判",
    page_icon="B",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.markdown(T.CSS, unsafe_allow_html=True)

PAGES = {
    "overview": ("总览 / ChatBI", overview.show),
    "workbench": ("研判工作台", workbench.show),
    "intel_pool": ("情报池", intel_pool.show),
    "knowledge": ("知识库", knowledge.show),
    "system": ("系统状态", system_status.show),
}


def _sidebar():
    with st.sidebar:
        st.markdown(
            """
            <div style='padding:0.4rem 0.4rem 1rem'>
              <div style='font-size:1.2rem;font-weight:800;color:#FFFFFF'>BGI</div>
              <div style='font-size:0.72rem;color:#92A1AF;margin-top:2px'>黑灰产情报研判 Agent</div>
            </div>
            """,
            unsafe_allow_html=True,
        )

        keys = list(PAGES.keys())
        labels = [PAGES[k][0] for k in keys]
        current = st.session_state.get("nav_page", "overview")
        if current not in keys:
            current = "overview"

        selected = st.radio(
            "导航",
            labels,
            index=keys.index(current),
            label_visibility="collapsed",
        )
        selected_key = keys[labels.index(selected)]
        if selected_key != current:
            st.session_state.nav_page = selected_key
            st.rerun()

        st.markdown(
            f"""
            <div style='position:fixed;bottom:0.8rem;left:0.8rem;right:0.8rem;
                        border-top:1px solid #25313E;padding-top:0.6rem;
                        font-size:0.68rem;color:#7F8D99'>
              v0.5 Console<br>{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
            </div>
            """,
            unsafe_allow_html=True,
        )


_sidebar()
page_key = st.session_state.get("nav_page", "overview")
PAGES.get(page_key, PAGES["overview"])[1]()
