"""
小红书关键词搜索 Spider（Playwright + API 拦截 + DOM 兜底）

核心策略:
  1. 优先拦截 XHR 搜索 API 获取结构化 JSON（/api/sns/web/v1/search/notes）
  2. 兜底 DOM 解析搜索结果卡片
  3. Playwright stealth 反检测

反爬要点:
  - Cookie 注入（web_session / a1 / websectiga）
  - navigator.webdriver 隐藏
  - 随机 UA 轮换
  - 自适应请求间隔
  - 首页预热建立会话

小红书搜索 API 说明:
  - 搜索页 URL: https://www.xiaohongshu.com/search_result?keyword={keyword}
  - 搜索 API: POST /api/sns/web/v1/search/notes
  - 需要 X-s / X-t / X-s-common 签名头（浏览器内 fetch 自动携带）
"""

import time
import json
import re
import random
from datetime import datetime
from dataclasses import dataclass, field
from urllib.parse import quote
from loguru import logger

from collectors.spiders.base_spider import BaseSpider, random_ua


# ── 解析结果结构 ──────────────────────────────────────────────────────────────

@dataclass
class ParsedXiaohongshuItem:
    """小红书搜索结果条目。"""
    platform: str = "xiaohongshu"
    content_raw: str = ""
    content_type: str = "text"
    source_url: str = ""
    author_uid: str = ""
    author_username: str = ""
    note_id: str = ""
    collected_at: datetime = field(default_factory=datetime.utcnow)
    keyword: str = ""
    like_count: int = 0
    collect_count: int = 0
    comment_count: int = 0
    tags: list[str] = field(default_factory=list)
    image_list: list[str] = field(default_factory=list)
    metadata: dict = field(default_factory=dict)


# ── Spider ─────────────────────────────────────────────────────────────────────

class XiaohongshuSearchSpider(BaseSpider):
    """小红书搜索 Spider — API 拦截 + DOM 兜底。"""

    PLATFORM = "xiaohongshu"
    HOME_URL = "https://www.xiaohongshu.com"
    SEARCH_URL = "https://www.xiaohongshu.com/search_result"
    # 新版搜索 API（2024+）
    SEARCH_API = "/api/sns/web/v1/search/notes"
    PAGE_SIZE = 20
    MIN_DELAY = 4.0     # 最小请求间隔（提高到4秒避免频率检测）
    MAX_DELAY = 8.0     # 最大请求间隔（提高到8秒模拟人工浏览）
    MAX_RETRIES = 3

    def __init__(self, headless: bool = True):
        super().__init__(headless)
        self._api_responses: list[dict] = []       # API 拦截缓存
        self._api_capture_enabled = False

    # ═══════════════════════════════════════════════════════════════════════════
    # Cookie 注入（小红书需要 web_session + a1）
    # ═══════════════════════════════════════════════════════════════════════════

    def _inject_cookies(self):
        """注入小红书 Cookie（优先环境变量，文件兜底，支持 JS 注入方式）。"""
        cookies = self.load_cookies(self.PLATFORM)
        if not cookies:
            logger.warning(
                f"未配置 {self.PLATFORM} Cookie"
                f"（环境变量 BGI_{self.PLATFORM.upper()}_COOKIES 或文件），搜索可能受限"
            )
            return

        try:
            # 标准化并注入
            clean = []
            js_cookies = []  # 需要 JS 注入的 HttpOnly cookies
            for c in cookies:
                c_clean = {
                    "name": c.get("name", ""),
                    "value": str(c.get("value", "")),
                    "domain": c.get("domain", ""),
                    "path": c.get("path", "/"),
                }
                if not c_clean["name"] or not c_clean["domain"]:
                    continue
                for src, dst in [("httpOnly", "httpOnly"), ("secure", "secure")]:
                    if c.get(src):
                        c_clean[dst] = True
                ss = c.get("sameSite")
                if ss == "no_restriction":
                    c_clean["sameSite"] = "None"
                elif ss in ("Strict", "Lax", "None"):
                    c_clean["sameSite"] = ss
                if c.get("expirationDate"):
                    c_clean["expires"] = float(c["expirationDate"])
                clean.append(c_clean)
            self._context.add_cookies(clean)
            self._logged_in = True
            logger.info(f"已注入 {len(clean)} 条 {self.PLATFORM} Cookie")

            # 补充 JS 注入（解决 add_cookies 对某些 domain 无效的问题）
            js_cookie_str = "; ".join(
                f"{c['name']}={c['value']}"
                for c in clean
                if c["name"] in ("web_session", "a1", "websectiga", "acw_tc")
            )
            if js_cookie_str and self._page:
                self._page.add_init_script(
                    f"document.cookie = '{js_cookie_str}; path=/; domain=.xiaohongshu.com';"
                )
        except Exception as exc:
            logger.warning(f"Cookie 注入失败 ({len(cookies)} cookies): {exc}")

    # ═══════════════════════════════════════════════════════════════════════════
    # API 拦截（优先获取结构化数据）
    # ═══════════════════════════════════════════════════════════════════════════

    def _setup_request_interception(self):
        """拦截 XHR 请求，捕获搜索 API 响应。"""
        if not self._page:
            return

        def _on_response(response):
            """捕获搜索 API 的响应。"""
            if not self._api_capture_enabled:
                return
            url = response.url
            if "/api/sns/web/v1/search/notes" in url or "/api/sns/web/v1/search" in url:
                try:
                    body = response.json()
                    if body and body.get("success", False):
                        self._api_responses.append(body)
                        logger.debug(f"  拦截到搜索 API 响应: {len(body.get('data',{}).get('items',[]))} 条")
                except Exception:
                    pass

        # 只拦截关键 XHR
        self._page.on("response", _on_response)

    # ═══════════════════════════════════════════════════════════════════════════
    # 搜索入口
    # ═══════════════════════════════════════════════════════════════════════════

    def search_and_parse(
        self, keyword: str, max_pages: int = 3, **kwargs
    ) -> list[ParsedXiaohongshuItem]:
        if not self._page:
            raise RuntimeError("Spider 未启动，请先调用 start()")

        # 检查登录状态
        if not self._check_login():
            logger.error("未登录或登录已过期，请运行: python login_edge.py xiaohongshu")
            return []

        max_items = kwargs.get("max_items", 0)
        use_incremental = kwargs.get("incremental", False)
        start_page = kwargs.get("start_page", 1)
        checkpoint_cb = kwargs.get("checkpoint_callback")
        all_items = []
        consecutive_empty = 0

        for page_num in range(start_page, max_pages + 1):
            logger.info(f"搜索 [{keyword}] 第{page_num}/{max_pages}页")

            try:
                search_url = self._build_search_url(keyword, page_num)
                self._page.goto(search_url, wait_until="domcontentloaded", timeout=30000)

                # 🛡️ 模拟人工浏览：随机等待页面加载 + 随机滚动
                page_load_wait = random.uniform(3.0, 6.0)
                time.sleep(page_load_wait)

                # 随机滚动 2-4 次（模拟浏览行为）
                for _ in range(random.randint(2, 4)):
                    scroll_distance = random.randint(300, 800)
                    self._page.evaluate(f"window.scrollBy(0, {scroll_distance})")
                    time.sleep(random.uniform(0.8, 2.0))

                # 🆕 从 SSR 数据中提取搜索结果（window.__INITIAL_STATE__）
                items = self._parse_ssr_data(keyword)
                if items:
                    logger.debug(f"  SSR 提取获取 {len(items)} 条")

                # 兜底：DOM 解析
                if not items:
                    logger.debug("  SSR 无数据，尝试 DOM 解析兜底")
                    try:
                        self._page.wait_for_selector(
                            "section.note-item, .feeds-page section",
                            timeout=8000,
                        )
                    except Exception:
                        pass
                    html = self._page.content()
                    items = self._parse_dom_results(html, keyword)
                    logger.debug(f"  DOM 兜底获取 {len(items)} 条")

                # 过滤 + 统计
                new_count = 0
                for item in items:
                    if use_incremental and self._should_skip(keyword, item.collected_at):
                        continue
                    all_items.append(item)
                    new_count += 1
                    self._update_last_collected(keyword, item.collected_at or datetime.utcnow())

                    if max_items and len(all_items) >= max_items:
                        break

                logger.info(f"  第{page_num}页: 获取 {len(items)} 条, 新增 {new_count} 条")

                if not items:
                    consecutive_empty += 1
                    if consecutive_empty >= self.BACKOFF_THRESHOLD:
                        logger.info("  连续空结果，停止翻页")
                        break
                else:
                    consecutive_empty = 0

                if max_items and len(all_items) >= max_items:
                    logger.info(f"  已达到 max_items={max_items}")
                    break

            except Exception as exc:
                logger.error(f"  第{page_num}页失败: {exc}")
                self.stats["errors"] += 1
                time.sleep(random.uniform(5.0, 10.0))
                continue

            if checkpoint_cb:
                checkpoint_cb(keyword, page_num, len(all_items))

            # 🛡️ 翻页间隔：随机延迟 + 偶尔长停顿（模拟阅读行为）
            self._adaptive_delay(consecutive_empty)
            if page_num % random.randint(2, 3) == 0:
                reading_pause = random.uniform(5.0, 12.0)
                logger.debug(f"  模拟阅读停顿 {reading_pause:.1f}s")
                time.sleep(reading_pause)

        logger.info(
            f"[{keyword}] 完成: {len(all_items)} 条 "
            f"({self.stats['pages_loaded']} pages, {self.stats['retries']} retries, {self.stats['errors']} errors)"
        )
        return all_items

    # ═══════════════════════════════════════════════════════════════════════════
    # 🆕 SSR 数据提取（window.__INITIAL_STATE__）
    # ═══════════════════════════════════════════════════════════════════════════

    def _parse_ssr_data(self, keyword: str) -> list[ParsedXiaohongshuItem]:
        """从 window.__INITIAL_STATE__.search.feeds 提取搜索结果。"""
        try:
            raw = self._page.evaluate('''
            () => {
                const state = window.__INITIAL_STATE__;
                if (!state || !state.search || !state.search.feeds) return [];
                const feeds = state.search.feeds._rawValue || state.search.feeds;
                if (!Array.isArray(feeds)) return [];
                return feeds
                    .filter(f => f.modelType === 'note' && f.noteCard)
                    .map(f => ({
                        id: f.id || '',
                        xsecToken: f.xsecToken || '',
                        displayTitle: f.noteCard.displayTitle || '',
                        desc: f.noteCard.desc || '',
                        type: f.noteCard.type || '',
                        user: f.noteCard.user || {},
                        interactInfo: f.noteCard.interactInfo || {},
                        imageList: f.noteCard.imageList || [],
                        tagList: f.noteCard.tagList || [],
                        time: f.noteCard.time || 0,
                        cover: f.noteCard.cover || {},
                    }));
            }
            ''')
            if not raw:
                return []

            items = []
            seen_ids = set()

            for r in raw:
                note_id = r.get('id', '')
                if not note_id or note_id in seen_ids:
                    continue
                seen_ids.add(note_id)

                # 🆕 xsecToken（访问完整笔记需要的安全令牌）
                xsec_token = r.get('xsecToken', '')

                # 标题 + 描述
                title = (r.get('displayTitle') or '').strip()
                desc = (r.get('desc') or '').strip()
                parts = []
                if title:
                    parts.append(f"【标题】{title}")
                if desc and desc != title:
                    parts.append(f"【正文】{desc}")
                content_raw = '\n'.join(parts) if parts else '【无文本内容】'

                # 作者 — SSR 使用 camelCase: nickname / nickName / userId
                user = r.get('user', {})
                author_name = (user.get('nickname') or user.get('nickName') or '')
                author_id = str(user.get('userId', '') or user.get('id', ''))

                # 互动 — SSR camelCase: likedCount / collectedCount / commentCount / sharedCount
                interact = r.get('interactInfo', {})
                like_count = int(interact.get('likedCount', 0))
                collect_count = int(interact.get('collectedCount', 0))
                comment_count = int(interact.get('commentCount', 0))

                # 标签
                tag_list = r.get('tagList', [])
                tags = []
                if isinstance(tag_list, list):
                    for t in tag_list:
                        if isinstance(t, dict):
                            name = t.get('name', '')
                            if name:
                                tags.append(name)
                        elif isinstance(t, str):
                            tags.append(t)

                # 图片 — SSR imageList[].url 或 imageList[].infoList[].url
                img_list = r.get('imageList', [])
                image_urls = []
                if isinstance(img_list, list):
                    for img in img_list:
                        if isinstance(img, dict):
                            url = img.get('url', '')
                            if url:
                                image_urls.append(url)
                            else:
                                info_list = img.get('infoList', [])
                                if isinstance(info_list, list):
                                    for info in info_list:
                                        u = info.get('url', '')
                                        if u:
                                            image_urls.append(u)

                # 类型
                note_type = r.get('type', '')
                content_type = 'text'
                if note_type == 'video':
                    content_type = 'video'
                elif image_urls:
                    content_type = 'image'

                # 时间
                time_ts = r.get('time', 0)
                note_time = self.ts_to_datetime(time_ts / 1000) if time_ts > 1e12 else (
                    self.ts_to_datetime(time_ts) if time_ts else datetime.utcnow()
                )

                # 构建 URL（带 xsec_token 才能直接访问）
                source_url = f'https://www.xiaohongshu.com/explore/{note_id}'
                if xsec_token:
                    source_url += f'?xsec_token={xsec_token}'

                item = ParsedXiaohongshuItem(
                    content_raw=content_raw,
                    content_type=content_type,
                    source_url=source_url,
                    author_uid=author_id,
                    author_username=author_name,
                    note_id=note_id,
                    collected_at=note_time,
                    keyword=keyword,
                    like_count=like_count,
                    collect_count=collect_count,
                    comment_count=comment_count,
                    tags=tags,
                    image_list=image_urls,
                    metadata={
                        'keyword': keyword,
                        'note_id': note_id,
                        'note_type': note_type,
                        'has_image': bool(image_urls),
                        'has_video': note_type == 'video',
                        'tags': tags,
                        'like_count': like_count,
                        'collect_count': collect_count,
                        'comment_count': comment_count,
                        'xsec_token': xsec_token,
                    },
                )
                items.append(item)

            return items
        except Exception as e:
            logger.debug(f'SSR 提取失败: {e}')
            return []

    # ═══════════════════════════════════════════════════════════════════════════
    # API 响应解析
    # ═══════════════════════════════════════════════════════════════════════════

    def _parse_api_responses(
        self, responses: list[dict], keyword: str
    ) -> list[ParsedXiaohongshuItem]:
        """解析 API 响应的 JSON 数据。"""
        items = []
        seen_ids = set()

        for resp in responses:
            data = resp.get("data", {})
            note_list = data.get("items", []) or data.get("notes", [])

            for note in note_list:
                note_id = str(note.get("id", "") or note.get("note_id", ""))
                if not note_id or note_id in seen_ids:
                    continue
                seen_ids.add(note_id)

                # 提取笔记卡片信息
                note_card = note.get("note_card", note)
                display = note_card.get("display_title", "") or note.get("display_title", "")
                title = note_card.get("title", "") or note.get("title", "")
                desc = note_card.get("desc", "") or note.get("desc", "")

                # 作者信息
                author_info = note.get("user", {}) or note_card.get("user", {}) or note.get("author", {}) or {}
                author_name = author_info.get("nickname", "") or author_info.get("name", "")
                author_id = str(author_info.get("id", "") or author_info.get("user_id", ""))

                # 互动数据
                interact = note.get("interact_info", {}) or note_card.get("interact_info", {}) or {}

                # 标签
                tags = []
                for t in note.get("tag_list", []) or note_card.get("tag_list", []):
                    if isinstance(t, dict):
                        tags.append(t.get("name", ""))
                    elif isinstance(t, str):
                        tags.append(t)

                # 图片列表
                image_list = []
                for img in note.get("image_list", []) or note_card.get("image_list", []):
                    if isinstance(img, dict):
                        url = img.get("url", "") or img.get("url_default", "")
                        if url:
                            image_list.append(url)

                # 构建内容
                content_parts = []
                if title:
                    content_parts.append(f"【标题】{self.clean_html(title)}")
                if desc:
                    content_parts.append(f"【正文】{self.clean_html(desc)}")
                if display:
                    content_parts.append(f"【摘要】{self.clean_html(display)}")
                if not content_parts:
                    content_parts.append("【无文本内容】")

                content_raw = "\n".join(content_parts)

                # 内容类型
                note_type = note_card.get("type", "") or note.get("type", "")
                content_type = "text"
                if note_type == "video":
                    content_type = "video"
                elif image_list:
                    content_type = "image"

                # 时间
                time_ts = note_card.get("time", 0) or note.get("time", 0)
                note_time = self.ts_to_datetime(time_ts) if time_ts else datetime.utcnow()

                item = ParsedXiaohongshuItem(
                    content_raw=content_raw,
                    content_type=content_type,
                    source_url=f"https://www.xiaohongshu.com/explore/{note_id}",
                    author_uid=author_id,
                    author_username=author_name,
                    note_id=note_id,
                    collected_at=note_time,
                    keyword=keyword,
                    like_count=int(interact.get("liked_count", 0) or note_card.get("liked_count", 0)),
                    collect_count=int(interact.get("collected_count", 0) or note_card.get("collected_count", 0)),
                    comment_count=int(interact.get("comment_count", 0) or note_card.get("comment_count", 0)),
                    tags=tags,
                    image_list=image_list,
                    metadata={
                        "keyword": keyword,
                        "note_id": note_id,
                        "note_type": note_type,
                        "has_image": bool(image_list),
                        "has_video": note_type == "video",
                        "has_emoji": self.contains_emoji(content_raw),
                        "tags": tags,
                        "like_count": int(interact.get("liked_count", 0) or note_card.get("liked_count", 0)),
                        "collect_count": int(interact.get("collected_count", 0) or note_card.get("collected_count", 0)),
                        "comment_count": int(interact.get("comment_count", 0) or note_card.get("comment_count", 0)),
                    },
                )
                items.append(item)

        return items

    # ═══════════════════════════════════════════════════════════════════════════
    # DOM 解析（兜底方案）
    # ═══════════════════════════════════════════════════════════════════════════

    def _parse_dom_results(
        self, html: str, keyword: str
    ) -> list[ParsedXiaohongshuItem]:
        """从 HTML 中解析小红书搜索结果卡片。"""
        items = []
        seen_ids = set()

        # 匹配小红书笔记卡片（多种选择器覆盖不同版本）
        card_patterns = [
            # 新版 section.note-item
            r'<section[^>]*class="[^"]*note-item[^"]*"[^>]*>(.*?)</section>',
            # 旧版 div.feeds-page 下的 note-item
            r'<div[^>]*class="[^"]*note-item[^"]*"[^>]*>(.*?)</div>\s*(?=<div[^>]*class="[^"]*note-item|$)',
        ]

        for pattern in card_patterns:
            for card_m in re.finditer(pattern, html, re.DOTALL):
                card = card_m.group(1) if card_m.lastindex else card_m.group(0)

                # 提取 note_id（从链接中）
                note_id = ""
                link_m = re.search(r'/explore/([a-f0-9]+)', card)
                if link_m:
                    note_id = link_m.group(1)
                else:
                    link_m = re.search(r'/discovery/item/([a-f0-9]+)', card)
                    if link_m:
                        note_id = link_m.group(1)
                if not note_id or note_id in seen_ids:
                    continue
                seen_ids.add(note_id)

                # 标题
                title = ""
                title_m = re.search(r'<span[^>]*class="[^"]*title[^"]*"[^>]*>(.*?)</span>', card, re.DOTALL)
                if title_m:
                    title = self.clean_html(title_m.group(1))
                if not title:
                    title_m = re.search(r'class="[^"]*title[^"]*"[^>]*>\s*([^<]+)', card)
                    if title_m:
                        title = title_m.group(1).strip()

                # 正文/描述
                desc = ""
                desc_m = re.search(r'<span[^>]*class="[^"]*desc[^"]*"[^>]*>(.*?)</span>', card, re.DOTALL)
                if desc_m:
                    desc = self.clean_html(desc_m.group(1))

                # 作者
                author_name = ""
                author_id = ""
                author_m = re.search(r'class="[^"]*author[^"]*"[^>]*>.*?<span[^>]*>([^<]+)</span>', card, re.DOTALL)
                if author_m:
                    author_name = author_m.group(1).strip()
                user_link_m = re.search(r'/user/profile/([a-f0-9]+)', card)
                if user_link_m:
                    author_id = user_link_m.group(1)

                # 互动数据
                like_count = 0
                like_m = re.search(r'class="[^"]*like[^"]*"[^>]*>.*?(\d+)', card, re.DOTALL)
                if like_m:
                    like_count = int(like_m.group(1))

                # 图片检测
                has_image = 'image' in card.lower() or 'img' in card.lower() or '图片' in card
                has_video = 'video' in card.lower() or '视频' in card

                content_parts = []
                if title:
                    content_parts.append(f"【标题】{title}")
                if desc:
                    content_parts.append(f"【正文】{desc}")
                if not content_parts:
                    content_parts.append("【无文本内容】")

                content_type = "video" if has_video else ("image" if has_image else "text")

                item = ParsedXiaohongshuItem(
                    content_raw="\n".join(content_parts),
                    content_type=content_type,
                    source_url=f"https://www.xiaohongshu.com/explore/{note_id}",
                    author_uid=author_id,
                    author_username=author_name,
                    note_id=note_id,
                    collected_at=datetime.utcnow(),
                    keyword=keyword,
                    like_count=like_count,
                    metadata={
                        "keyword": keyword,
                        "note_id": note_id,
                        "has_image": has_image,
                        "has_video": has_video,
                        "has_emoji": self.contains_emoji("\n".join(content_parts)),
                        "tags": [],
                        "like_count": like_count,
                        "parse_method": "dom",
                    },
                )
                items.append(item)

        return items

    # ═══════════════════════════════════════════════════════════════════════════
    # 工具方法
    # ═══════════════════════════════════════════════════════════════════════════

    def _build_search_url(self, keyword: str, page: int = 1) -> str:
        """构建搜索 URL。"""
        encoded = quote(keyword)
        url = f"{self.SEARCH_URL}?keyword={encoded}"
        if page > 1:
            url += f"&page={page}"
        # 排序：默认综合排序
        url += "&sort=general"
        return url

    def _is_blocked(self) -> bool:
        """检查是否触发反爬。"""
        if not self._page:
            return False
        try:
            title = self._page.title()
            blocked_signals = ["验证", "滑块", "安全验证", "captcha", "verify"]
            if any(kw in title for kw in blocked_signals):
                return True
            url = self._page.url
            if "login" in url.lower() or "signin" in url.lower():
                return True
            return False
        except Exception:
            return False

    def _check_login(self) -> bool:
        """检查登录状态。"""
        if not self._page:
            return False
        try:
            logged_in = self._page.evaluate('''
            () => {
                const body = document.body?.innerText || '';
                if (body.includes('登录后查看')) return false;
                const state = window.__INITIAL_STATE__;
                if (state?.user?.isLogin) return true;
                return !document.querySelector('.login-modal');
            }
            ''')
            return bool(logged_in)
        except Exception:
            return True  # 无法检测时假定已登录
