"""Reusable Streamlit UI components."""

from __future__ import annotations

import streamlit as st

import ui.labels as L
import ui.theme as T
from ui import data


def page_header(kicker: str, title: str, subtitle: str):
    st.markdown(f"<span class='page-kicker'>{kicker}</span>", unsafe_allow_html=True)
    st.markdown(f"# {title}")


def service_strip(compact: bool = True):
    statuses = data.service_status()
    cols = st.columns(len(statuses))
    for col, item in zip(cols, statuses):
        label = "已连接" if item["ok"] else "未连接"
        with col:
            st.markdown(
                f"""
                <div class='bagi-panel-tight'>
                  <div style='display:flex;justify-content:space-between;align-items:center;gap:8px'>
                    <strong>{item['name']}</strong>
                    {T.status_dot(item['ok'], label)}
                  </div>
                  <div class='section-note' style='margin-top:4px'>{item['role']}</div>
                  <div class='mono' style='margin-top:5px;color:{T.MUTED};font-size:0.72rem'>{item['detail']}</div>
                </div>
                """,
                unsafe_allow_html=True,
            )
    if not compact:
        with st.expander("连接明细", expanded=False):
            st.dataframe(statuses, hide_index=True, use_container_width=True)


def risk_badge(level: str | None) -> str:
    value = str(level or "normal")
    label = L.risk_level_label(value)
    return T.badge(label, T.RISK_COLORS.get(value, T.BLUE))


def raw_status_badge(status: str | None) -> str:
    value = str(status or "")
    return T.badge(L.raw_status_label(value), T.STATUS_COLORS.get(value, T.MUTED))


def job_status_badge(status: str | None) -> str:
    value = str(status or "")
    return T.badge(L.job_status_label(value), T.STATUS_COLORS.get(value, T.MUTED))


def empty_panel(title: str, note: str):
    st.markdown(
        f"""
        <div class='bagi-panel' style='text-align:center;padding:2rem'>
          <div class='section-title'>{title}</div>
          <div class='section-note'>{note}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )
