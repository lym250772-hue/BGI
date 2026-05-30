"""Intel pool page."""

from __future__ import annotations

import pandas as pd
import streamlit as st

import ui.labels as L
import ui.theme as T


PLATFORMS = ["全部", "telegram", "tieba", "weibo", "zhihu", "xiaohongshu", "douyin", "forum"]
RISK_LABELS = ["全部", "诈骗", "引流", "作弊", "账号黑产", "内容违规", "工具交易", "直播违规", "未分类"]
STATUSES = {
    "全部": None,
    "待处理": "RAW_COLLECTED",
    "已研判": "ANALYZED",
    "已清洗": "CLEANED",
}


def _load_rows(limit: int = 300) -> list[dict]:
    try:
        from storage.mysql_store import mysql
        with mysql.cursor() as c:
            c.execute(
                """
                SELECT
                    o.id,
                    o.source_platform,
                    o.source_channel,
                    o.author_name,
                    o.content_raw,
                    o.raw_status,
                    o.collect_time,
                    a.risk_label,
                    a.risk_sub_label,
                    a.risk_score,
                    a.risk_level,
                    a.classification_method
                FROM ods_raw_intel o
                LEFT JOIN dwd_intel_analysis a
                  ON a.raw_id=o.id AND a.is_latest=1
                ORDER BY o.collect_time DESC, o.id DESC
                LIMIT %s
                """,
                (limit,),
            )
            return c.fetchall()
    except Exception as exc:
        st.session_state.intel_list_error = str(exc)
        return []


def _status_label(value: str) -> str:
    return {
        "RAW_COLLECTED": "待处理",
        "CLEANED": "已清洗",
        "ANALYZED": "已研判",
        "DISCARDED": "已丢弃",
    }.get(value or "", value or "-")


def _risk_text(row: dict) -> str:
    risk = row.get("risk_label") or "未分类"
    sub = row.get("risk_sub_label") or ""
    return f"{risk} / {sub}" if sub else risk


def _rows_to_df(rows: list[dict]) -> pd.DataFrame:
    try:
        from analyzer.defanger import defang_text
    except Exception:
        defang_text = lambda x: x

    return pd.DataFrame([
        {
            "情报ID": r.get("id"),
            "来源平台": r.get("source_platform") or "-",
            "频道/群组": r.get("source_channel") or "-",
            "作者": r.get("author_name") or "-",
            "内容摘要": defang_text((r.get("content_raw") or "")[:100]),
            "风险结论": _risk_text(r),
            "风险分": f"{float(r.get('risk_score') or 0):.2f}" if r.get("risk_score") is not None else "-",
            "风险等级": L.risk_level_label(r.get("risk_level") or ""),
            "判定方式": L.classification_method_label(r.get("classification_method") or ""),
            "处理状态": _status_label(r.get("raw_status")),
            "采集时间": str(r.get("collect_time", ""))[:19],
        }
        for r in rows
    ])


def show():
    st.markdown("## 情报池")
    st.caption("浏览、筛选和检索已接收的黑灰产情报，研判结果会在这里回填。")

    rows = _load_rows()
    if not rows:
        err = st.session_state.get("intel_list_error")
        if err:
            st.error("无法加载情报池，请确认 MySQL 已启动。")
            st.code(err, language="text")
        else:
            st.markdown(T.empty("DATA", "暂无情报数据", "导入或生成示例数据后会显示在这里"), unsafe_allow_html=True)
        return

    c1, c2, c3, c4 = st.columns([2.4, 1.2, 1.2, 1.2])
    with c1:
        keyword = st.text_input("搜索内容、作者或频道", placeholder="输入关键词...", key="intel_keyword")
    with c2:
        platform = st.selectbox("来源平台", PLATFORMS, key="intel_platform")
    with c3:
        risk = st.selectbox("风险类型", RISK_LABELS, key="intel_risk")
    with c4:
        status_label = st.selectbox("处理状态", list(STATUSES.keys()), key="intel_status")

    target_status = STATUSES[status_label]
    filtered = []
    for row in rows:
        if platform != "全部" and row.get("source_platform") != platform:
            continue
        row_risk = row.get("risk_label") or "未分类"
        if risk != "全部" and row_risk != risk:
            continue
        if target_status and row.get("raw_status") != target_status:
            continue
        if keyword:
            haystack = f"{row.get('content_raw', '')} {row.get('author_name', '')} {row.get('source_channel', '')}"
            if keyword.lower() not in haystack.lower():
                continue
        filtered.append(row)

    st.caption(f"共 {len(filtered)} 条情报")
    st.dataframe(
        _rows_to_df(filtered),
        width="stretch",
        hide_index=True,
        column_config={
            "情报ID": st.column_config.NumberColumn(width="small"),
            "内容摘要": st.column_config.TextColumn(width="large"),
            "风险分": st.column_config.TextColumn(width="small"),
            "采集时间": st.column_config.TextColumn(width="medium"),
        },
    )
