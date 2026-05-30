"""Black-market slang dictionary and candidate review page."""

from __future__ import annotations

import json

import pandas as pd
import streamlit as st

import ui.labels as L
import ui.theme as T


RISK_CATEGORIES = [
    "",
    "诈骗",
    "引流",
    "作弊",
    "账号黑产",
    "内容违规",
    "工具交易",
    "直播违规",
]


def _load_slang_rows() -> list[dict]:
    try:
        from storage.mysql_store import mysql
        return mysql.list_slang(status=None)
    except Exception as exc:
        st.session_state.slang_dict_error = str(exc)
        return []


def _approve(term: str, meaning: str, category: str, reviewer: str = "analyst") -> bool:
    try:
        from storage.mysql_store import mysql
        return mysql.approve_slang_candidate(term, meaning=meaning, category=category, reviewer=reviewer)
    except Exception:
        return False


def _reject(term: str, reviewer: str = "analyst", reason: str = "人工忽略") -> bool:
    try:
        from storage.mysql_store import mysql
        return mysql.reject_slang_candidate(term, reviewer=reviewer, reason=reason)
    except Exception:
        return False


def _norm(row: dict) -> dict:
    row = dict(row)
    row["term"] = row.get("term") or row.get("slang") or ""
    row["meaning"] = row.get("normalized_meaning") or row.get("meaning") or ""
    row["category"] = row.get("risk_category") or row.get("category") or "未分类"
    row["status"] = row.get("status") or "active"
    return row


def _match_search(row: dict, keyword: str) -> bool:
    if not keyword:
        return True
    haystack = " ".join([
        str(row.get("term", "")),
        str(row.get("meaning", "")),
        str(row.get("category", "")),
        str(row.get("candidate_evidence", "")),
        str(row.get("candidate_reason", "")),
    ])
    return keyword.lower() in haystack.lower()


def _examples_preview(value) -> str:
    if not value:
        return ""
    if isinstance(value, list):
        return "；".join(str(v) for v in value if v)[:80]
    try:
        parsed = json.loads(value)
        if isinstance(parsed, list):
            return "；".join(str(v) for v in parsed if v)[:80]
    except Exception:
        pass
    return str(value)[:80]


def _render_active_table(rows: list[dict]):
    if not rows:
        st.markdown(T.empty("SL", "暂无正式黑话", "候选词确认后会进入这里"), unsafe_allow_html=True)
        return
    df = pd.DataFrame([
        {
            "黑话": r["term"],
            "标准释义": r["meaning"],
            "风险分类": r["category"],
            "来源": r.get("source", ""),
            "置信度": f"{float(r.get('confidence') or 0):.2f}",
            "更新时间": str(r.get("updated_at", ""))[:19],
        }
        for r in rows
    ])
    st.dataframe(df, width="stretch", hide_index=True)


def _render_candidate_cards(rows: list[dict]):
    if not rows:
        st.markdown(T.empty("NEW", "暂无待审核候选黑话", "当模型发现疑似新黑话时会出现在这里"), unsafe_allow_html=True)
        return

    reviewer = st.text_input("审核人", value="analyst", key="slang_candidate_reviewer")
    for idx, row in enumerate(rows):
        term = row["term"]
        meaning_default = row.get("meaning") or "待人工确认"
        category_default = row.get("category") if row.get("category") in RISK_CATEGORIES else ""
        confidence = float(row.get("confidence") or 0)
        evidence = row.get("candidate_evidence") or _examples_preview(row.get("examples")) or "-"
        reason = row.get("candidate_reason") or "-"

        st.markdown(
            f"""<div class="intel-card" style="border-left:3px solid {T.AMBER_MED};margin-bottom:0.55rem">
            <div style="display:flex;gap:0.55rem;align-items:center;margin-bottom:0.3rem">
              <div style="font-size:1rem;font-weight:700;color:{T.TEXT_MAIN}">{term}</div>
              <div style="font-size:0.72rem;color:{T.TEXT_SOFT}">置信度 {confidence:.2f}</div>
              <div style="font-size:0.72rem;color:{T.TEXT_SOFT}">来源 {row.get('source', '-')}</div>
            </div>
            <div style="font-size:0.78rem;line-height:1.55;color:{T.TEXT_MAIN}">证据：{evidence}</div>
            <div style="font-size:0.74rem;line-height:1.55;color:{T.TEXT_SOFT};margin-top:0.15rem">原因：{reason}</div>
            </div>""",
            unsafe_allow_html=True,
        )

        c1, c2 = st.columns([1.4, 0.8])
        with c1:
            meaning = st.text_input(
                "确认释义",
                value=meaning_default,
                key=f"candidate_meaning_{idx}_{term}",
            )
        with c2:
            category = st.selectbox(
                "风险分类",
                RISK_CATEGORIES,
                index=RISK_CATEGORIES.index(category_default) if category_default in RISK_CATEGORIES else 0,
                key=f"candidate_category_{idx}_{term}",
            )

        b1, b2 = st.columns(2)
        with b1:
            if st.button("加入正式词典", type="primary", key=f"candidate_approve_{idx}_{term}"):
                if _approve(term, meaning, category, reviewer):
                    st.success(f"已加入正式词典：{term}")
                    st.rerun()
                st.warning("加入失败，请检查数据库连接或候选词状态")
        with b2:
            if st.button("忽略该候选", key=f"candidate_reject_{idx}_{term}"):
                if _reject(term, reviewer=reviewer):
                    st.info(f"已忽略候选词：{term}")
                    st.rerun()
                st.warning("忽略失败，请检查数据库连接或候选词状态")


def _render_rejected_table(rows: list[dict]):
    if not rows:
        st.caption("暂无已忽略候选词。")
        return
    df = pd.DataFrame([
        {
            "黑话": r["term"],
            "建议释义": r["meaning"],
            "发现证据": r.get("candidate_evidence", ""),
            "忽略原因": r.get("candidate_reason", ""),
            "审核人": r.get("reviewed_by", ""),
        }
        for r in rows
    ])
    st.dataframe(df, width="stretch", hide_index=True)


def show():
    st.markdown("## 黑话词典")
    st.caption("管理正式黑话词典，并审核模型发现的疑似新黑话。")

    rows = [_norm(r) for r in _load_slang_rows()]
    if not rows:
        err = st.session_state.get("slang_dict_error")
        if err:
            st.error("无法加载黑话词典，请确认 MySQL 已启动。")
            st.code(err, language="text")
        else:
            st.markdown(T.empty("SL", "黑话词典为空", "运行 python main.py init-db 或导入种子词典"), unsafe_allow_html=True)
        return

    active = [r for r in rows if r["status"] == "active"]
    candidates = [r for r in rows if r["status"] == "candidate"]
    rejected = [r for r in rows if r["status"] == "rejected"]

    chips = [
        f"正式词典 <strong>{len(active)}</strong>",
        f"待审核 <strong>{len(candidates)}</strong>",
        f"已忽略 <strong>{len(rejected)}</strong>",
    ]
    chips_html = "".join(
        f'<span style="display:inline-flex;align-items:center;background:{T.BG_CARD};'
        f'border:1px solid {T.BORDER};border-radius:18px;padding:5px 12px;'
        f'margin-right:8px;font-size:0.8rem;color:{T.TEXT_MAIN}">{chip}</span>'
        for chip in chips
    )
    st.markdown(f'<div style="margin:0.5rem 0 1rem">{chips_html}</div>', unsafe_allow_html=True)

    search = st.text_input("搜索黑话、释义或证据", placeholder="输入关键词...", key="slang_dict_search")
    active = [r for r in active if _match_search(r, search)]
    candidates = [r for r in candidates if _match_search(r, search)]
    rejected = [r for r in rejected if _match_search(r, search)]

    tab_active, tab_candidate, tab_rejected = st.tabs([
        f"正式词典 ({len(active)})",
        f"待审核候选 ({len(candidates)})",
        f"已忽略 ({len(rejected)})",
    ])
    with tab_active:
        _render_active_table(active)
    with tab_candidate:
        _render_candidate_cards(candidates)
    with tab_rejected:
        _render_rejected_table(rejected)
