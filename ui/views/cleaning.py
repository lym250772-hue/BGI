"""数据清洗页面 — v2.0: 作者感知去重 + 内容角色五分类 + MEDIA_ONLY。"""

from __future__ import annotations

import sys
import time
from pathlib import Path

import pandas as pd
import streamlit as st

from ui import data
from ui.components import page_header, service_strip

# ── 会话状态初始化 ────────────────────────────────────────────────────────────

def _init_session():
    defaults = {
        "cleaning_selected_ids": [],
        "cleaning_batch_result": None,
        "cleaning_preview_id": None,
        "cleaning_filter_status": "RAW_COLLECTED",
        "cleaning_filter_platform": "全部",
    }
    for k, v in defaults.items():
        if k not in st.session_state:
            st.session_state[k] = v


# ── 清洗执行 ──────────────────────────────────────────────────────────────────

def _run_cleaning_on_selected(selected_ids: list[int]) -> dict:
    """调用 data.run_cleaning 并向 ods_raw_intel 写入清洗结果。"""
    from cleaner.pipeline import CleaningPipeline
    from storage.mysql_store import mysql

    pipeline = CleaningPipeline()
    existing_hashes = []
    try:
        existing_hashes = mysql.list_existing_simhashes(limit=5000)
    except Exception:
        pass

    items = []
    for raw_id in selected_ids:
        try:
            row = mysql.get_raw_by_id(raw_id)
            if row:
                items.append({
                    "id": row["id"],
                    "platform": row.get("source_platform") or "unknown",
                    "content_raw": row.get("content_raw") or "",
                    "author_uid": row.get("author_id") or "",
                    "author_username": row.get("author_name") or "",
                })
        except Exception:
            pass

    cleaned, discarded, media_only, similar = 0, 0, 0, 0
    details: list[dict] = []

    for item in items:
        result = pipeline.process(
            item["content_raw"],
            existing_hashes=existing_hashes,
            platform=item["platform"],
            author_uid=item["author_uid"],
            author_username=item["author_username"],
        )

        status = result.get("status", "CLEANED" if not result["should_discard"] else "DISCARDED")

        if status == "DISCARDED":
            mysql.update_raw_status(item["id"], "DISCARDED", clean_text=result["text"])
            discarded += 1
        elif status in ("MEDIA_ONLY", "SIMILAR", "CLEANED"):
            mysql.update_raw_status(
                item["id"], "CLEANED",
                clean_text=result["text"],
                simhash=result["simhash"],
            )
            if status == "MEDIA_ONLY":
                media_only += 1
            elif status == "SIMILAR":
                similar += 1
            else:
                cleaned += 1

        existing_hashes.append(result["simhash"])

        # 构建丢弃原因
        discard_reason = ""
        if status == "DISCARDED":
            reason = result.get("noise_reason", "")
            is_dup = result.get("is_duplicate", False)
            is_sim = result.get("is_similar", False)
            is_media = result.get("is_media_only", False)
            if is_dup:
                discard_reason = reason if reason else "作者重复(同一人重复发相同内容)"
            elif is_media:
                discard_reason = reason if reason else "QQ嵌入媒体(无法获取图片/视频内容)"
            elif reason:
                discard_reason = reason
            else:
                # 真正找不到原因时才用默认描述
                score = result.get('noise_score', 0)
                if score >= 0.6:
                    discard_reason = f"噪声评分过高({score:.2f})"
                else:
                    discard_reason = f"平台规则判定为噪声(评分{score:.2f})"

        details.append({
            "id": item["id"],
            "platform": item["platform"],
            "original": item["content_raw"][:200],
            "text": result["text"][:200],
            "status": status,
            "noise_reason": discard_reason,
            "noise_score": result.get("noise_score", 0),
            "content_role": result.get("content_role", "unknown"),
            "is_media_only": result.get("is_media_only", False),
            "similar_to": result.get("similar_to", ""),
        })

    return {
        "total": len(items),
        "cleaned": cleaned,
        "discarded": discarded,
        "media_only": media_only,
        "similar": similar,
        "details": details,
    }


def _run_cleaning_all_pending(limit: int = 500) -> dict:
    """清洗所有 RAW_COLLECTED 状态的数据。"""
    from storage.mysql_store import mysql
    pending = mysql.list_raw(status="RAW_COLLECTED", limit=limit)
    if not pending:
        return {"total": 0, "cleaned": 0, "discarded": 0, "media_only": 0, "similar": 0, "details": []}
    ids = [int(r["id"]) for r in pending]
    return _run_cleaning_on_selected(ids)


# ── 单条清洗预览 ──────────────────────────────────────────────────────────────

def _show_cleaning_preview(raw_id: int):
    """展示单条数据的清洗前后对比。"""
    result = data.get_cleaning_preview(raw_id)
    if not result:
        st.warning("无法加载该条数据")
        return

    col1, col2 = st.columns(2)
    with col1:
        st.markdown("**原始文本**")
        st.text_area("original", result["original"], height=150, key=f"orig_{raw_id}",
                     label_visibility="collapsed")
    with col2:
        st.markdown("**清洗后文本**")
        st.text_area("cleaned", result["cleaned"], height=150, key=f"clean_{raw_id}",
                     label_visibility="collapsed")

    # 清洗步骤明细
    with st.expander("清洗步骤详情", expanded=True):
        steps = result["steps"]
        c1, c2, c3 = st.columns(3)
        with c1:
            st.metric("Emoji 发现", steps["emoji"]["emoji_count"])
            if steps["emoji"]["emojis_found"]:
                st.caption(" ".join(steps["emoji"]["emojis_found"]))
        with c2:
            is_noise = steps["platform"]["is_platform_noise"]
            st.metric("平台噪声", "是" if is_noise else "否",
                     delta=steps["platform"]["platform_noise_reason"] if is_noise else None)
        with c3:
            st.metric("噪声评分", f"{result['noise_score']:.2f}")
            if result["noise_reasons"]:
                for r in result["noise_reasons"][:3]:
                    st.caption(f"• {r}")

        st.divider()
        c4, c5 = st.columns(2)
        with c4:
            priority_color = "red" if result["priority"] == "high" else "green"
            st.markdown(f"优先级: **:{priority_color}[{result['priority']}]**")
            st.markdown(f"SimHash: `{result['simhash']}`")
        with c5:
            should_discard = result["should_discard"]
            st.markdown(f"丢弃判定: **{'是' if should_discard else '否'}**")


# ── 主渲染函数 ────────────────────────────────────────────────────────────────

def show():
    _init_session()
    page_header("Cleaning", "数据清洗", "v2.0 作者感知去重 · 内容角色五分类 · MEDIA_ONLY 保护")
    service_strip(compact=True)

    # ── Tab 1: 批量清洗 ──────────────────────────────────────────────────
    tab1, tab2, tab3 = st.tabs(["批量清洗", "清洗预览", "操作日志"])

    with tab1:
        st.markdown("### 批量清洗")

        col1, col2, col3, col4 = st.columns([1, 1, 1, 0.8])
        with col1:
            status_label = st.selectbox(
                "数据状态",
                ["RAW_COLLECTED（待清洗）", "全部待处理"],
                key="cleaning_status",
            )
        with col2:
            platform = st.selectbox(
                "平台筛选",
                ["全部", "weibo", "zhihu", "tieba", "xiaohongshu", "douyin", "xianyu", "qq_group"],
                key="cleaning_platform",
            )
        with col3:
            limit = st.number_input("单次清洗数量", min_value=20, max_value=2000, value=200, step=20)
        with col4:
            st.markdown("<br>", unsafe_allow_html=True)
            do_clean_all = st.button("🚀 一键清洗", type="primary", use_container_width=True)

        # ── 情报列表 ──
        filter_status = None
        if status_label == "RAW_COLLECTED（待清洗）":
            filter_status = "RAW_COLLECTED"
        filter_platform = None if platform == "全部" else platform

        rows = data.list_intel(status=filter_status, keyword="", limit=limit)
        if filter_platform:
            rows = [r for r in rows if r.get("source_platform") == filter_platform]

        if rows:
            # 多选表格
            df = pd.DataFrame([
                {
                    "": False,
                    "ID": r.get("id"),
                    "平台": r.get("source_platform") or "-",
                    "作者": r.get("author_name") or "-",
                    "内容摘要": (r.get("content_preview") or r.get("content_raw") or "")[:100],
                    "状态": r.get("raw_status") or "-",
                }
                for r in rows
            ])

            edited = st.data_editor(
                df,
                hide_index=True,
                use_container_width=True,
                height=400,
                column_config={"": st.column_config.CheckboxColumn("选中", default=False)},
                disabled=["ID", "平台", "作者", "内容摘要", "状态"],
                key="cleaning_editor",
            )

            selected = [int(row["ID"]) for _, row in edited.iterrows() if row[""]]

            col_a, col_b, col_c = st.columns([0.6, 0.6, 2])
            with col_a:
                if st.button("🧹 清洗所选", type="secondary", disabled=not selected,
                            use_container_width=True):
                    with st.spinner(f"正在清洗 {len(selected)} 条数据..."):
                        st.session_state.cleaning_batch_result = _run_cleaning_on_selected(selected)
                    st.rerun()
            with col_b:
                if st.button("📋 全选手动清洗", type="secondary", use_container_width=True):
                    all_ids = [int(r["id"]) for r in rows]
                    with st.spinner(f"正在清洗 {len(all_ids)} 条数据..."):
                        st.session_state.cleaning_batch_result = _run_cleaning_on_selected(all_ids)
                    st.rerun()

            st.caption(f"共 {len(rows)} 条待清洗数据，已选中 {len(selected)} 条")
        else:
            st.info("没有待清洗的数据。请先在采集器管理页面采集数据，或导入示例数据。")

        # ── 一键清洗按钮 ──
        if do_clean_all:
            with st.spinner(f"正在清洗最多 {limit} 条数据..."):
                st.session_state.cleaning_batch_result = _run_cleaning_all_pending(limit=limit)
            st.rerun()

        # ── 清洗结果展示 ──
        if st.session_state.cleaning_batch_result:
            result = st.session_state.cleaning_batch_result
            st.divider()
            st.markdown("### 清洗结果")

            c1, c2, c3, c4, c5 = st.columns(5)
            with c1:
                st.metric("总计", result["total"])
            with c2:
                st.metric("✅ 通过", result["cleaned"])
            with c3:
                st.metric("🔗 相似", result["similar"])
            with c4:
                st.metric("📷 媒体", result["media_only"])
            with c5:
                st.metric("🗑️ 丢弃", result["discarded"])

            # 详情表
            if result.get("details"):
                all_details = result["details"]
                # 用 session_state 记住展开状态
                if "cleaning_detail_expanded" not in st.session_state:
                    st.session_state.cleaning_detail_expanded = False

                col_a, col_b = st.columns([1, 3])
                with col_a:
                    filter_status = st.selectbox(
                        "筛选", ["全部", "✅ 通过", "🔗 相似", "📷 媒体", "🗑️ 丢弃"],
                        key="cleaning_detail_filter",
                    )
                with col_b:
                    detail_expanded = st.checkbox(
                        "展开详情", value=st.session_state.cleaning_detail_expanded,
                        key="cleaning_detail_expand_cb",
                    )
                    st.session_state.cleaning_detail_expanded = detail_expanded

                details = list(all_details)
                if filter_status == "✅ 通过":
                    details = [d for d in details if d["status"] == "CLEANED"]
                elif filter_status == "🔗 相似":
                    details = [d for d in details if d["status"] == "SIMILAR"]
                elif filter_status == "📷 媒体":
                    details = [d for d in details if d["status"] == "MEDIA_ONLY"]
                elif filter_status == "🗑️ 丢弃":
                    details = [d for d in details if d["status"] == "DISCARDED"]

                if st.session_state.cleaning_detail_expanded:
                    # 根据筛选决定列
                    is_discarded_view = (filter_status == "🗑️ 丢弃")
                    rows = []
                    for d in details:
                        row = {
                            "ID": d["id"],
                            "平台": d["platform"],
                            "状态": d["status"],
                            "内容角色": d.get("content_role", ""),
                            "噪声分": f"{d['noise_score']:.2f}",
                        }
                        if is_discarded_view:
                            row["丢弃原因"] = d.get("noise_reason", "")[:100]
                        row["清洗后文本"] = (d.get("text") or "")[:120]
                        rows.append(row)
                    st.dataframe(pd.DataFrame(rows), hide_index=True, use_container_width=True, height=300)
                    st.caption(f"共 {len(details)} 条")

            # 清除按钮
            if st.button("清除结果", key="clear_cleaning_result"):
                st.session_state.cleaning_batch_result = None
                st.rerun()

    # ── Tab 2: 清洗预览 ──────────────────────────────────────────────────
    with tab2:
        st.markdown("### 单条清洗预览")
        preview_id = st.number_input("输入情报 ID", min_value=1, value=1, step=1, key="preview_id_input")
        if st.button("🔍 预览清洗效果"):
            st.session_state.cleaning_preview_id = preview_id

        if st.session_state.cleaning_preview_id:
            _show_cleaning_preview(st.session_state.cleaning_preview_id)

    # ── Tab 3: 操作日志 / 统计 ────────────────────────────────────────────
    with tab3:
        st.markdown("### 清洗统计")

        try:
            from storage.mysql_store import mysql
            with mysql.cursor() as c:
                c.execute(
                    """SELECT raw_status, COUNT(*) AS cnt
                       FROM ods_raw_intel
                       GROUP BY raw_status
                       ORDER BY cnt DESC"""
                )
                status_rows = [dict(r) for r in c.fetchall()]
        except Exception:
            status_rows = []

        if status_rows:
            status_df = pd.DataFrame([
                {"状态": r["raw_status"], "数量": r["cnt"]}
                for r in status_rows
            ])
            col_a, col_b = st.columns([1, 2])
            with col_a:
                st.dataframe(status_df, hide_index=True, use_container_width=True)
            with col_b:
                st.bar_chart(status_df.set_index("状态"), use_container_width=True, height=300)
        else:
            st.info("暂无数据。请先导入示例数据或执行采集。")

        st.divider()
        st.markdown("### 清洗管道说明")
        st.markdown("""
        | 步骤 | 功能 | 技术 |
        |:--:|------|------|
        | 0 | Emoji 语义翻译 | 100+ 映射，8 大语义类别，追加式翻译 |
        | 1 | 平台感知过滤 | 7 平台专属规则 + 关键词误匹配检测 |
        | 2 | 文本规范化 | HTML/Unicode/零宽字符/全半角/URL 简化 |
        | 3 | 作者感知去重 ⭐ | 同作者+相似=丢弃，不同作者+相似=情报保留 |
        | 4 | 噪声评分 | 12 维度评分，短文本情报免罚 |
        | 5 | 优先级标记 | 36 个高危关键词 → HIGH/NORMAL |
        """)
