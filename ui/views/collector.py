"""采集器管理页面 — 答辩演示用：一键触发采集 + 结果展示。"""

from __future__ import annotations

import hashlib
import sys
import threading
import time
from datetime import datetime, timezone, timedelta
from uuid import uuid4

BJT = timezone(timedelta(hours=8))
from pathlib import Path

import pandas as pd
import streamlit as st

from ui import data
from ui.components import page_header, service_strip

# ── 平台配置 ────────────────────────────────────────────────────────────────

PLATFORMS = {
    "weibo":       {"name": "微博",   "icon": "📰", "cls": "内容社区", "tech": "AJAX API (纯HTTP)",      "speed": "~8条/s",  "need": "Cookie"},
    "zhihu":       {"name": "知乎",   "icon": "❓", "cls": "内容社区", "tech": "浏览器内fetch API",       "speed": "~5条/s",  "need": "Cookie (JS注入)"},
    "tieba":       {"name": "贴吧",   "icon": "💬", "cls": "论坛",     "tech": "浏览器 + DOM",            "speed": "~10条/s", "need": "Cookie"},
    "xiaohongshu": {"name": "小红书", "icon": "📕", "cls": "内容社区", "tech": "SSR提取 + DOM兜底",       "speed": "~0.5条/s","need": "Cookie + 浏览器"},
    "douyin":      {"name": "抖音",   "icon": "🎵", "cls": "短视频",   "tech": "X-Bogus + 浏览器内fetch",  "speed": "~0.5条/s","need": "msToken/Cookie"},
    "xianyu":      {"name": "闲鱼",   "icon": "🐟", "cls": "二手交易", "tech": "v3持久化浏览器",          "speed": "~0.3条/s","need": "扫码登录(持久化)"},
    "qq_group":    {"name": "QQ群",   "icon": "💬", "cls": "社交IM",   "tech": "NapCatQQ WebSocket+HTTP", "speed": "实时+批量","need": "NapCatQQ + QQ登录"},
}

DEMO_KEYWORDS = ["刷单", "接码", "账号交易", "涨粉", "解封"]


# ── 后台采集 ─────────────────────────────────────────────────────────────────

def _do_collect(platform: str, keywords: list[str], max_pages: int, fetch_replies: bool):
    """直接调用 collector（不走 subprocess），产出 IntelItem 列表 + 日志。"""
    from collectors.registry import get_collector

    logs: list[str] = []
    results: list[dict] = []
    crawl_batch_id = f"ui_{platform}_{datetime.now().strftime('%Y%m%d%H%M%S')}_{uuid4().hex[:6]}"
    inserted_count = 0

    kwargs = {"keywords": keywords, "max_pages_per_keyword": max_pages}
    if platform in ("tieba",):
        kwargs["fetch_replies"] = fetch_replies

    try:
        from storage.mysql_store import mysql

        collector = get_collector(platform, **kwargs)
        logs.append(f"[{datetime.now().strftime('%H:%M:%S')}] 开始采集 {platform} · {', '.join(keywords)}")
        for item in collector.collect():
            # 写入 MySQL；失败必须暴露在日志里，否则前端看得到采集结果，
            # 但情报池查不到入库数据，会造成“数据消失”的错觉。
            raw_id = None
            try:
                raw_id = mysql.insert_raw(
                    _intel_item_to_insert_dict(
                        item,
                        keywords=keywords,
                        crawl_batch_id=crawl_batch_id,
                    )
                )
                inserted_count += 1
            except Exception as exc:
                logs.append(
                    f"[WARN] 入库失败：{(item.content_raw or '')[:40]}... · {exc}"
                )

            results.append({
                "情报ID": raw_id if raw_id is not None else "入库失败",
                "平台": item.platform,
                "频道": item.group_id or (item.metadata or {}).get("keyword", "-"),
                "内容": (item.content_raw or "")[:120],
                "作者": item.author_username or "-",
                "点赞": item.like_count,
                "评论": item.comment_count,
                "转发": item.share_count,
                "爬取时间": _to_bj_time(item.collected_at),
                "链接": item.source_url or "",
            })
            if len(results) % 5 == 0:
                logs.append(f"[{datetime.now().strftime('%H:%M:%S')}] 已采集 {len(results)} 条...")
        logs.append(
            f"[{datetime.now().strftime('%H:%M:%S')}] 采集完成，共 {len(results)} 条，成功入库 {inserted_count} 条"
        )
    except Exception as exc:
        logs.append(f"[ERROR] {exc}")

    return results, logs


def _intel_item_to_insert_dict(item, keywords: list[str], crawl_batch_id: str) -> dict:
    """把前端采集得到的 IntelItem 转成 ods_raw_intel 入库结构。"""
    metadata = dict(getattr(item, "metadata", {}) or {})
    keyword = metadata.get("keyword") or _match_keyword(item.content_raw or "", keywords)
    source_channel = (
        getattr(item, "group_id", "")
        or metadata.get("bar_name")
        or metadata.get("group_name")
        or metadata.get("keyword")
        or keyword
        or ""
    )
    image_urls = list(getattr(item, "image_urls", []) or [])
    video_cover_url = getattr(item, "video_cover_url", "") or ""
    media_urls = image_urls + ([video_cover_url] if video_cover_url else [])

    metadata.update({
        "ui_collect": True,
        "keywords": keywords,
        "keyword": keyword,
        "group_id": getattr(item, "group_id", ""),
        "message_id": getattr(item, "message_id", None),
        "post_id": getattr(item, "post_id", ""),
        "like_count": int(getattr(item, "like_count", 0) or 0),
        "comment_count": int(getattr(item, "comment_count", 0) or 0),
        "share_count": int(getattr(item, "share_count", 0) or 0),
        "collect_count": int(getattr(item, "collect_count", 0) or 0),
        "tags": list(getattr(item, "tags", []) or []),
        "comments_count": len(getattr(item, "comments", []) or []),
        "price": float(getattr(item, "price", 0.0) or 0.0),
        "seller_rating": getattr(item, "seller_rating", ""),
        "location": getattr(item, "location", ""),
        "listing_status": getattr(item, "listing_status", ""),
    })

    return {
        "source_platform": getattr(item, "platform", "unknown") or "unknown",
        "source_channel": source_channel,
        "source_url": getattr(item, "source_url", "") or "",
        "source_keyword": keyword,
        "author_id": str(getattr(item, "author_uid", "") or ""),
        "author_name": getattr(item, "author_username", "") or "",
        "publish_time": getattr(item, "collected_at", None),
        "collect_time": datetime.now(),
        "content_type": getattr(item, "content_type", "text") or "text",
        "content_raw": getattr(item, "content_raw", "") or "",
        "media_urls": media_urls,
        "media_hash": _media_hash(media_urls),
        "crawl_batch_id": crawl_batch_id,
        "raw_status": "RAW_COLLECTED",
        "metadata": metadata,
    }


def _match_keyword(text: str, keywords: list[str]) -> str:
    """根据正文反推命中的搜索词，找不到则取第一个搜索词。"""
    for kw in keywords:
        if kw and kw in text:
            return kw
    return keywords[0] if keywords else ""


def _media_hash(media_urls: list[str]) -> str:
    if not media_urls:
        return ""
    joined = "|".join(str(url) for url in media_urls if url)
    return hashlib.md5(joined.encode("utf-8")).hexdigest() if joined else ""


# ── 页面入口 ────────────────────────────────────────────────────────────────

def show():
    page_header(
        "Collector Manager",
        "采集器管理",
        "管理7平台采集器：选择平台和关键词，一键触发采集，查看实时结果。",
    )

    service_strip()
    st.markdown("---")

    # ═════════════════════════════════════════════════════════════════════════
    # 平台总览卡片
    # ═════════════════════════════════════════════════════════════════════════

    st.markdown("### 平台总览")
    cols = st.columns(4)
    for i, (key, p) in enumerate(PLATFORMS.items()):
        with cols[i % 4]:
            cnt = _platform_count(key)
            st.markdown(
                f"""
                <div class='bagi-panel' style='padding:0.6rem 0.8rem;margin-bottom:0.5rem'>
                  <div style='display:flex;justify-content:space-between;align-items:center'>
                    <span style='font-size:1.1rem'>{p['icon']} <strong>{p['name']}</strong></span>
                    <span style='font-size:0.7rem;color:#92A1AF'>{p['cls']}</span>
                  </div>
                  <div style='font-size:0.7rem;color:#92A1AF;margin-top:0.3rem'>{p['tech']}</div>
                  <div style='font-size:0.68rem;margin-top:0.2rem'>⚡ {p['speed']}  📦 <strong>{cnt}</strong> 条</div>
                  <div style='font-size:0.62rem;color:#92A1AF'>🔑 {p['need']}</div>
                </div>
                """,
                unsafe_allow_html=True,
            )

    st.markdown("---")

    # ═════════════════════════════════════════════════════════════════════════
    # 快速采集
    # ═════════════════════════════════════════════════════════════════════════

    st.markdown("### 快速采集")

    c1, c2, c3 = st.columns([2, 2, 1])
    with c1:
        platform = st.selectbox(
            "目标平台",
            options=list(PLATFORMS.keys()),
            format_func=lambda k: f"{PLATFORMS[k]['icon']} {PLATFORMS[k]['name']}",
            key="collect_platform",
        )
    with c2:
        # 快捷按钮通过 _kw_clicked 传值，不与 text_input 的 key 冲突
        default_kw = st.session_state.pop("_kw_clicked", None) or DEMO_KEYWORDS[0]
        keyword = st.text_input(
            "搜索关键词（逗号分隔）",
            value=default_kw,
            key="collect_keyword",
        )
    with c3:
        max_pages = st.number_input("翻页数", min_value=1, max_value=5, value=1, key="collect_pages")

    # 快捷关键词（前2个是黑话，有词典释义；后3个是搜索主题词）
    slang_meaning = _load_slang_meanings()
    st.caption("演示关键词（悬停看说明）：")
    kw_cols = st.columns(len(DEMO_KEYWORDS))
    for i, kw in enumerate(DEMO_KEYWORDS):
        meaning = slang_meaning.get(kw, "")
        tip = meaning if meaning else "搜索主题词（非黑话）"
        if kw_cols[i].button(kw, key=f"quick_{kw}", help=tip, use_container_width=True):
            st.session_state["_kw_clicked"] = kw
            st.rerun()

    fetch_replies = False
    if platform in ("tieba",):
        fetch_replies = st.checkbox("采集回复", value=False, key="collect_replies")

    # ── 开始采集按钮 ──────────────────────────────────────────────────

    if st.button("开始采集", type="primary", use_container_width=True):
        keywords = [k.strip() for k in keyword.split(",") if k.strip()]
        if not keywords:
            st.error("请输入搜索关键词")
        else:
            with st.spinner(f"正在采集 {PLATFORMS[platform]['name']} · {', '.join(keywords)} ..."):
                results, logs = _do_collect(platform, keywords, max_pages, fetch_replies)
            st.session_state["last_results"] = results
            st.session_state["last_logs"] = logs
            st.session_state["last_platform"] = platform
            st.rerun()

    # ── 显示上次采集结果 ──────────────────────────────────────────────

    if st.session_state.get("last_results"):
        st.markdown("---")
        pname = PLATFORMS.get(st.session_state.get("last_platform", ""), {}).get("name", "")
        st.markdown(f"### 采集结果 · {pname}（{len(st.session_state['last_results'])} 条）")
        df = pd.DataFrame(st.session_state["last_results"])
        display_columns = ["情报ID", "平台", "频道", "内容", "作者", "点赞", "评论", "转发", "爬取时间", "链接"]
        for col in display_columns:
            if col not in df.columns:
                df[col] = "旧结果未记录" if col == "情报ID" else "-"
        st.dataframe(
            df[display_columns],
            hide_index=True,
            use_container_width=True,
            column_config={
                "情报ID": st.column_config.TextColumn("情报ID", width="small"),
                "内容": st.column_config.TextColumn("内容", width="large"),
                "链接": st.column_config.LinkColumn("链接", width="medium"),
            },
        )

    if st.session_state.get("last_logs"):
        with st.expander("采集日志", expanded=False):
            st.code("\n".join(st.session_state["last_logs"]), language=None)

    st.markdown("---")

    # ═════════════════════════════════════════════════════════════════════════
    # 依赖检查
    # ═════════════════════════════════════════════════════════════════════════

    st.markdown("### 运行环境检查")
    checks = _env_checks()
    check_cols = st.columns(len(checks))
    for i, (name, ok, detail) in enumerate(checks):
        with check_cols[i]:
            st.markdown(
                f"""
                <div class='bagi-panel' style='text-align:center;padding:0.6rem'>
                  <div style='font-size:1.5rem'>{"✅" if ok else "❌"}</div>
                  <div style='font-weight:600;margin-top:0.3rem'>{name}</div>
                  <div style='font-size:0.65rem;color:#92A1AF;margin-top:0.2rem'>{detail}</div>
                </div>
                """,
                unsafe_allow_html=True,
            )

# ── 辅助函数 ────────────────────────────────────────────────────────────────

@st.cache_data(ttl=300)
def _load_slang_meanings() -> dict[str, str]:
    """从数据库加载黑话词典，返回 {term: meaning} 映射。"""
    try:
        from storage.mysql_store import mysql
        with mysql.cursor() as c:
            c.execute(
                "SELECT term, normalized_meaning FROM dim_slang_dict WHERE status='active'"
            )
            return {r["term"]: (r["normalized_meaning"] or "") for r in c.fetchall()}
    except Exception:
        return {}


def _to_bj_time(dt) -> str:
    """UTC → 北京时间 (UTC+8)"""
    if dt is None:
        return ""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(BJT).strftime("%Y-%m-%d %H:%M:%S")


def _platform_count(platform: str) -> str:
    """从 MySQL 查 per-platform 计数，失败返回 '--'."""
    try:
        from storage.mysql_store import mysql
        with mysql.cursor() as c:
            c.execute(
                "SELECT COUNT(*) AS cnt FROM ods_raw_intel WHERE source_platform = %s",
                (platform,),
            )
            row = c.fetchone()
            return str(row["cnt"]) if row else "0"
    except Exception:
        return "--"


def _env_checks() -> list[tuple[str, bool, str]]:
    results = []
    results.append(("Python", True, f"{sys.version_info.major}.{sys.version_info.minor}"))
    import subprocess as sp
    try:
        r = sp.run(["docker", "info"], capture_output=True, timeout=10)
        results.append(("Docker", r.returncode == 0, "运行中" if r.returncode == 0 else "未启动"))
    except Exception:
        results.append(("Docker", False, "未检测到"))
    try:
        import urllib.request
        urllib.request.urlopen("http://localhost:3000/api/get_login_info", timeout=3)
        results.append(("NapCatQQ", True, "已连接"))
    except Exception:
        results.append(("NapCatQQ", False, "未启动"))
    try:
        from playwright.sync_api import sync_playwright  # noqa: F401
        results.append(("Playwright", True, "已安装"))
    except ImportError:
        results.append(("Playwright", False, "未安装"))
    try:
        from config.settings import settings
        ok = bool(settings.llm_api_key and len(str(settings.llm_api_key)) > 10)
        results.append(("LLM Key", ok, "已配置" if ok else "未配置"))
    except Exception:
        results.append(("LLM Key", False, "检查失败"))
    return results
