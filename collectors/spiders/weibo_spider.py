"""
微博关键词搜索 Spider（Playwright 实现）

完整流程:
1. 启动 Chromium 无头浏览器 → 注入登录 Cookie
2. 构造搜索 URL → 等待搜索结果卡片渲染
3. 解析 HTML 卡片 → 提取结构化字段
4. 输出 IntelItem 兼容的 dict 列表
"""

import time
import re
import os
import json
import random
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
class ParsedWeiboItem:
    """微博搜索结果解析后的结构化数据，可直接映射到 IntelItem + raw_data 表。"""
    platform: str = "weibo"
    content_raw: str = ""
    content_type: str = "text"
    source_url: str = ""
    author_uid: str = ""
    author_username: str = ""
    weibo_id: str = ""
    collected_at: datetime = field(default_factory=datetime.utcnow)
    keyword: str = ""
    metadata: dict = field(default_factory=dict)


# ── Spider ─────────────────────────────────────────────────────────────────────

class WeiboSearchSpider:
    """微博搜索 Spider — 按关键词搜索并返回结构化数据。

    使用方式:
        spider = WeiboSearchSpider()
        spider.start()
        items = spider.search_and_parse("刷单", max_pages=2)
        for item in items:
            print(item.author_username, item.content_raw[:50])
        spider.close()
    """

    WEIBO_HOME = "https://weibo.com"
    WEIBO_SEARCH_URL = "https://s.weibo.com/weibo"
    PAGE_SIZE = 25

    def __init__(self, headless: bool = True):
        self.headless = headless
        self._playwright = None
        self._browser: Browser | None = None
        self._context = None
        self._page: Page | None = None
        self._logged_in = False
        self._cookie_file = os.path.join(
            settings.raw_data_dir.as_posix(), "weibo_cookies.json"
        )

    @staticmethod
    def _load_cookies(platform: str) -> list[dict] | None:
        """加载平台 Cookie：优先环境变量 BGI_{PLATFORM}_COOKIES，文件兜底。"""
        # 1. 从环境变量读取（JSON 字符串）
        env_val = getattr(settings, f"{platform}_cookies", "")
        if env_val:
            try:
                cookies = json.loads(env_val)
                if isinstance(cookies, list) and cookies:
                    return cookies
            except json.JSONDecodeError:
                pass
        # 2. 从文件兜底
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

    # ── 生命周期 ──────────────────────────────────────────────────────────

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
        )

        # 先访问一次 weibo.com 建立域名上下文（Playwright add_cookies 要求）
        temp_page = self._context.new_page()
        try:
            temp_page.goto(self.WEIBO_HOME, wait_until="domcontentloaded", timeout=20000)
            time.sleep(1)
        except Exception:
            logger.warning("预热访问 weibo.com 超时，继续...")
        temp_page.close()

        # 注入 Cookie（优先环境变量，文件兜底）
        cookies = self._load_cookies("weibo")
        if cookies:
            try:
                self._context.add_cookies(cookies)
                self._logged_in = True
                logger.info(f"已注入 {len(cookies)} 条微博 Cookie")
            except Exception as exc:
                logger.warning(f"Cookie 注入失败: {exc}")
        else:
            logger.warning("未配置微博 Cookie（环境变量 BGI_WEIBO_COOKIES 或文件），搜索可能被拦截")

        self._page = self._context.new_page()
        self._page.add_init_script("""
            Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
        """)
        logger.info("微博搜索 Spider 已启动（登录态=" + ("是" if self._logged_in else "否") + "）")

    def close(self):
        """关闭浏览器，释放资源。"""
        if self._browser:
            self._browser.close()
            logger.info("微博搜索 Spider 已关闭")
        if self._playwright:
            self._playwright.stop()

    # ── 搜索（纯 HTML 版本，用于调试） ───────────────────────────────────

    def search(self, keyword: str, max_pages: int = 3) -> list[str]:
        """按关键词搜索微博，返回每页的 HTML 列表（不做解析，用于调试）。

        Args:
            keyword: 搜索关键词
            max_pages: 最多翻页数

        Returns:
            list[str]: 每页 HTML 源码字符串
        """
        if not self._page:
            raise RuntimeError("Spider 未启动，请先调用 start()")

        all_html = []
        for page_num in range(1, max_pages + 1):
            url = self._build_search_url(keyword, page_num)
            logger.info(f"搜索 [{keyword}] 第{page_num}页 → {url}")

            try:
                html = self._fetch_page(keyword, page_num)
                if html:
                    all_html.append(html)
            except Exception as exc:
                logger.error(f"  第{page_num}页加载失败: {exc}")
                continue

            if page_num < max_pages:
                delay = 2.5 + (hash(keyword + str(page_num)) % 30) / 10.0
                time.sleep(delay)

        return all_html

    # ── 搜索 + 解析（正式入口） ──────────────────────────────────────────

    def search_and_parse(self, keyword: str, max_pages: int = 3) -> list[ParsedWeiboItem]:
        """按关键词搜索微博，返回解析后的结构化数据列表。

        Args:
            keyword: 搜索关键词
            max_pages: 最多翻页数

        Returns:
            list[ParsedWeiboItem]: 解析后的微博数据
        """
        if not self._page:
            raise RuntimeError("Spider 未启动，请先调用 start()")

        all_items = []
        for page_num in range(1, max_pages + 1):
            url = self._build_search_url(keyword, page_num)
            logger.info(f"搜索+解析 [{keyword}] 第{page_num}/{max_pages}页")

            try:
                html = self._fetch_page(keyword, page_num)
                if not html:
                    continue

                items = self._parse_results(html, keyword)
                all_items.extend(items)
                logger.info(f"  第{page_num}页解析完成，提取 {len(items)} 条微博")

            except Exception as exc:
                logger.error(f"  第{page_num}页处理失败: {exc}")
                continue

            if page_num < max_pages:
                delay = 2.5 + (hash(keyword + str(page_num)) % 30) / 10.0
                time.sleep(delay)

        logger.info(f"搜索 [{keyword}] 完成，共 {len(all_items)} 条微博（{max_pages} 页）")
        return all_items

    # ── 内部：加载页面 ────────────────────────────────────────────────────

    def _fetch_page(self, keyword: str, page_num: int) -> str | None:
        """加载搜索结果页，返回 HTML。"""
        url = self._build_search_url(keyword, page_num)
        try:
            self._page.goto(url, wait_until="load", timeout=30000)
            # 等待搜索结果卡片
            try:
                self._page.wait_for_selector(
                    "div.card-feed", timeout=15000,
                )
            except Exception:
                logger.warning("  搜索结果卡片未在 15s 内出现，尝试继续...")
            time.sleep(2)

            title = self._page.title()
            if "登录" in title:
                logger.error(f"  被重定向到登录页，Cookie 可能已失效")
                return None

            return self._page.content()
        except Exception as exc:
            logger.error(f"  页面加载失败 [{keyword}/第{page_num}页]: {exc}")
            return None

    # ── 内部：解析搜索结果 ────────────────────────────────────────────────

    def _parse_results(self, html: str, keyword: str) -> list[ParsedWeiboItem]:
        """从搜索页 HTML 中解析所有微博卡片，返回结构化数据列表。"""
        cards = self._extract_card_htmls(html)
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
    def _extract_card_htmls(html: str) -> list[str]:
        """从 HTML 中切分出每个 card-feed 的完整 div 片段。"""
        cards = []
        for m in re.finditer(r'<div[^>]*class="[^"]*card-feed[^"]*"[^>]*>', html):
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

    def _parse_one_card(self, card_html: str, keyword: str) -> ParsedWeiboItem | None:
        """解析单张微博卡片 HTML，返回 ParsedWeiboItem。"""
        item = ParsedWeiboItem(keyword=keyword)

        # -- 用户 UID ---------------------------------------------------------
        uid_m = re.search(r"//weibo\.com/(\d+)\?", card_html)
        if uid_m:
            item.author_uid = uid_m.group(1)

        # -- 用户名 ------------------------------------------------------------
        nick_m = re.search(r'nick-name="([^"]+)"', card_html)
        if nick_m:
            item.author_username = nick_m.group(1)

        # -- 微博 ID -----------------------------------------------------------
        post_m = re.search(r"//weibo\.com/\d+/(\w+)\?", card_html)
        if post_m:
            item.weibo_id = post_m.group(1)
            item.source_url = f"https://weibo.com/{item.author_uid}/{item.weibo_id}"

        # -- 正文 --------------------------------------------------------------
        item.content_raw = self._extract_content(card_html)

        # -- 时间 --------------------------------------------------------------
        item.collected_at = self._extract_time(card_html)

        # -- 内容类型 ----------------------------------------------------------
        item.content_type = self._detect_content_type(card_html)

        # -- 元数据 ------------------------------------------------------------
        item.metadata = {
            "keyword": keyword,
            "has_image": "图片" in card_html or "photo" in card_html.lower(),
            "has_video": "视频" in card_html or "video" in card_html.lower(),
            "is_long_text": "展开" in card_html,
        }

        return item

    # ── 字段提取辅助方法 ──────────────────────────────────────────────────

    @staticmethod
    def _extract_content(card_html: str) -> str:
        """从卡片 HTML 中提取微博正文。"""
        # 找 node-type="feed_list_content" 的 p/div 节点
        content_m = re.search(
            r'node-type="feed_list_content"[^>]*>(.*?)(?:<div[^>]*node-type="feed_list_media_prev"|$)',
            card_html, re.DOTALL,
        )
        if not content_m:
            return ""

        text = content_m.group(1)
        # 去掉 HTML 标签
        text = re.sub(r"<[^>]+>", " ", text)
        # 折叠空白
        text = re.sub(r"\s+", " ", text)
        # 去掉首部 "展开 c " / "收起 d" 等
        text = re.sub(r"^\s*展开\s*c\s*", "", text)
        text = re.sub(r"\s*收起\s*d\s*$", "", text)
        text = re.sub(r"\s*展开\s*c\s*", " ", text)
        return text.strip()

    @staticmethod
    def _extract_time(card_html: str) -> datetime:
        """从卡片中提取发布时间，处理相对时间。"""
        now = datetime.utcnow()

        # 1) 绝对时间: "05月22日 17:47"
        abs_m = re.search(r"(\d{2})月(\d{2})日\s*(\d{2}):(\d{2})", card_html)
        if abs_m:
            month, day, hour, minute = map(int, abs_m.groups())
            year = now.year
            # 如果月份比当前月大很多，说明是去年的微博
            if month > now.month + 1:
                year -= 1
            try:
                return datetime(year, month, day, hour, minute)
            except ValueError:
                pass

        # 2) 今天: "今天 HH:MM"
        today_m = re.search(r"今天\s*(\d{2}):(\d{2})", card_html)
        if today_m:
            hour, minute = map(int, today_m.groups())
            return datetime(now.year, now.month, now.day, hour, minute)

        # 3) N分钟前
        min_m = re.search(r"(\d+)分钟前", card_html)
        if min_m:
            return now - timedelta(minutes=int(min_m.group(1)))

        # 4) N小时前
        hour_m = re.search(r"(\d+)小时前", card_html)
        if hour_m:
            return now - timedelta(hours=int(hour_m.group(1)))

        # 5) 昨天 HH:MM
        yday_m = re.search(r"昨天\s*(\d{2}):(\d{2})", card_html)
        if yday_m:
            hour, minute = map(int, yday_m.groups())
            yesterday = now - timedelta(days=1)
            return datetime(yesterday.year, yesterday.month, yesterday.day, hour, minute)

        # 6) N秒前
        sec_m = re.search(r"(\d+)秒前", card_html)
        if sec_m:
            return now - timedelta(seconds=int(sec_m.group(1)))

        return now

    @staticmethod
    def _detect_content_type(card_html: str) -> str:
        """根据卡片内容判断微博类型。"""
        has_video = "视频" in card_html or "wbpv_video" in card_html
        has_image = "图片" in card_html or "photo" in card_html
        if has_video:
            return "video"
        if has_image:
            return "image"
        return "text"

    # ── 辅助方法 ──────────────────────────────────────────────────────────

    def _build_search_url(self, keyword: str, page: int = 1) -> str:
        """构造微博搜索 URL。"""
        from urllib.parse import quote
        encoded = quote(keyword)
        if page <= 1:
            return f"{self.WEIBO_SEARCH_URL}?q={encoded}"
        return f"{self.WEIBO_SEARCH_URL}?q={encoded}&page={page}"

    def screenshot(self, path: str = "weibo_debug.png"):
        """调试用：保存当前页面截图。"""
        if self._page:
            full_path = os.path.join(settings.raw_data_dir.as_posix(), path)
            self._page.screenshot(path=full_path, full_page=True)
            logger.info(f"截图已保存: {full_path}")

    # ── 上下文管理器 ──────────────────────────────────────────────────────

    def __enter__(self):
        self.start()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()
