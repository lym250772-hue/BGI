"""
微博关键词搜索 Spider（Playwright 实现，继承 BaseSpider）
"""

import time
import re
from datetime import datetime, timedelta
from dataclasses import dataclass, field
from loguru import logger

from collectors.spiders.base_spider import BaseSpider, random_ua


# ── 解析结果结构 ──────────────────────────────────────────────────────────────

@dataclass
class ParsedWeiboItem:
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

class WeiboSearchSpider(BaseSpider):
    """微博搜索 Spider — 按关键词搜索并返回结构化数据。"""

    PLATFORM = "weibo"
    HOME_URL = "https://weibo.com"
    SEARCH_URL = "https://s.weibo.com/weibo"
    PAGE_SIZE = 25
    MIN_DELAY = 2.0
    MAX_DELAY = 4.5

    def _is_blocked(self) -> bool:
        if not self._page:
            return False
        try:
            title = self._page.title()
            return "登录" in title or "验证" in title
        except Exception:
            return False

    # ── 搜索入口 ──────────────────────────────────────────────────────────

    def search_and_parse(self, keyword: str, max_pages: int = 3, **kwargs) -> list[ParsedWeiboItem]:
        if not self._page:
            raise RuntimeError("Spider 未启动，请先调用 start()")

        max_items = kwargs.get("max_items", 0)
        all_items = []
        consecutive_empty = 0

        for page_num in range(1, max_pages + 1):
            logger.info(f"搜索 [{keyword}] 第{page_num}/{max_pages}页")
            try:
                url = self._build_url(keyword, page_num)
                html = self.fetch_page(url, wait_selector="div.card-feed")
                if not html:
                    consecutive_empty += 1
                    if consecutive_empty >= self.BACKOFF_THRESHOLD:
                        logger.info(f"  连续 {consecutive_empty} 页空结果，停止翻页")
                        break
                    continue

                items = self._parse_results(html, keyword)
                new_count = 0
                for item in items:
                    if self._should_skip(keyword, item.collected_at):
                        continue
                    all_items.append(item)
                    new_count += 1
                    self._update_last_collected(keyword, item.collected_at or datetime.utcnow())

                logger.info(f"  第{page_num}页: 解析 {len(items)} 条, 新增 {new_count} 条")

                if len(items) < self.PAGE_SIZE // 2:
                    consecutive_empty += 1
                else:
                    consecutive_empty = 0

                if max_items and len(all_items) >= max_items:
                    logger.info(f"  已达到目标数量 {max_items}，停止")
                    break

            except Exception as exc:
                logger.error(f"  第{page_num}页处理失败: {exc}")
                continue

            if page_num < max_pages:
                self._adaptive_delay(consecutive_empty)

        logger.info(f"[{keyword}] 完成: {len(all_items)} 条 ({self.stats['pages_loaded']} 页, {self.stats['retries']} 次重试)")
        return all_items

    # ── 解析 ──────────────────────────────────────────────────────────────

    def _parse_results(self, html: str, keyword: str) -> list[ParsedWeiboItem]:
        cards = self._extract_card_htmls(html)
        items = []
        for card_html in cards:
            try:
                item = self._parse_one_card(card_html, keyword)
                if item and item.content_raw:
                    items.append(item)
            except Exception:
                continue
        return items

    @staticmethod
    def _extract_card_htmls(html: str) -> list[str]:
        cards = []
        for m in re.finditer(r'<div[^>]*class="[^"]*card-feed[^"]*"[^>]*>', html):
            start = m.start()
            depth, pos = 0, start
            while pos < len(html):
                next_open = html.find("<div", pos + 1)
                next_close = html.find("</div>", pos + 1)
                if next_close == -1:
                    break
                if next_open != -1 and next_open < next_close:
                    depth += 1
                    pos = next_open
                elif depth == 0:
                    cards.append(html[start:next_close + 6])
                    break
                else:
                    depth -= 1
                    pos = next_close
        return cards

    def _parse_one_card(self, card_html: str, keyword: str) -> ParsedWeiboItem | None:
        item = ParsedWeiboItem(keyword=keyword)
        uid_m = re.search(r"//weibo\.com/(\d+)\?", card_html)
        if uid_m:
            item.author_uid = uid_m.group(1)
        nick_m = re.search(r'nick-name="([^"]+)"', card_html)
        if nick_m:
            item.author_username = nick_m.group(1)
        post_m = re.search(r"//weibo\.com/\d+/(\w+)\?", card_html)
        if post_m:
            item.weibo_id = post_m.group(1)
            item.source_url = f"https://weibo.com/{item.author_uid}/{item.weibo_id}"
        item.content_raw = self._extract_content(card_html)
        item.collected_at = self._extract_time(card_html)
        item.content_type = self._detect_content_type(card_html)
        item.metadata = {
            "keyword": keyword,
            "has_image": "图片" in card_html or "photo" in card_html.lower(),
            "has_video": "视频" in card_html or "video" in card_html.lower(),
            "is_long_text": "展开" in card_html,
        }
        return item

    @staticmethod
    def _extract_content(card_html: str) -> str:
        content_m = re.search(
            r'node-type="feed_list_content"[^>]*>(.*?)(?:<div[^>]*node-type="feed_list_media_prev"|$)',
            card_html, re.DOTALL,
        )
        if not content_m:
            return ""
        text = content_m.group(1)
        text = re.sub(r"<[^>]+>", " ", text)
        text = re.sub(r"\s+", " ", text)
        text = re.sub(r"^\s*展开\s*c\s*", "", text)
        text = re.sub(r"\s*收起\s*d\s*$", "", text)
        text = re.sub(r"\s*展开\s*c\s*", " ", text)
        return text.strip()

    @staticmethod
    def _extract_time(card_html: str) -> datetime:
        now = datetime.utcnow()
        abs_m = re.search(r"(\d{2})月(\d{2})日\s*(\d{2}):(\d{2})", card_html)
        if abs_m:
            month, day, hour, minute = map(int, abs_m.groups())
            year = now.year
            if month > now.month + 1:
                year -= 1
            try:
                return datetime(year, month, day, hour, minute)
            except ValueError:
                pass
        today_m = re.search(r"今天\s*(\d{2}):(\d{2})", card_html)
        if today_m:
            hour, minute = map(int, today_m.groups())
            return datetime(now.year, now.month, now.day, hour, minute)
        min_m = re.search(r"(\d+)分钟前", card_html)
        if min_m:
            return now - timedelta(minutes=int(min_m.group(1)))
        hour_m = re.search(r"(\d+)小时前", card_html)
        if hour_m:
            return now - timedelta(hours=int(hour_m.group(1)))
        yday_m = re.search(r"昨天\s*(\d{2}):(\d{2})", card_html)
        if yday_m:
            hour, minute = map(int, yday_m.groups())
            return datetime((now - timedelta(days=1)).year, (now - timedelta(days=1)).month, (now - timedelta(days=1)).day, hour, minute)
        sec_m = re.search(r"(\d+)秒前", card_html)
        if sec_m:
            return now - timedelta(seconds=int(sec_m.group(1)))
        return now

    @staticmethod
    def _detect_content_type(card_html: str) -> str:
        if "视频" in card_html or "wbpv_video" in card_html:
            return "video"
        if "图片" in card_html or "photo" in card_html:
            return "image"
        return "text"

    def _build_url(self, keyword: str, page: int = 1) -> str:
        from urllib.parse import quote
        encoded = quote(keyword)
        if page <= 1:
            return f"{self.SEARCH_URL}?q={encoded}"
        return f"{self.SEARCH_URL}?q={encoded}&page={page}"
