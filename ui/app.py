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


def _initial_page() -> str:
    """Read page key from URL first, then session state."""
    try:
        page = st.query_params.get("page")
        if isinstance(page, list):
            page = page[0] if page else None
        if page in PAGES:
            return page
    except Exception:
        pass
    page = st.session_state.get("nav_page", "overview")
    return page if page in PAGES else "overview"


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
        current = _initial_page()
        if current not in keys:
            current = "overview"
        st.session_state.nav_page = current

        selected = st.radio(
            "导航",
            labels,
            index=keys.index(current),
            label_visibility="collapsed",
        )
        selected_key = keys[labels.index(selected)]
        if selected_key != current:
            st.session_state.nav_page = selected_key
            try:
                st.query_params["page"] = selected_key
            except Exception:
                pass
            st.rerun()

        st.markdown(
            f"""
            <div class='sidebar-footer'>
              <div style='border-top:1px solid #25313E;padding-top:0.6rem;
                          font-size:0.68rem;color:#7F8D99'>
                v0.5 Console
              </div>
            </div>
            """,
            unsafe_allow_html=True,
        )


try:
    st.query_params["page"] = _initial_page()
except Exception:
    pass

_sidebar()
page_key = _initial_page()
PAGES.get(page_key, PAGES["overview"])[1]()
