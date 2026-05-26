"""
贴吧关键词搜索 Spider（Playwright 实现）

流程:
1. 启动 Chromium → 注入 Cookie → 访问贴吧
2. 构造搜索 URL → 等待搜索结果 Ajax 渲染
3. 解析搜索结果卡片 → 提取帖子元信息
4. 可选: 进入帖子详情页 → 获取完整正文 + 回复
5. 输出 ParsedTiebaItem 列表

反爬策略:
- 随机 User-Agent 轮换
- navigator.webdriver 隐藏
- 随机请求间隔 (2~5s)
- 支持 Cookie 登录态注入
"""

import time
import re
import os
import json
import random
import hashlib
from datetime import datetime, timedelta
from dataclasses import dataclass, field
from loguru import logger
from playwright.sync_api import sync_playwright, Browser, Page

from config.settings import settings


# ── User-Agent 池 ──────────────────────────────────────────────────────────────

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:120.0) Gecko/20100101 Firefox/120.0",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/118.0.0.0 Safari/537.36",
]


def random_ua() -> str:
    return random.choice(USER_AGENTS)


# ── 解析结果结构 ──────────────────────────────────────────────────────────────

@dataclass
class ParsedTiebaItem:
    """贴吧搜索结果 / 帖子详情 解析后的结构化数据。"""
    platform: str = "tieba"
    content_raw: str = ""          # 帖子正文（含标题）
    content_type: str = "text"
    source_url: str = ""
    author_uid: str = ""
    author_username: str = ""
    thread_id: str = ""
    collected_at: datetime = field(default_factory=datetime.utcnow)
    keyword: str = ""
    bar_name: str = ""             # 所属贴吧
    reply_count: int = 0
    metadata: dict = field(default_factory=dict)


@dataclass
class ParsedReply:
    """帖子的单条回复。"""
    author_username: str = ""
    author_uid: str = ""
    content: str = ""
    reply_time: datetime | None = None
    floor: int = 0


# ── Spider ─────────────────────────────────────────────────────────────────────

class TiebaSpider:
    """贴吧搜索 Spider — 按关键词搜索并返回结构化数据。

    使用方式:
        spider = TiebaSpider()
        spider.start()
        items = spider.search_and_parse("刷单", max_pages=2)
        spider.close()
    """

    TIEBA_HOME = "https://tieba.baidu.com"
    TIEBA_SEARCH_URL = "https://tieba.baidu.com/f/search/res"

    def __init__(self, headless: bool = True, fetch_replies: bool = True):
        """
        Args:
            headless: 是否无头模式
            fetch_replies: 是否进入帖子详情页采集完整正文和回复
        """
        self.headless = headless
        self.fetch_replies = fetch_replies
        self._playwright = None
        self._browser: Browser | None = None
        self._context = None
        self._page: Page | None = None
        self._logged_in = False
        self._cookie_file = os.path.join(
            settings.raw_data_dir.as_posix(), "tieba_cookies.json"
        )
        # 增量采集: 记录每个关键词的最后采集时间
        self._last_collected_at: dict[str, datetime] = {}
        self._incremental_file = os.path.join(
            settings.raw_data_dir.as_posix(), "tieba_last_collected.json"
        )

    @staticmethod
    def _load_cookies(platform: str) -> list[dict] | None:
        """加载平台 Cookie：优先环境变量 BGI_{PLATFORM}_COOKIES，文件兜底。"""
        env_val = getattr(settings, f"{platform}_cookies", "")
        if env_val:
            try:
                cookies = json.loads(env_val)
                if isinstance(cookies, list) and cookies:
                    return cookies
            except json.JSONDecodeError:
                pass
        cookie_file = os.path.join(
            settings.raw_data_dir.as_posix(), f"{platform}_cookies.json"
        )
        if os.path.exists(cookie_file):
            try:
                with open(cookie_file, "r", encoding="utf-8") as f:
                    cookies = json.load(f)
                if isinstance(cookies, list) and cookies:
                    return cookies
            except Exception:
                pass
        return None

    # ── 生命周期 ────────────────────────────────────────────────────────────

    def start(self):
        """启动浏览器并注入 Cookie 登录态。"""
        self._playwright = sync_playwright().start()
        self._browser = self._playwright.chromium.launch(
            headless=self.headless,
            args=[
                "--disable-blink-features=AutomationControlled",
                "--no-sandbox",
            ],
        )
        self._context = self._browser.new_context(
            user_agent=random_ua(),
            locale="zh-CN",
            viewport={"width": 1366, "height": 768},
        )

        # 注入 Cookie 登录态（优先环境变量 BGI_TIEBA_COOKIES，文件兜底）
        cookies = self._load_cookies("tieba")
        if cookies:
            try:
                self._context.add_cookies(cookies)
                self._logged_in = True
                logger.info(f"已注入 {len(cookies)} 条贴吧 Cookie")
            except Exception as exc:
                logger.warning(f"Cookie 注入失败: {exc}")
        else:
            logger.warning("未配置贴吧 Cookie（环境变量 BGI_TIEBA_COOKIES 或文件），搜索可能受限")

        self._page = self._context.new_page()
        self._page.add_init_script("""
            Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
        """)

        # 预热：用主 page 先访问贴吧首页，模拟正常用户行为
        try:
            self._page.goto(self.TIEBA_HOME, wait_until="domcontentloaded", timeout=20000)
            time.sleep(2)
        except Exception:
            logger.warning("预热访问 tieba.baidu.com 超时，继续...")

        # 加载增量采集记录
        self._load_incremental_state()

        logger.info(
            f"贴吧 Spider 已启动（登录态={'是' if self._logged_in else '否'}"
            f"，采集回复={'是' if self.fetch_replies else '否'}）"
        )

    def close(self):
        """关闭浏览器，持久化增量状态。"""
        self._save_incremental_state()
        if self._browser:
            self._browser.close()
            logger.info("贴吧 Spider 已关闭")
        if self._playwright:
            self._playwright.stop()

    # ── 增量采集状态 ────────────────────────────────────────────────────────

    def _load_incremental_state(self):
        """从文件加载各关键词的最后采集时间。"""
        if os.path.exists(self._incremental_file):
            try:
                with open(self._incremental_file, "r", encoding="utf-8") as f:
                    raw = json.load(f)
                for k, v in raw.items():
                    self._last_collected_at[k] = datetime.fromisoformat(v)
                logger.info(f"已加载 {len(self._last_collected_at)} 个关键词的增量状态")
            except Exception as exc:
                logger.warning(f"加载增量状态失败: {exc}")

    def _save_incremental_state(self):
        """持久化各关键词的最后采集时间。"""
        try:
            raw = {k: v.isoformat() for k, v in self._last_collected_at.items()}
            with open(self._incremental_file, "w", encoding="utf-8") as f:
                json.dump(raw, f, ensure_ascii=False, indent=2)
        except Exception as exc:
            logger.warning(f"保存增量状态失败: {exc}")

    def _update_last_collected(self, keyword: str, dt: datetime):
        """更新某关键词的最后采集时间。"""
        if keyword not in self._last_collected_at or dt > self._last_collected_at[keyword]:
            self._last_collected_at[keyword] = dt

    # ── 搜索 + 解析（正式入口）─────────────────────────────────────────────

    def search_and_parse(
        self, keyword: str, max_pages: int = 3, max_threads_per_page: int = 20,
    ) -> list[ParsedTiebaItem]:
        """按关键词搜索贴吧，返回解析后的结构化数据。

        Args:
            keyword: 搜索关键词
            max_pages: 最多翻页数
            max_threads_per_page: 每页最多处理的帖子数

        Returns:
            list[ParsedTiebaItem]
        """
        if not self._page:
            raise RuntimeError("Spider 未启动，请先调用 start()")

        last_ts = self._last_collected_at.get(keyword)
        if last_ts:
            logger.info(f"增量采集 [{keyword}]：跳过 {last_ts.isoformat()} 之前的内容")

        all_items = []
        for page_num in range(1, max_pages + 1):
            url = self._build_search_url(keyword, page_num)
            logger.info(f"搜索 [{keyword}] 第{page_num}/{max_pages}页")

            try:
                html = self._fetch_search_page(keyword, page_num)
                if not html:
                    continue

                cards = self._parse_search_results(html, keyword)

                new_count = 0
                for card in cards[:max_threads_per_page]:
                    # 增量过滤：如果帖子时间早于上次采集时间则跳过
                    if last_ts and card.collected_at and card.collected_at <= last_ts:
                        continue
                    new_count += 1

                    # 获取帖子详情（完整正文 + 回复）
                    if self.fetch_replies and card.thread_id:
                        try:
                            thread_detail = self._fetch_thread_detail(card.thread_id)
                            if thread_detail:
                                card.content_raw = thread_detail.get("content_raw", card.content_raw)
                                card.content_type = thread_detail.get("content_type", card.content_type)
                                card.author_uid = thread_detail.get("author_uid", card.author_uid)
                                card.author_username = thread_detail.get("author_username", card.author_username)
                                card.metadata["replies"] = thread_detail.get("replies", [])
                                card.metadata["reply_count"] = len(thread_detail.get("replies", []))
                            delay = 1.5 + random.random() * 2.0  # 访问帖子间隔
                            time.sleep(delay)
                        except Exception as exc:
                            logger.debug(f"  获取帖子 {card.thread_id} 详情失败: {exc}")

                    all_items.append(card)
                    self._update_last_collected(keyword, card.collected_at or datetime.utcnow())

                logger.info(f"  第{page_num}页: 解析 {len(cards)} 条, 新增 {new_count} 条")

            except Exception as exc:
                logger.error(f"  第{page_num}页处理失败: {exc}")
                continue

            if page_num < max_pages:
                delay = 2.5 + random.random() * 2.5
                logger.debug(f"  翻页等待 {delay:.1f}s...")
                time.sleep(delay)

        logger.info(f"搜索 [{keyword}] 完成，共 {len(all_items)} 条贴吧帖子")
        return all_items

    # ── 内部：搜索页加载 ────────────────────────────────────────────────────

    def _fetch_search_page(self, keyword: str, page_num: int) -> str | None:
        """加载贴吧搜索结果页，返回 HTML。"""
        url = self._build_search_url(keyword, page_num)
        try:
            # 加 Referer 避免触发百度安全验证（直接访问搜索URL会被视为机器人）
            self._page.goto(
                url,
                wait_until="domcontentloaded",
                timeout=30000,
                referer="https://tieba.baidu.com/index.html",
            )
            # 等待搜索结果 Ajax 渲染（新版 Vue 虚拟列表）
            try:
                self._page.wait_for_selector(
                    "div.threadcardclass, div.s_post, div.virtual-list-item",
                    timeout=15000,
                )
            except Exception:
                try:
                    self._page.wait_for_selector(
                        "span.title-wrap, span.p_title, a.bluelink",
                        timeout=10000,
                    )
                except Exception:
                    logger.warning("  搜索结果未在预期时间内出现，尝试继续...")
            time.sleep(2)

            title = self._page.title()
            if "验证" in title or "安全验证" in title:
                logger.error("  触发百度安全验证！建议更换IP或使用登录Cookie")
                return None

            return self._page.content()
        except Exception as exc:
            logger.error(f"  搜索页加载失败 [{keyword}/第{page_num}页]: {exc}")
            return None

    def _build_search_url(self, keyword: str, page: int = 1) -> str:
        """构造贴吧搜索 URL。搜索结果每页50条，pn 为偏移量。"""
        from urllib.parse import quote
        encoded = quote(keyword)
        pn = (page - 1) * 50
        return f"{self.TIEBA_SEARCH_URL}?ie=utf-8&kw=&qw={encoded}&pn={pn}"

    # ── 内部：搜索结果解析 ──────────────────────────────────────────────────

    def _parse_search_results(self, html: str, keyword: str) -> list[ParsedTiebaItem]:
        """从搜索页 HTML 中解析帖子列表。"""
        cards = self._extract_search_cards(html)
        items = []
        for card_html in cards:
            try:
                item = self._parse_one_card(card_html, keyword)
                if item and item.content_raw:
                    items.append(item)
            except Exception as exc:
                logger.debug(f"  跳过解析失败的卡片: {exc}")
                continue
        return items

    @staticmethod
    def _extract_search_cards(html: str) -> list[str]:
        """从搜索页 HTML 中切分出帖子卡片（新版 Vue 虚拟列表结构）。

        只提取 threadcardclass 卡片，跳过 forum-wrap（相关吧推荐）和模糊用户卡片。
        """
        cards = []
        # 新版贴吧搜索: 每个结果是 div.virtual-list-item > div.threadcardclass.thread-new3
        for m in re.finditer(
            r'<div[^>]*class="[^"]*threadcardclass[^"]*thread-new3[^"]*"[^>]*>',
            html,
        ):
            start = m.start()
            depth = 0
            pos = start
            while pos < len(html):
                next_open = html.find("<div", pos + 1)
                next_close = html.find("</div>", pos + 1)
                if next_close == -1:
                    break
                if next_open != -1 and next_open < next_close:
                    depth += 1
                    pos = next_open
                else:
                    if depth == 0:
                        cards.append(html[start:next_close + 6])
                        break
                    depth -= 1
                    pos = next_close

        # 兼容旧版: div.s_post 卡片
        if not cards:
            for m in re.finditer(r'<div[^>]*class="[^"]*s_post[^"]*"[^>]*>', html):
                start = m.start()
                depth = 0
                pos = start
                while pos < len(html):
                    next_open = html.find("<div", pos + 1)
                    next_close = html.find("</div>", pos + 1)
                    if next_close == -1:
                        break
                    if next_open != -1 and next_open < next_close:
                        depth += 1
                        pos = next_open
                    else:
                        if depth == 0:
                            cards.append(html[start:next_close + 6])
                            break
                        depth -= 1
                        pos = next_close

        return cards

    def _parse_one_card(self, card_html: str, keyword: str) -> ParsedTiebaItem | None:
        """解析单张搜索结果卡片，兼容新版 (Vue) 和旧版 HTML 结构。"""
        item = ParsedTiebaItem(keyword=keyword)

        # -- 帖子标题（新版: .title-wrap span; 旧版: a.bluelink）--------------
        # 注意: title-wrap div 和 span 之间可能有 HTML 注释 <!---->
        title = ""
        title_wrap_m = re.search(
            r'class="[^"]*title-wrap[^"]*"[^>]*>.*?<span[^>]*>(.*?)</span>',
            card_html, re.DOTALL,
        )
        if title_wrap_m:
            title = self._clean_html(title_wrap_m.group(1))
        if not title:
            bluelink_m = re.search(
                r'<a[^>]*class="[^"]*bluelink[^"]*"[^>]*>([^<]+)</a>', card_html,
            )
            if bluelink_m:
                title = bluelink_m.group(1).strip()
        if not title:
            # 最后尝试: 查找 /p/ 链接的文本
            link_text_m = re.search(
                r'<a[^>]*href="[^"]*/p/\d+[^"]*"[^>]*>([^<]+)</a>', card_html,
            )
            if link_text_m:
                title = link_text_m.group(1).strip()

        # -- 帖子正文摘要（新版: .abstract-wrap span; 旧版: .p_content）-------
        snippet = ""
        abstract_m = re.search(
            r'class="[^"]*abstract-wrap[^"]*"[^>]*>.*?<span[^>]*>(.*?)</span>',
            card_html, re.DOTALL,
        )
        if abstract_m:
            snippet = self._clean_html(abstract_m.group(1))
        if not snippet:
            content_m = re.search(
                r'<div[^>]*class="[^"]*p_content[^"]*"[^>]*>(.*?)</div>',
                card_html, re.DOTALL,
            )
            if content_m:
                snippet = self._clean_html(content_m.group(1))

        snippet = self._extract_emojis_inline(snippet)

        # 组合标题和正文
        parts = [p for p in [title, snippet] if p]
        item.content_raw = "\n".join(parts)

        # -- 帖子链接 & thread_id ----------------------------------------------
        # 新版: a.action-link-bg; 旧版: 直接 /p/ 链接
        url_m = re.search(r'href="(https?://tieba\.baidu\.com/p/(\d+)[^"]*)"', card_html)
        if url_m:
            item.source_url = url_m.group(1)
            item.thread_id = url_m.group(2)

        # -- 作者（新版: .forum-attention.user; 旧版: .p_author_name）-----------
        author_m = re.search(
            r'class="[^"]*forum-attention[^"]*user[^"]*"[^>]*>\s*([^<]+?)\s*</span>',
            card_html,
        )
        if not author_m:
            author_m = re.search(
                r'class="[^"]*p_author_name[^"]*"[^>]*>([^<]+)</', card_html,
            )
        if author_m:
            item.author_username = author_m.group(1).strip()

        # 作者 UID
        uid_m = re.search(r'/home\?uid=(\w+)', card_html)
        if uid_m:
            item.author_uid = uid_m.group(1)

        # -- 所属贴吧（新版: .forum-name-text; 旧版: .p_forum_name）-------------
        bar_m = re.search(
            r'class="[^"]*forum-name-text[^"]*"[^>]*>([^<]+)</span>', card_html,
        )
        if not bar_m:
            bar_m = re.search(
                r'class="[^"]*forum-name[^"]*"[^>]*>[^<]*<span[^>]*>([^<]+)</span>', card_html,
            )
        if not bar_m:
            bar_m = re.search(
                r'class="[^"]*p_forum_name[^"]*"[^>]*>([^<]+)</', card_html,
            )
        if bar_m:
            item.bar_name = bar_m.group(1).strip()

        # -- 回复数（新版: comment 区域的 .action-number）------------------------
        # action-bar 中的第二个 action-number 通常是回复数
        action_numbers = re.findall(
            r'class="[^"]*action-number[^"]*"[^>]*>\s*(\d+)\s*<', card_html,
        )
        if action_numbers:
            item.reply_count = int(action_numbers[0]) if action_numbers else 0

        # -- 时间（新版: "发布于 YYYY-M-D"；旧版: 相对时间）-----------------------
        item.collected_at = self._extract_time(card_html)

        # -- 元数据 ------------------------------------------------------------
        item.metadata = {
            "keyword": keyword,
            "bar_name": item.bar_name,
            "reply_count": item.reply_count,
            "has_image": "image-card-wrapper" in card_html
            or "img" in card_html.lower()
            or "图片" in card_html,
            "has_emoji": bool(re.search(r'class="[^"]*BDE_Smiley[^"]*"', card_html)),
        }

        return item

    # ── 内部：帖子详情页采集 ────────────────────────────────────────────────

    def _fetch_thread_detail(self, thread_id: str) -> dict | None:
        """进入帖子详情页，获取完整正文和回复列表。

        Returns:
            dict with keys: content_raw, content_type, author_uid, author_username, replies
        """
        url = f"https://tieba.baidu.com/p/{thread_id}"
        try:
            self._page.goto(url, wait_until="domcontentloaded", timeout=20000)
            try:
                self._page.wait_for_selector(
                    "div.d_post_content, div.l_post", timeout=10000,
                )
            except Exception:
                logger.debug(f"  帖子 {thread_id} 内容未在预期时间内加载")
            time.sleep(1.5)

            html = self._page.content()

            # 解析全部楼层
            posts = self._parse_thread_posts(html)
            if not posts:
                return None

            # 主帖是第一个楼层
            main_post = posts[0]
            replies = posts[1:]

            result = {
                "content_raw": main_post.get("content", ""),
                "content_type": "text",
                "author_uid": main_post.get("author_uid", ""),
                "author_username": main_post.get("author_username", ""),
                "replies": [],
            }

            for r in replies:
                result["replies"].append({
                    "author_username": r.get("author_username", ""),
                    "author_uid": r.get("author_uid", ""),
                    "content": r.get("content", ""),
                    "reply_time": r.get("reply_time"),
                    "floor": r.get("floor", 0),
                })

            return result
        except Exception as exc:
            logger.debug(f"  获取帖子 {thread_id} 详情异常: {exc}")
            return None

    def _parse_thread_posts(self, html: str) -> list[dict]:
        """解析帖子详情页的所有楼层（主帖 + 回复）。"""
        posts = []
        # 匹配每个楼层 div.l_post
        for m in re.finditer(r'<div[^>]*class="[^"]*l_post[^"]*"[^>]*>', html):
            start = m.start()
            depth = 0
            pos = start
            while pos < len(html):
                next_open = html.find("<div", pos + 1)
                next_close = html.find("</div>", pos + 1)
                if next_close == -1:
                    break
                if next_open != -1 and next_open < next_close:
                    depth += 1
                    pos = next_open
                else:
                    if depth == 0:
                        post_html = html[start:next_close + 6]
                        parsed = self._parse_one_post(post_html)
                        if parsed:
                            posts.append(parsed)
                        break
                    depth -= 1
                    pos = next_close
        return posts

    def _parse_one_post(self, post_html: str) -> dict | None:
        """解析单个楼层（主帖或回复）。"""
        result = {
            "author_username": "",
            "author_uid": "",
            "content": "",
            "reply_time": None,
            "floor": 0,
        }

        # -- 作者 --------------------------------------------------------------
        author_m = re.search(r'class="[^"]*d_author[^"]*"[^>]*>.*?<a[^>]*>([^<]+)</a>', post_html, re.DOTALL)
        if not author_m:
            author_m = re.search(r'<a[^>]*class="[^"]*p_author_name[^"]*"[^>]*>([^<]+)</a>', post_html)
        if author_m:
            result["author_username"] = author_m.group(1).strip()

        # 作者 UID
        uid_m = re.search(r'data-field="[^"]*user_id[^:]*:(\d+)', post_html)
        if uid_m:
            result["author_uid"] = uid_m.group(1)

        # -- 正文内容 ----------------------------------------------------------
        content_m = re.search(
            r'<div[^>]*class="[^"]*d_post_content[^"]*"[^>]*>(.*?)</div>',
            post_html, re.DOTALL,
        )
        if not content_m:
            content_m = re.search(
                r'<div[^>]*id="post_content[^"]*"[^>]*>(.*?)</div>',
                post_html, re.DOTALL,
            )
        if content_m:
            text = self._clean_html(content_m.group(1))
            text = self._extract_emojis_inline(text)
            result["content"] = text

        # -- 楼层号 ------------------------------------------------------------
        floor_m = re.search(r'class="[^"]*tail-info[^"]*"[^>]*>(\d+)楼', post_html)
        if floor_m:
            result["floor"] = int(floor_m.group(1))

        # -- 时间 --------------------------------------------------------------
        result["reply_time"] = self._extract_time(post_html)

        return result

    # ── 字段提取辅助 ────────────────────────────────────────────────────────

    @staticmethod
    def _clean_html(text: str) -> str:
        """去除 HTML 标签，保留文本和表情符号占位。"""
        # 先处理 <br> 为换行
        text = re.sub(r"<br\s*/?>", "\n", text, flags=re.I)
        # 图片表情 (<img class="BDE_Smiley">) 保留 alt 文本
        text = re.sub(
            r'<img[^>]*class="[^"]*BDE_Smiley[^"]*"[^>]*alt="([^"]*)"[^>]*>',
            r"[\1]", text,
        )
        # 其他图片保留占位符
        text = re.sub(r'<img[^>]*>', "[图片]", text)
        # 去除其他 HTML 标签
        text = re.sub(r"<[^>]+>", " ", text)
        # 折叠空白
        text = re.sub(r"&nbsp;", " ", text)
        text = re.sub(r"&amp;", "&", text)
        text = re.sub(r"&lt;", "<", text)
        text = re.sub(r"&gt;", ">", text)
        text = re.sub(r"\s+", " ", text)
        return text.strip()

    @staticmethod
    def _extract_emojis_inline(text: str) -> str:
        """提取 Unicode 表情符号，保持其文本形式。已在 _clean_html 中处理了 BDE_Smiley，
        这里确保 Unicode emoji 保留在文本中。"""
        # 保留 Unicode emoji (U+1F600-U+1F9FF 等范围)
        # 不做删除，保持原样让后续分析能识别
        return text

    @staticmethod
    def _extract_time(html: str) -> datetime:
        """从 HTML 中提取时间，处理相对时间表达。"""
        now = datetime.utcnow()

        # 1) 新版 "发布于 2026-5-11" 或 "发布于 2026-05-11"
        pub_m = re.search(r"发布于\s*(\d{4})[-/](\d{1,2})[-/](\d{1,2})", html)
        if pub_m:
            y, mo, d = map(int, pub_m.groups())
            return datetime(y, mo, d)

        # 2) 绝对时间 "2025-05-22 17:47" 或 "05-22 17:47"
        abs_m = re.search(r"(\d{2,4})[-/](\d{1,2})[-/](\d{1,2})\s+(\d{1,2}):(\d{2})", html)
        if abs_m:
            parts = [int(x) for x in abs_m.groups()]
            if parts[0] < 100:
                parts[0] += 2000
            try:
                return datetime(parts[0], parts[1], parts[2], parts[3], parts[4])
            except ValueError:
                pass

        # 2) "MM月DD日 HH:MM"
        abs_m2 = re.search(r"(\d{1,2})月(\d{1,2})日\s*(\d{1,2}):(\d{2})", html)
        if abs_m2:
            month, day, hour, minute = map(int, abs_m2.groups())
            year = now.year
            if month > now.month + 1:
                year -= 1
            try:
                return datetime(year, month, day, hour, minute)
            except ValueError:
                pass

        # 3) "今天 HH:MM"
        today_m = re.search(r"今天\s*(\d{1,2}):(\d{2})", html)
        if today_m:
            hour, minute = map(int, today_m.groups())
            return datetime(now.year, now.month, now.day, hour, minute)

        # 4) "N分钟前"
        min_m = re.search(r"(\d+)分钟前", html)
        if min_m:
            return now - timedelta(minutes=int(min_m.group(1)))

        # 5) "N小时前"
        hour_m = re.search(r"(\d+)小时前", html)
        if hour_m:
            return now - timedelta(hours=int(hour_m.group(1)))

        # 6) "昨天 HH:MM"
        yday_m = re.search(r"昨天\s*(\d{1,2}):(\d{2})", html)
        if yday_m:
            hour, minute = map(int, yday_m.groups())
            yesterday = now - timedelta(days=1)
            return datetime(yesterday.year, yesterday.month, yesterday.day, hour, minute)

        # 7) "N秒前"
        sec_m = re.search(r"(\d+)秒前", html)
        if sec_m:
            return now - timedelta(seconds=int(sec_m.group(1)))

        # 8) 纯日期 "2025-05-22"
        date_m = re.search(r"(\d{4})-(\d{1,2})-(\d{1,2})", html)
        if date_m:
            y, mo, d = map(int, date_m.groups())
            return datetime(y, mo, d)

        return now

    # ── 调试工具 ────────────────────────────────────────────────────────────

    def screenshot(self, path: str = "tieba_debug.png"):
        """保存当前页面截图，用于调试。"""
        if self._page:
            full_path = os.path.join(settings.raw_data_dir.as_posix(), path)
            self._page.screenshot(path=full_path, full_page=True)
            logger.info(f"截图已保存: {full_path}")

    def __enter__(self):
        self.start()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()
