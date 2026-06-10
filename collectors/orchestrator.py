"""Multi-platform concurrent collection orchestrator.

Manages concurrent data collection across all platforms with:
- One thread per platform (parallel keyword search)
- Token-bucket rate limiting (per-platform)
- Progress tracking and periodic reporting
- Checkpoint resume integration (using existing BaseSpider checkpoint infra)
- Graceful shutdown on SIGINT (Ctrl+C)

(Telegram/Telethon 已于 2026-06-04 移除)
"""

from __future__ import annotations

import json as _json
import signal
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from loguru import logger

from config.settings import settings


class SpiderType(Enum):
    PLAYWRIGHT = "playwright"   # Browser-based: tieba, zhihu, douyin, xiaohongshu, xianyu
    HTTP = "http"               # Pure requests: weibo


# ═══════════════════════════════════════════════════════════════════════════════
# Data structures
# ═══════════════════════════════════════════════════════════════════════════════

@dataclass
class PlatformTask:
    """Single-platform collection configuration."""
    platform: str
    keywords: list[str]
    spider_type: SpiderType
    max_pages: int = 10
    max_items: int = 0
    fetch_replies: bool = True
    incremental: bool = False
    headless: bool = True
    resume_from_checkpoint: bool = True
    requests_per_minute: int = 20
    pass


# ═══════════════════════════════════════════════════════════════════════════════
# Rate Limiter (token bucket, thread-safe)
# ═══════════════════════════════════════════════════════════════════════════════

class RateLimiter:
    """Token-bucket rate limiter.

    Limits the *start* of a new keyword search to at most ``rpm`` calls per
    minute.  The spider's own ``_adaptive_delay`` handles per-page pacing.
    """

    def __init__(self, rpm: int):
        self._rate = rpm / 60.0  # tokens per second
        self._tokens = float(rpm)
        self._last_refill = time.monotonic()
        self._lock = threading.Lock()

    def acquire(self) -> float:
        """Block until a token is available.  Returns seconds waited."""
        with self._lock:
            now = time.monotonic()
            elapsed = now - self._last_refill
            # Refill
            self._tokens = min(self._rate * 60, self._tokens + elapsed * self._rate)
            self._last_refill = now

            if self._tokens >= 1.0:
                self._tokens -= 1.0
                return 0.0

            # Need to wait
            wait = (1.0 - self._tokens) / self._rate
            self._tokens = 0.0  # consume the upcoming token

        time.sleep(wait)
        return wait


# ═══════════════════════════════════════════════════════════════════════════════
# Progress Tracker (thread-safe)
# ═══════════════════════════════════════════════════════════════════════════════

class ProgressTracker:
    """Real-time, thread-safe collection statistics."""

    def __init__(self):
        self._lock = threading.Lock()
        self.start_time = time.time()
        self.platforms: dict[str, dict] = {}
        self._total_items = 0
        self._total_errors = 0

    def update(self, platform: str, /, *, items_delta: int = 0,
               errors_delta: int = 0, keyword: str = "", status: str = "") -> None:
        """Atomically update statistics for a platform."""
        with self._lock:
            p = self.platforms.setdefault(platform, {
                "items": 0, "errors": 0, "keyword": "", "status": "pending",
            })
            p["items"] += items_delta
            p["errors"] += errors_delta
            if keyword:
                p["keyword"] = keyword
            if status:
                p["status"] = status
            self._total_items += items_delta
            self._total_errors += errors_delta

    def snapshot(self) -> dict:
        """Return a point-in-time snapshot of all statistics."""
        with self._lock:
            elapsed = time.time() - self.start_time
            return {
                "elapsed_sec": round(elapsed, 1),
                "total_items": self._total_items,
                "total_errors": self._total_errors,
                "items_per_sec": round(
                    self._total_items / elapsed if elapsed > 0 else 0, 2),
                "platforms": {
                    k: dict(v) for k, v in self.platforms.items()
                },
            }


# ═══════════════════════════════════════════════════════════════════════════════
# Collection Orchestrator
# ═══════════════════════════════════════════════════════════════════════════════

class CollectionOrchestrator:
    """Central orchestrator for multi-platform concurrent collection.

    Usage::

        tasks = [PlatformTask(platform="weibo", keywords=["刷单"], ...), ...]
        orch = CollectionOrchestrator(tasks, write_pipeline)
        final_stats = orch.run_all()
    """

    def __init__(self, tasks: list[PlatformTask],
                 write_pipeline,  # ConcurrentWritePipeline
                 stats_interval: float = 5.0):
        self.tasks = tasks
        self._write = write_pipeline
        self._stats_interval = stats_interval
        self.progress = ProgressTracker()
        self._rate_limiters = {
            t.platform: RateLimiter(t.requests_per_minute) for t in tasks
        }
        self._shutdown = threading.Event()

    # ── public entry point ───────────────────────────────────────────────

    def run_all(self) -> dict:
        """Launch all platform threads, monitor, handle graceful shutdown.

        Returns the final stats snapshot.
        """
        threads: list[threading.Thread] = []
        for task in self.tasks:
            t = threading.Thread(
                target=self._run_platform, args=(task),
                name=f"collect-{task.platform}", daemon=True)
            t.start()
            threads.append(t)

        # Graceful shutdown on Ctrl+C
        original_handler = signal.getsignal(signal.SIGINT)
        def _handle_sigint(sig, frame):
            logger.warning("Ctrl+C received — initiating graceful shutdown...")
            self._shutdown.set()
            if original_handler and original_handler not in (
                signal.SIG_DFL, signal.SIG_IGN
            ):
                try:
                    original_handler(sig, frame)
                except Exception:
                    pass
        signal.signal(signal.SIGINT, _handle_sigint)

        # Progress reporter (periodic)
        reporter = threading.Thread(target=self._report_loop, daemon=True)
        reporter.start()

        # Wait for all platform threads
        for t in threads:
            while t.is_alive():
                t.join(timeout=1.0)

        self._shutdown.set()
        reporter.join(timeout=2)

        # Restore original signal handler
        signal.signal(signal.SIGINT, original_handler)

        return self.progress.snapshot()

    def _report_loop(self) -> None:
        """Periodically log collection progress."""
        while not self._shutdown.wait(timeout=self._stats_interval):
            snap = self.progress.snapshot()
            parts = [
                f"{p}:{d['items']}it/{d['status'][:8]}"
                for p, d in snap["platforms"].items()
            ]
            logger.info(
                "[Collector] {} items | {:.1f}/s | {}",
                snap["total_items"],
                snap["items_per_sec"],
                " | ".join(parts))

    # ── platform dispatch ────────────────────────────────────────────────

    def _run_platform(self, task: PlatformTask) -> None:
        """Entry point for one platform thread."""
        try:
            if task.spider_type == SpiderType.PLAYWRIGHT:
                self._run_playwright(task)
            elif task.spider_type == SpiderType.HTTP:
                self._run_http(task)
            else:
                logger.error("[{}] Unknown spider type", task.platform)
            self.progress.update(task.platform, status="completed")
        except Exception as exc:
            logger.error("[{}] Fatal: {}", task.platform, exc, exc_info=True)
            self.progress.update(task.platform, status="failed", errors_delta=1)

    # ── Playwright path (tieba / zhihu / douyin / xiaohongshu) ──────────

    def _run_playwright(self, task: PlatformTask) -> None:
        spider = _make_playwright_spider(task)
        if spider is None:
            self.progress.update(task.platform, status="error(no spider)")
            return
        limiter = self._rate_limiters[task.platform]
        try:
            spider.start()
            for kw in task.keywords:
                if self._shutdown.is_set():
                    logger.info("[{}] Shutdown — stopping before [{}]", task.platform, kw)
                    break

                self.progress.update(task.platform, keyword=kw, status="collecting")

                # ── Checkpoint resume ──
                start_page = 1
                if task.resume_from_checkpoint:
                    ck = spider._checkpoint.get(kw, {})
                    start_page = ck.get("page", 1)
                    if start_page > 1:
                        logger.info(
                            "[{}] Resuming [{}] from page {} (had {} items)",
                            task.platform, kw, start_page,
                            ck.get("collected_total", 0))

                # Rate-limit keyword start
                limiter.acquire()

                items = spider.search_and_parse(
                    kw,
                    max_pages=task.max_pages,
                    max_items=task.max_items,
                    incremental=task.incremental,
                    start_page=start_page,
                    checkpoint_callback=spider._update_checkpoint)

                for parsed in items:
                    if self._shutdown.is_set():
                        break
                    self._write.enqueue(_parsed_to_dict(parsed, task.platform))
                    self.progress.update(task.platform, items_delta=1)

                # Keyword done — clear checkpoint
                spider._clear_checkpoint(kw)
                if task.incremental:
                    spider._update_last_collected(kw, now_bjt())

        finally:
            try:
                spider.close()
            except Exception:
                pass

    # ── HTTP path (weibo / zhihu / xiaohongshu) ──────────────────────────

    def _run_http(self, task: PlatformTask) -> None:
        p = task.platform
        if p == "weibo":
            self._run_http_weibo(task)
        elif p == "zhihu":
            self._run_http_zhihu(task)
        elif p == "xiaohongshu":
            self._run_http_xhs(task)
        else:
            logger.error("[{}] Unknown HTTP platform", p)

    def _run_http_weibo(self, task: PlatformTask) -> None:
        from collectors.spiders.weibo_api_spider import WeiboAPISpider

        spider = WeiboAPISpider()
        limiter = self._rate_limiters[task.platform]
        try:
            for kw in task.keywords:
                if self._shutdown.is_set():
                    break
                self.progress.update(task.platform, keyword=kw, status="collecting")
                limiter.acquire()
                parsed_items = spider.search(kw, max_pages=task.max_pages)
                for p in parsed_items:
                    if self._shutdown.is_set():
                        break
                    self._write.enqueue(_parsed_to_dict(p, "weibo"))
                    self.progress.update(task.platform, items_delta=1)

                    # 采集评论
                    if task.fetch_replies and p.comments_count > 0:
                        try:
                            comments = spider.get_comments(p.weibo_id, max_pages=2)
                            for c in comments:
                                if self._shutdown.is_set():
                                    break
                                self._write.enqueue(_comment_to_dict(
                                    c, "weibo", parent_id=p.weibo_id,
                                    keyword=kw, parent_url=p.source_url))
                                self.progress.update(task.platform, items_delta=1)
                        except Exception:
                            pass
        finally:
            if hasattr(spider, "_session") and spider._session:
                try:
                    spider._session.close()
                except Exception:
                    pass

    def _run_http_zhihu(self, task: PlatformTask) -> None:
        from collectors.spiders.zhihu_api_spider import ZhihuAPISpider

        spider = ZhihuAPISpider(
            fetch_answers=task.fetch_replies,
            fetch_comments=task.fetch_replies)
        limiter = self._rate_limiters[task.platform]
        try:
            for kw in task.keywords:
                if self._shutdown.is_set():
                    break
                self.progress.update(task.platform, keyword=kw, status="collecting")
                limiter.acquire()
                parsed_items = spider.search(kw, max_pages=task.max_pages)
                for p in parsed_items:
                    if self._shutdown.is_set():
                        break
                    self._write.enqueue(_parsed_to_dict(p, "zhihu"))
                    self.progress.update(task.platform, items_delta=1)
        finally:
            if hasattr(spider, "_session") and spider._session:
                try:
                    spider._session.close()
                except Exception:
                    pass

    def _run_http_xhs(self, task: PlatformTask) -> None:
        # Fallback to Playwright Xiaohongshu spider for now
        # (pure-HTTP version requires X-s/X-t signing)
        self._run_playwright(task)

# ═══════════════════════════════════════════════════════════════════════════════
# Helpers — item-to-dict conversion
# ═══════════════════════════════════════════════════════════════════════════════

def _parsed_to_dict(parsed, platform: str) -> dict:
    """Convert any Parsed*Item dataclass to INSERT dict for ods_raw_intel.

    All Parsed*Item dataclasses share the same core fields
    (content_raw, source_url, author_uid, author_username, collected_at,
     keyword, metadata).  We use getattr for safe access.
    """
    return {
        "source_platform": platform,
        "source_url": getattr(parsed, "source_url", ""),
        "source_channel": _source_channel(parsed, platform),
        "source_keyword": getattr(parsed, "keyword", ""),
        "author_id": str(getattr(parsed, "author_uid", "")),
        "author_name": getattr(parsed, "author_username", ""),
        "content_type": getattr(parsed, "content_type", "text"),
        "content_raw": getattr(parsed, "content_raw", ""),
        "publish_time": getattr(parsed, "collected_at", None),
        "collect_time": now_bjt(),
        "raw_status": "RAW_COLLECTED",
        "media_urls": _json.dumps(_collect_media_urls(parsed), ensure_ascii=False),
        "media_hash": _compute_media_hash(parsed),
        "crawl_batch_id": "",
        "metadata": _json.dumps(
            _build_metadata(parsed, platform),
            ensure_ascii=False, default=str),
    }


def _source_channel(parsed, platform: str) -> str:
    """Extract source_channel (group/forum) from parsed item."""
    # tieba uses bar_name
    if platform == "tieba":
        return getattr(parsed, "bar_name", "")
    # Others use group_id or keyword inside metadata
    meta = getattr(parsed, "metadata", {}) or {}
    return meta.get("keyword", getattr(parsed, "keyword", ""))


def _build_metadata(parsed, platform: str) -> dict:
    """Build enriched metadata dict with platform-specific fields."""
    base = dict(getattr(parsed, "metadata", {}) or {})

    # Always record keyword & platform ids
    base.setdefault("keyword", getattr(parsed, "keyword", ""))

    # Platform-specific IDs
    if hasattr(parsed, "thread_id"):
        base.setdefault("thread_id", parsed.thread_id)
    if hasattr(parsed, "weibo_id"):
        base.setdefault("weibo_id", parsed.weibo_id)
    if hasattr(parsed, "question_id"):
        base.setdefault("question_id", parsed.question_id)
    if hasattr(parsed, "note_id"):
        base.setdefault("note_id", parsed.note_id)
    if hasattr(parsed, "aweme_id"):
        base.setdefault("aweme_id", parsed.aweme_id)
    if hasattr(parsed, "bar_name"):
        base.setdefault("bar_name", parsed.bar_name)

    # Engagement stats
    for key in ("reply_count", "reposts_count", "comments_count",
                "attitudes_count", "voteup_count", "like_count",
                "collect_count", "share_count", "comment_count",
                "play_count", "duration"):
        val = getattr(parsed, key, None)
        if val is not None and val != 0:
            base.setdefault(key, val)

    # Lists
    for key in ("topics", "tags", "image_list", "hashtags"):
        val = getattr(parsed, key, None)
        if val:
            base.setdefault(key, val)

    return base


def _collect_media_urls(parsed) -> list[str]:
    """Gather all media URLs from a parsed item (image_list + video_cover)."""
    urls = []
    # image_list from xiaohongshu, douyin 图集
    for key in ("image_list", "image_urls"):
        val = getattr(parsed, key, None)
        if isinstance(val, list):
            urls.extend(v for v in val if isinstance(v, str) and v)
    # video_cover from douyin
    cover = getattr(parsed, "video_cover_url", "")
    if cover and isinstance(cover, str) and cover not in urls:
        urls.append(cover)
    return urls


def _compute_media_hash(parsed) -> str:
    """Compute a short content hash from media URLs for dedup purposes."""
    urls = _collect_media_urls(parsed)
    if not urls:
        return ""
    import hashlib
    return hashlib.md5("|".join(sorted(urls)).encode()).hexdigest()[:12]


def _comment_to_dict(comment: dict, platform: str, *,
                     parent_id: str = "", keyword: str = "",
                     parent_url: str = "") -> dict:
    """Convert a single comment/reply dict to INSERT dict (as separate IntelItem)."""
    text = comment.get("text_raw", "") or comment.get("text", "") or comment.get("content", "")
    author = comment.get("user", {}) or comment.get("author", {}) or {}
    if isinstance(author, dict):
        uid = str(author.get("id", "") or author.get("user_id", ""))
        name = author.get("screen_name", "") or author.get("name", "") or author.get("nickname", "")
    else:
        uid, name = "", ""

    return {
        "source_platform": platform,
        "source_url": f"{parent_url}#comment_{comment.get('id', '')}" if parent_url else "",
        "source_channel": keyword,
        "source_keyword": keyword,
        "author_id": uid,
        "author_name": name,
        "content_type": "comment",
        "content_raw": text,
        "publish_time": comment.get("created_at") or comment.get("created_time"),
        "collect_time": now_bjt(),
        "raw_status": "RAW_COLLECTED",
        "media_urls": _json.dumps([]),
        "media_hash": "",
        "crawl_batch_id": "",
        "metadata": _json.dumps({
            "parent_id": parent_id,
            "comment_id": str(comment.get("id", "")),
            "keyword": keyword,
            "like_count": comment.get("like_counts", 0) or comment.get("like_count", 0) or comment.get("voteup_count", 0),
            "is_comment": True,
        }, ensure_ascii=False, default=str),
    }



# ═══════════════════════════════════════════════════════════════════════════════
# Spider factory
# ═══════════════════════════════════════════════════════════════════════════════

def _make_playwright_spider(task: PlatformTask):
    """Create the appropriate Playwright-based spider for a platform."""
    p = task.platform
    if p == "tieba":
        from collectors.spiders.tieba_spider import TiebaSpider
        return TiebaSpider(headless=task.headless)
    elif p == "zhihu":
        from collectors.spiders.zhihu_spider import ZhihuSearchSpider
        return ZhihuSearchSpider(headless=task.headless,
                                 fetch_answers=task.fetch_replies,
                                 fetch_comments=task.fetch_replies)
    elif p == "douyin":
        from collectors.spiders.douyin_spider import DouyinSearchSpider
        return DouyinSearchSpider(headless=task.headless)
    elif p == "xiaohongshu":
        from collectors.spiders.xiaohongshu_spider import XiaohongshuSearchSpider
        return XiaohongshuSearchSpider(headless=task.headless)
    elif p == "xianyu":
        from collectors.spiders.xianyu_spider import XianyuSearchSpider
        return XianyuSearchSpider(headless=False)  # 闲鱼强制非headless
    else:
        logger.error("Unknown Playwright platform: {}", p)
        return None
