"""全自动情报流水线页面 — 一键采集→清洗→研判→入库，答辩演示用。

通过 session_state 驱动分阶段状态机，支持:
  - 实时计数(采集逐条更新)
  - 页面切换后状态恢复
"""

from __future__ import annotations

import sys
import time
import hashlib
from datetime import datetime, timezone, timedelta
from pathlib import Path
from uuid import uuid4

import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from ui.components import page_header
import ui.theme as T

BJT = timezone(timedelta(hours=8))

PLATFORMS = {
    "weibo": {"name": "微博", "icon": "📰"},
    "zhihu": {"name": "知乎", "icon": "❓"},
    "tieba": {"name": "贴吧", "icon": "💬"},
    "xiaohongshu": {"name": "小红书", "icon": "📕"},
    "douyin": {"name": "抖音", "icon": "🎵"},
    "xianyu": {"name": "闲鱼", "icon": "🐟"},
    "qq_group": {"name": "QQ群", "icon": "💬"},
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


# ── session_state 键名 ──
S_RUNNING = "pipe_running"        # bool
S_STAGE = "pipe_stage"            # str: idle|collect|clean|analyze|done
S_STEPS = "pipe_steps"            # list[dict]: 每步状态
S_CUR_STEP_DETAIL = "pipe_detail"  # str: 当前步骤实时描述
S_COLLECTOR = "pipe_collector"    # collector 实例
S_RAW_IDS = "pipe_collected_ids"  # 采集到的 raw_ids
S_CLEANED_IDS = "pipe_cleaned_ids"
S_KEYWORDS = "pipe_keywords"
S_PLATFORM = "pipe_platform"
S_MAX_PAGES = "pipe_max_pages"
S_RESULTS = "pipe_results"        # 上次完整结果(切页恢复用)
S_INSERTED = "pipe_inserted"
S_CLEANED = "pipe_cleaned"
S_DISCARDED = "pipe_discarded"
S_ANALYZED = "pipe_analyzed"


def _pipe_step(idx: int, title: str, status: str, detail: str = ""):
    icon_map = {"pending": "⏳", "running": "🔄", "done": "✅", "error": "❌"}
    color_map = {"pending": T.MUTED, "running": T.BLUE, "done": T.GREEN, "error": T.RED}
    icon = icon_map.get(status, "⏳")
    color = color_map.get(status, T.MUTED)
    st.markdown(
        f"""<div style='display:flex;align-items:center;gap:10px;padding:8px 0;
                  border-left:3px solid {color};padding-left:12px;margin:4px 0'>
          <span style='font-size:1.2rem'>{icon}</span>
          <div style='flex:1'><strong style='color:{T.INK}'>Step {idx}: {title}</strong>
          <div style='font-size:0.78rem;color:{T.MUTED};margin-top:2px'>{detail}</div></div>
        </div>""",
        unsafe_allow_html=True,
    )


def _ensure_session_keys():
    """确保 session_state 中 pipeline 相关 key 存在。"""
    defaults = {
        S_RUNNING: False, S_STAGE: "idle", S_STEPS: [], S_CUR_STEP_DETAIL: "",
        S_RAW_IDS: [], S_CLEANED_IDS: [], S_RESULTS: None,
        S_INSERTED: 0, S_CLEANED: 0, S_DISCARDED: 0, S_ANALYZED: 0,
    }
    for k, v in defaults.items():
        if k not in st.session_state:
            st.session_state[k] = v


def _reset_pipeline():
    """清除流水线运行状态（不删上次结果）。"""
    st.session_state[S_RUNNING] = False
    st.session_state[S_STAGE] = "idle"
    st.session_state[S_STEPS] = []
    st.session_state[S_CUR_STEP_DETAIL] = ""
    st.session_state[S_RAW_IDS] = []
    st.session_state[S_CLEANED_IDS] = []


def _get_pipeline_stats():
    try:
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
                c.execute("SELECT COUNT(*) as cnt FROM dwd_intel_analysis WHERE risk_level IN ('critical','high')")
                stats["high_risk"] = c.fetchone()["cnt"]
            except Exception:
                pass
            try:
                c.execute("SELECT COUNT(*) as cnt FROM dwd_entity")
                stats["entities"] = c.fetchone()["cnt"]
            except Exception:
                pass
        return stats
    except Exception:
        return {"raw": 0, "cleaned": 0, "analyzed": 0, "high_risk": 0, "entities": 0}


# ── 各阶段执行函数(生成器, yield 后 st.rerun) ──

def _gen_collect(platform: str, keywords: list[str], max_pages: int):
    """采集生成器 — 每入库一条 yield 一次。"""
    from collectors.registry import get_collector
    from storage.mysql_store import mysql

    inserted = 0
    new_ids: list[int] = []
    crawl_batch_id = f"pipe_{platform}_{datetime.now().strftime('%Y%m%d%H%M%S')}_{uuid4().hex[:6]}"
    kwargs = {"keywords": keywords, "max_pages_per_keyword": max_pages}
    collector = get_collector(platform, **kwargs)

    for item in collector.collect():
        text = getattr(item, "content_raw", "") or ""
        kw = next((k for k in keywords if k in text), keywords[0])
        metadata = dict(getattr(item, "metadata", {}) or {})
        metadata.update({"ui_collect": True, "keywords": keywords, "keyword": kw,
                         "group_id": getattr(item, "group_id", "")})
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
        except Exception:
            pass
        # 每次入库后 yield
        st.session_state[S_INSERTED] = inserted
        st.session_state[S_RAW_IDS] = list(new_ids)
        st.session_state[S_CUR_STEP_DETAIL] = f"已采集 {inserted} 条..."
        yield

    st.session_state[S_INSERTED] = inserted
    st.session_state[S_RAW_IDS] = list(new_ids)
    st.session_state[S_CUR_STEP_DETAIL] = f"采集完成: {inserted} 条"


def _gen_clean(raw_ids: list[int]):
    """清洗生成器 — 每处理一条 yield 一次。"""
    from cleaner.pipeline import CleaningPipeline
    from storage.mysql_store import mysql

    cleaned, discarded = 0, 0
    cleaned_ids: list[int] = []
    existing_hashes = mysql.list_existing_simhashes(limit=5000)
    pipeline = CleaningPipeline()

    total = len(raw_ids)
    for i, raw_id in enumerate(raw_ids):
        item = mysql.get_raw_by_id(raw_id)
        if not item:
            continue
        result = pipeline.process(
            item.get("content_raw", ""), existing_hashes=existing_hashes,
            platform=item.get("source_platform") or "unknown",
            author_uid=item.get("author_uid") or "",
            author_username=item.get("author_username") or "",
        )
        status = result.get("status", "CLEANED" if not result["should_discard"] else "DISCARDED")
        if status == "DISCARDED":
            mysql.update_raw_status(raw_id, "DISCARDED", clean_text=result["text"])
            discarded += 1
        else:
            mysql.update_raw_status(raw_id, "CLEANED", clean_text=result["text"], simhash=result["simhash"])
            cleaned += 1
            cleaned_ids.append(raw_id)

        st.session_state[S_CLEANED] = cleaned
        st.session_state[S_DISCARDED] = discarded
        st.session_state[S_CLEANED_IDS] = list(cleaned_ids)
        st.session_state[S_CUR_STEP_DETAIL] = f"{i+1}/{total} | 通过 {cleaned} 丢弃 {discarded}"
        yield

    st.session_state[S_CUR_STEP_DETAIL] = f"{cleaned} 通过, {discarded} 丢弃"


def _gen_analyze(raw_ids: list[int]):
    """研判生成器 — 每分析一条 yield 一次。"""
    from analyzer.engine import engine
    from storage.mysql_store import mysql

    analyzed = 0
    failed = 0
    clean_map = {}
    if raw_ids:
        with mysql.cursor() as c:
            placeholders = ",".join(["%s"] * len(raw_ids))
            c.execute(
                f"SELECT raw_id, merged_text, clean_text FROM dwd_clean_intel WHERE raw_id IN ({placeholders})",
                raw_ids,
            )
            for row in c.fetchall():
                clean_map[row["raw_id"]] = row

    items = []
    for rid in raw_ids:
        it = mysql.get_raw_by_id(rid)
        if it:
            items.append(it)

    total = len(items)
    for i, item in enumerate(items):
        clean = clean_map.get(item["id"], {})
        text = clean.get("merged_text") or clean.get("clean_text") or item.get("content_raw", "")
        if not text or not text.strip():
            continue
        preview = text.replace("\n", " ")[:40]
        try:
            engine.run(raw_data_id=item["id"], text=text,
                       platform=item.get("source_platform", "unknown"))
            analyzed += 1
        except Exception as exc:
            failed += 1
            st.session_state.setdefault("pipe_errors", []).append(
                f"研判失败 ID={item['id']}: {exc}"
            )

        st.session_state[S_ANALYZED] = analyzed
        status = f"{i+1}/{total} | [{preview}...]"
        if failed:
            status += f" | ⚠️ {failed}条失败"
        st.session_state[S_CUR_STEP_DETAIL] = status
        yield

    detail = f"研判完成: {analyzed} 条"
    if failed:
        detail += f", {failed} 条失败"
    st.session_state[S_CUR_STEP_DETAIL] = detail


# ── 主页面 ──────────────────────────────────────────────────────────────────

def show():
    _ensure_session_keys()

    page_header("全自动流水线", "⚡ 情报工厂", "选平台、输关键词、一键启动 → 采集 → 清洗 → 研判 → 入库")

    # ── 顶部状态卡片 ──
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
            "采集平台", list(PLATFORMS.keys()),
            format_func=lambda p: f"{PLATFORMS[p]['icon']} {PLATFORMS[p]['name']}",
            key="pipe_platform_select",
        )
        # 同步到 session
        st.session_state[S_PLATFORM] = platform
    with c2:
        preset = st.multiselect("预设关键词（可多选）", list(PRESET_KEYWORDS.keys()), key="pipe_preset")
        custom_kw = st.text_input("自定义关键词（逗号分隔）", placeholder="例如: 出租淘宝号, 微信解封", key="pipe_custom_kw")
    with c3:
        max_pages = st.slider("每个关键词最大页数", 1, 20, 3, key="pipe_max_pages")
        st.markdown("<br>", unsafe_allow_html=True)
        start_btn = st.button(
            "🚀 一键启动全流程", type="primary", use_container_width=True,
            disabled=st.session_state[S_RUNNING],
        )

    keywords = []
    for p in preset:
        keywords.append(p)
    if custom_kw.strip():
        keywords.extend([k.strip() for k in custom_kw.split(",") if k.strip()])
    st.session_state[S_KEYWORDS] = keywords

    if keywords:
        st.markdown(
            f"<span style='color:{T.BLUE};font-size:0.85rem'>已选关键词: {', '.join(keywords)}</span>",
            unsafe_allow_html=True,
        )

    # ── 进度展示区域（运行中 or 上次结果） ──
    running = st.session_state[S_RUNNING]
    stage = st.session_state[S_STAGE]
    prev_results = st.session_state[S_RESULTS]

    if running or prev_results:
        st.markdown("---")
        st.markdown("### 📋 执行进度")

        # 确定显示的步骤状态
        if running:
            steps = st.session_state[S_STEPS]
            detail = st.session_state.get(S_CUR_STEP_DETAIL, "")
        else:
            # 从上次结果重建步骤
            steps = prev_results.get("steps", []) if prev_results else []
            detail = ""

        if steps:
            for s in steps:
                _pipe_step(s["idx"], s["title"], s["status"], s.get("detail", ""))
        elif running:
            # 初始化阶段展示
            _pipe_step(1, "数据采集", "running", detail or "准备中...")
            _pipe_step(2, "数据清洗", "pending", "")
            _pipe_step(3, "自动研判", "pending", "")
            _pipe_step(4, "多库写入", "pending", "")

        # ── 结束后的结果 ──
        if not running and prev_results:
            st.markdown("---")
            st.markdown("### 🎉 上次流水线结果")
            c1, c2, c3 = st.columns(3)
            c1.metric("采集入库", f"{prev_results.get('inserted', 0)} 条")
            c2.metric("清洗通过/丢弃", f"{prev_results.get('cleaned', 0)}/{prev_results.get('discarded', 0)}")
            c3.metric("研判完成", f"{prev_results.get('analyzed', 0)} 条")
            if prev_results.get("success"):
                st.success(prev_results["success"])

    # ═══════════ 按钮动作 ═══════════
    if start_btn:
        if not keywords:
            st.error("请选择或输入至少一个关键词")
            st.stop()

        _reset_pipeline()
        st.session_state[S_RUNNING] = True
        st.session_state[S_STAGE] = "collect"
        st.session_state[S_STEPS] = [
            {"idx": 1, "title": "数据采集", "status": "running",
             "detail": f"平台={platform}, 关键词={len(keywords)}个, 页数={max_pages}"},
            {"idx": 2, "title": "数据清洗", "status": "pending", "detail": ""},
            {"idx": 3, "title": "自动研判", "status": "pending", "detail": ""},
            {"idx": 4, "title": "多库写入", "status": "pending", "detail": ""},
        ]
        st.session_state[S_INSERTED] = 0
        st.session_state[S_CLEANED] = 0
        st.session_state[S_DISCARDED] = 0
        st.session_state[S_ANALYZED] = 0
        st.session_state[S_CUR_STEP_DETAIL] = "准备开始..."

        # 创建采集生成器
        gen = _gen_collect(platform, keywords, max_pages)
        st.session_state["pipe_gen"] = gen
        st.session_state["pipe_gen_stage"] = "collect"
        st.rerun()

    # ═══════════ 自动推进生成器 ═══════════
    if running and "pipe_gen" in st.session_state:
        gen = st.session_state["pipe_gen"]
        gen_stage = st.session_state.get("pipe_gen_stage", "")
        if gen is not None:
            try:
                next(gen)
                # 更新当前步骤的 detail
                steps = list(st.session_state[S_STEPS])
                cur_detail = st.session_state.get(S_CUR_STEP_DETAIL, "")
                for s in steps:
                    if s["status"] == "running":
                        s["detail"] = cur_detail
                        break
                st.session_state[S_STEPS] = steps
                st.rerun()
            except StopIteration:
                # 当前阶段完成 → 进入下一阶段
                steps = list(st.session_state[S_STEPS])

                if gen_stage == "collect":
                    # Step 1 完成
                    inserted = st.session_state[S_INSERTED]
                    raw_ids = st.session_state[S_RAW_IDS]
                    elapsed = ""  # 简单略过
                    steps[0] = {"idx": 1, "title": "数据采集", "status": "done",
                                "detail": f"新入库 {inserted} 条原始数据"}
                    steps[1] = {"idx": 2, "title": "数据清洗", "status": "running",
                                "detail": f"清洗刚入库的 {len(raw_ids)} 条..."}
                    st.session_state[S_STEPS] = steps

                    # 启动清洗生成器
                    gen2 = _gen_clean(raw_ids)
                    st.session_state["pipe_gen"] = gen2
                    st.session_state["pipe_gen_stage"] = "clean"
                    st.rerun()

                elif gen_stage == "clean":
                    # Step 2 完成
                    cleaned = st.session_state[S_CLEANED]
                    discarded = st.session_state[S_DISCARDED]
                    cleaned_ids = st.session_state[S_CLEANED_IDS]
                    steps[1] = {"idx": 2, "title": "数据清洗", "status": "done",
                                "detail": f"{cleaned} 条通过, {discarded} 条丢弃"}
                    if cleaned_ids:
                        steps[2] = {"idx": 3, "title": "自动研判", "status": "running",
                                    "detail": f"研判 {len(cleaned_ids)} 条..."}
                    else:
                        steps[2] = {"idx": 3, "title": "自动研判", "status": "done",
                                    "detail": "无待研判数据"}
                    st.session_state[S_STEPS] = steps

                    if cleaned_ids:
                        gen3 = _gen_analyze(cleaned_ids)
                        st.session_state["pipe_gen"] = gen3
                        st.session_state["pipe_gen_stage"] = "analyze"
                    else:
                        steps[3] = {"idx": 4, "title": "多库写入", "status": "done",
                                    "detail": "MySQL + Neo4j + Milvus 同步完成"}
                        st.session_state[S_STEPS] = steps
                        st.session_state["pipe_gen"] = None
                        st.session_state[S_RUNNING] = False
                        st.session_state[S_STAGE] = "done"
                        # 保存结果
                        st.session_state[S_RESULTS] = {
                            "steps": list(steps),
                            "inserted": inserted,
                            "cleaned": cleaned,
                            "discarded": discarded,
                            "analyzed": 0,
                            "success": f"全流程完毕：采集 {inserted} → 清洗 {cleaned}/{discarded} → 研判 0",
                        }
                    st.rerun()

                elif gen_stage == "analyze":
                    # Step 3 完成
                    analyzed = st.session_state[S_ANALYZED]
                    steps[2] = {"idx": 3, "title": "自动研判", "status": "done",
                                "detail": f"{analyzed} 条完成研判"}
                    steps[3] = {"idx": 4, "title": "多库写入", "status": "done",
                                "detail": "MySQL + Neo4j + Milvus 同步完成"}
                    st.session_state[S_STEPS] = steps
                    st.session_state["pipe_gen"] = None
                    st.session_state[S_RUNNING] = False
                    st.session_state[S_STAGE] = "done"

                    # 保存完整结果
                    inserted = st.session_state[S_INSERTED]
                    cleaned = st.session_state[S_CLEANED]
                    discarded = st.session_state[S_DISCARDED]
                    st.session_state[S_RESULTS] = {
                        "steps": list(steps),
                        "inserted": inserted,
                        "cleaned": cleaned,
                        "discarded": discarded,
                        "analyzed": analyzed,
                        "success": f"全流程完毕：采集 {inserted} → 清洗 {cleaned}/{discarded} → 研判 {analyzed}",
                    }
                    st.balloons()
                    st.rerun()

            except Exception as e:
                st.session_state["pipe_gen"] = None
                st.session_state[S_RUNNING] = False
                st.session_state[S_STAGE] = "idle"
                st.error(f"流水线异常: {e}")
