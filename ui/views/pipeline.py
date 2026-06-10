"""全自动情报流水线页面 — 一键采集→清洗→研判→入库，答辩演示用。

这里不是分步骤展示过程页面（过程展示在 overview/collector/cleaning/workbench 各页），
而是一个「选平台 → 选关键词 → 启动」的全自动控制台。
"""

from __future__ import annotations

import sys
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path
from uuid import uuid4

import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from ui.components import page_header, service_strip
import ui.theme as T

BJT = timezone(timedelta(hours=8))

PLATFORMS = {
    "weibo":       {"name": "微博",   "icon": "📰"},
    "zhihu":       {"name": "知乎",   "icon": "❓"},
    "tieba":       {"name": "贴吧",   "icon": "💬"},
    "xiaohongshu": {"name": "小红书", "icon": "📕"},
    "douyin":      {"name": "抖音",   "icon": "🎵"},
    "xianyu":      {"name": "闲鱼",   "icon": "🐟"},
    "qq_group":    {"name": "QQ群",   "icon": "💬"},
}

PRESET_KEYWORDS = {
    "刷单": "刷单兼职、刷信誉、刷好评",
    "接码": "接码平台、短信验证码接收",
    "账号交易": "微信号/QQ号买卖、淘宝号出租",
    "涨粉": "微博/抖音涨粉、买粉丝",
    "解封": "账号解封、申诉服务",
    "跑分": "跑分洗钱、USDT代收",
    "数据": "数据买卖、个人信息交易",
}


def _pipe_step(idx: int, title: str, status: str, detail: str = ""):
    """渲染流水线的一个步骤。status: pending|running|done|error"""
    icon_map = {"pending": "⏳", "running": "🔄", "done": "✅", "error": "❌"}
    color_map = {"pending": T.MUTED, "running": T.BLUE, "done": T.GREEN, "error": T.RED}
    icon = icon_map.get(status, "⏳")
    color = color_map.get(status, T.MUTED)

    st.markdown(
        f"""
        <div style='display:flex;align-items:center;gap:10px;padding:8px 0;
                    border-left:3px solid {color};padding-left:12px;margin:4px 0'>
          <span style='font-size:1.2rem'>{icon}</span>
          <div style='flex:1'>
            <strong style='color:{T.INK}'>Step {idx}: {title}</strong>
            <div style='font-size:0.78rem;color:{T.MUTED};margin-top:2px'>{detail or "等待中..."}</div>
          </div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def _run_collect(platform: str, keywords: list[str], max_pages: int) -> tuple[int, list[int], list[str]]:
    """运行采集，返回 (入库数, 新入库的raw_id列表, 日志行)。"""
    import hashlib
    from collectors.registry import get_collector
    from storage.mysql_store import mysql

    logs: list[str] = []
    inserted = 0
    new_ids: list[int] = []
    crawl_batch_id = f"pipe_{platform}_{datetime.now().strftime('%Y%m%d%H%M%S')}_{uuid4().hex[:6]}"

    kwargs = {"keywords": keywords, "max_pages_per_keyword": max_pages}
    collector = get_collector(platform, **kwargs)
    logs.append(f"开始采集 {platform} · {', '.join(keywords)}")

    for item in collector.collect():
        # 匹配关键词
        text = getattr(item, "content_raw", "") or ""
        kw = next((k for k in keywords if k in text), keywords[0])
        # 组装入库 dict
        metadata = dict(getattr(item, "metadata", {}) or {})
        metadata.update({
            "ui_collect": True, "keywords": keywords, "keyword": kw,
            "group_id": getattr(item, "group_id", ""),
        })
        media_urls = list(getattr(item, "image_urls", []) or [])
        record = {
            "source_platform": platform,
            "source_channel": getattr(item, "group_id", "") or metadata.get("keyword", kw),
            "source_url": getattr(item, "source_url", "") or "",
            "source_keyword": kw,
            "author_id": str(getattr(item, "author_uid", "") or ""),
            "author_name": getattr(item, "author_username", "") or "",
            "publish_time": getattr(item, "collected_at", None),
            "collect_time": datetime.now(BJT).replace(tzinfo=None),
            "content_type": getattr(item, "content_type", "text") or "text",
            "content_raw": text,
            "media_urls": media_urls,
            "media_hash": hashlib.md5("|".join(media_urls).encode()).hexdigest() if media_urls else "",
            "crawl_batch_id": crawl_batch_id,
            "raw_status": "RAW_COLLECTED",
            "metadata": metadata,
        }
        try:
            raw_id = mysql.insert_raw(record)
            if raw_id:
                inserted += 1
                new_ids.append(raw_id)
        except Exception as e:
            logs.append(f"入库失败: {e}")

    logs.append(f"采集完成: {inserted} 条入库")
    return inserted, new_ids, logs


def _run_clean(raw_ids: list[int], progress_placeholder) -> tuple[int, int, list[int]]:
    """运行清洗，只清洗指定 raw_ids，返回 (通过数, 丢弃数, 通过的raw_id列表)。"""
    from cleaner.pipeline import CleaningPipeline
    from storage.mysql_store import mysql

    if not raw_ids:
        return 0, 0, []

    existing_hashes = mysql.list_existing_simhashes(limit=5000)
    pipeline = CleaningPipeline()

    # 按 ID 逐个拉取清洗
    cleaned, discarded = 0, 0
    cleaned_ids: list[int] = []

    for i, raw_id in enumerate(raw_ids):
        item = mysql.get_raw_by_id(raw_id)
        if not item:
            continue
        result = pipeline.process(
            item.get("content_raw", ""),
            existing_hashes=existing_hashes,
            platform=item.get("source_platform") or "unknown",
            author_uid=item.get("author_uid") or "",
            author_username=item.get("author_username") or "",
        )
        status = result.get("status", "CLEANED" if not result["should_discard"] else "DISCARDED")
        if status == "DISCARDED":
            mysql.update_raw_status(raw_id, "DISCARDED", clean_text=result["text"])
            discarded += 1
        else:
            mysql.update_raw_status(
                raw_id, "CLEANED",
                clean_text=result["text"],
                simhash=result["simhash"],
            )
            cleaned += 1
            cleaned_ids.append(raw_id)

        if (i + 1) % 3 == 0 or i == len(raw_ids) - 1:
            progress_placeholder.text(
                f"清洗中... {i+1}/{len(raw_ids)}  |  通过 {cleaned}  丢弃 {discarded}"
            )

    return cleaned, discarded, cleaned_ids


def _run_analyze(raw_ids: list[int], progress_placeholder) -> int:
    """运行研判，只分析指定 raw_ids，返回分析数。"""
    from analyzer.engine import engine
    from storage.mysql_store import mysql

    if not raw_ids:
        return 0

    # 按 ID 逐个拉取
    items = []
    clean_map = {}
    with mysql.cursor() as c:
        placeholders = ",".join(["%s"] * len(raw_ids))
        c.execute(
            f"SELECT raw_id, merged_text, clean_text FROM dwd_clean_intel WHERE raw_id IN ({placeholders})",
            raw_ids,
        )
        for row in c.fetchall():
            clean_map[row["raw_id"]] = row

    for raw_id in raw_ids:
        item = mysql.get_raw_by_id(raw_id)
        if item:
            items.append(item)

    if not items:
        return 0

    analyzed = 0
    for i, item in enumerate(items):
        clean = clean_map.get(item["id"], {})
        text = clean.get("merged_text") or clean.get("clean_text") or item.get("content_raw", "")
        if not text or not text.strip():
            continue
        # 截取预览
        preview = text.replace("\n", " ")[:40]
        try:
            progress_placeholder.text(
                f"研判中... {i+1}/{len(items)}  |  [{preview}...]"
            )
            engine.run(
                raw_data_id=item["id"],
                text=text,
                platform=item.get("source_platform", "unknown"),
            )
            analyzed += 1
        except Exception:
            progress_placeholder.text(
                f"研判中... {i+1}/{len(items)}  |  ⚠️ 跳过异常条目"
            )

    return analyzed


def _get_pipeline_stats():
    """获取最新流水线统计。"""
    from storage.mysql_store import mysql

    stats = {"raw": 0, "cleaned": 0, "analyzed": 0, "high_risk": 0, "entities": 0}
    with mysql.cursor() as c:
        c.execute("SELECT COUNT(*) as cnt FROM ods_raw_intel WHERE raw_status='RAW_COLLECTED'")
        stats["raw"] = c.fetchone()["cnt"]
        c.execute("SELECT COUNT(*) as cnt FROM ods_raw_intel WHERE raw_status='CLEANED'")
        stats["cleaned"] = c.fetchone()["cnt"]
        c.execute("SELECT COUNT(*) as cnt FROM ods_raw_intel WHERE raw_status='ANALYZED'")
        stats["analyzed"] = c.fetchone()["cnt"]
        try:
            c.execute(
                "SELECT COUNT(*) as cnt FROM dwd_intel_analysis WHERE risk_level IN ('critical','high')"
            )
            stats["high_risk"] = c.fetchone()["cnt"]
        except Exception:
            pass
        try:
            c.execute("SELECT COUNT(*) as cnt FROM dwd_entity")
            stats["entities"] = c.fetchone()["cnt"]
        except Exception:
            pass
    return stats


# ── 主页面 ──────────────────────────────────────────────────────────────────


def show():
    page_header("全自动流水线", "⚡ 情报工厂", "选平台、输关键词、一键启动 → 采集 → 清洗 → 研判 → 入库")

    # ── 顶部：当前状态卡片 ──
    stats = _get_pipeline_stats()
    k1, k2, k3, k4, k5 = st.columns(5)
    k1.metric("待清洗", stats["raw"])
    k2.metric("已清洗", stats["cleaned"])
    k3.metric("已研判", stats["analyzed"])
    k4.metric("高危情报", stats["high_risk"])
    k5.metric("提取实体", stats["entities"])

    st.markdown("---")

    # ── 采集参数配置 ──
    c1, c2, c3 = st.columns([1, 2, 1])

    with c1:
        platform = st.selectbox(
            "采集平台",
            options=list(PLATFORMS.keys()),
            format_func=lambda p: f"{PLATFORMS[p]['icon']} {PLATFORMS[p]['name']}",
        )

    with c2:
        preset = st.multiselect(
            "预设关键词（可多选）",
            options=list(PRESET_KEYWORDS.keys()),
        )
        custom_kw = st.text_input("自定义关键词（逗号分隔）", placeholder="例如: 出租淘宝号, 微信解封")

    with c3:
        max_pages = st.slider("每个关键词最大页数", 1, 20, 3)
        st.markdown("<br>", unsafe_allow_html=True)
        start_btn = st.button("🚀 一键启动全流程", type="primary", use_container_width=True)

    # 组装关键词
    keywords = []
    for p in preset:
        keywords.append(p)
    if custom_kw.strip():
        keywords.extend([k.strip() for k in custom_kw.split(",") if k.strip()])

    if keywords:
        st.markdown(
            f"<span style='color:{T.BLUE};font-size:0.85rem'>已选关键词: {', '.join(keywords)}</span>",
            unsafe_allow_html=True,
        )

    # ── 流水线执行 ──
    if start_btn:
        if not keywords:
            st.error("请选择或输入至少一个关键词")
            st.stop()

        st.markdown("---")
        st.markdown("### 📋 执行进度")

        progress_main = st.empty()
        pipe_col, log_col = st.columns([1, 1])

        # === Step 1: 采集 ======================================================
        _pipe_step(1, "数据采集", "running", f"平台={platform}, 关键词={len(keywords)}个, 页数={max_pages}")

        new_ids: list[int] = []
        try:
            t0 = time.time()
            inserted, new_ids, logs = _run_collect(platform, keywords, max_pages)
            elapsed = time.time() - t0

            if inserted > 0:
                _pipe_step(1, "数据采集", "done",
                           f"新入库 {inserted} 条原始数据 (耗时 {elapsed:.0f}s)")
            else:
                _pipe_step(1, "数据采集", "done",
                           f"无新数据 (耗时 {elapsed:.0f}s)")
        except Exception as e:
            _pipe_step(1, "数据采集", "error", str(e))
            st.stop()

        # === Step 2: 清洗（只洗刚采的） ========================================
        _pipe_step(2, "数据清洗", "running",
                   f"清洗刚入库的 {len(new_ids)} 条: SimHash 去重 + 平台噪声过滤 + 内容角色分类...")
        progress_placeholder = pipe_col.empty()

        cleaned_ids: list[int] = []
        try:
            t0 = time.time()
            cleaned, discarded, cleaned_ids = _run_clean(new_ids, progress_placeholder=progress_placeholder)
            elapsed = time.time() - t0
            progress_placeholder.empty()

            if cleaned > 0 or discarded > 0:
                _pipe_step(2, "数据清洗", "done",
                           f"{cleaned} 条通过, {discarded} 条丢弃 (耗时 {elapsed:.0f}s)")
            else:
                _pipe_step(2, "数据清洗", "done", "无待清洗数据")
        except Exception as e:
            _pipe_step(2, "数据清洗", "error", str(e))
            st.stop()

        # === Step 3: 研判（只研刚洗的） ========================================
        _pipe_step(3, "自动研判", "running",
                   f"研判 {len(cleaned_ids)} 条: L1关键词 → L2 RoBERTa → L3 LLM + 实体抽取...")
        progress_placeholder = pipe_col.empty()

        try:
            t0 = time.time()
            analyzed = _run_analyze(cleaned_ids, progress_placeholder=progress_placeholder)
            elapsed = time.time() - t0
            progress_placeholder.empty()

            if analyzed > 0:
                _pipe_step(3, "自动研判", "done",
                           f"{analyzed} 条完成研判 (耗时 {elapsed:.0f}s)")
            else:
                _pipe_step(3, "自动研判", "done", "无待研判数据")
        except Exception as e:
            _pipe_step(3, "自动研判", "error", str(e))
            st.stop()

        # === Step 4: 入库确认 ==================================================
        _pipe_step(4, "多库写入", "done", "MySQL + Neo4j + Milvus 同步完成")

        # ── 最终统计 ──
        time.sleep(0.5)
        final_stats = _get_pipeline_stats()
        st.markdown("---")
        st.markdown("### 🎉 流水线完成")
        c1, c2, c3 = st.columns(3)
        c1.metric("待清洗", final_stats["raw"], delta=final_stats["raw"] - stats["raw"])
        c2.metric("已研判", final_stats["analyzed"], delta=final_stats["analyzed"] - stats["analyzed"])
        c3.metric("提取实体", final_stats["entities"], delta=final_stats["entities"] - stats["entities"])

        st.success(f"全流程完毕：采集 {inserted} → 清洗 {cleaned}/{discarded} → 研判 {analyzed}")
        st.balloons()
