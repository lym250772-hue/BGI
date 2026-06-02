"""
贴吧关键词搜索 Spider（Playwright 实现，继承 BaseSpider）
"""

import time
import re
import random
from datetime import datetime, timedelta
from dataclasses import dataclass, field
from loguru import logger

from collectors.spiders.base_spider import BaseSpider


# ── 解析结果结构 ──────────────────────────────────────────────────────────────

@dataclass
class ParsedTiebaItem:
    platform: str = "tieba"
    content_raw: str = ""
    content_type: str = "text"
    source_url: str = ""
    author_uid: str = ""
    author_username: str = ""
    thread_id: str = ""
    collected_at: datetime = field(default_factory=datetime.utcnow)
    keyword: str = ""
    bar_name: str = ""
    reply_count: int = 0
    metadata: dict = field(default_factory=dict)


# ── Spider ─────────────────────────────────────────────────────────────────────

class TiebaSpider(BaseSpider):
    """贴吧搜索 Spider — 按关键词搜索并返回结构化数据。"""

    PLATFORM = "tieba"
    HOME_URL = "https://tieba.baidu.com"
    SEARCH_URL = "https://tieba.baidu.com/f/search/res"
    PAGE_SIZE = 50
    MIN_DELAY = 2.0
    MAX_DELAY = 4.5

    def __init__(self, headless: bool = True, fetch_replies: bool = True):
        super().__init__(headless)
        self.fetch_replies = fetch_replies

    def _is_blocked(self) -> bool:
        """贴吧安全验证页面短时出现后会自动跳转，不要太快判定拦截。"""
        return False

    def fetch_page(self, url: str, wait_selector: str = None,
                   wait_timeout: int = 15000, referer: str = None) -> str | None:
        """Tieba 需要 networkidle 等待 React 完全渲染。"""
        import time as _time
        last_error = None
        for attempt in range(1, self.MAX_RETRIES + 1):
            try:
                goto_opts = {"wait_until": "networkidle", "timeout": 30000}
                if referer:
                    goto_opts["referer"] = referer
                self._page.goto(url, **goto_opts)
                _time.sleep(3)  # React 渲染额外等待
                if wait_selector:
                    try:
                        self._page.wait_for_selector(wait_selector, timeout=wait_timeout)
                    except Exception:
                        pass
                self.stats["pages_loaded"] += 1
                return self._page.content()
            except Exception as exc:
                last_error = exc
                self.stats["retries"] += 1
                if attempt < self.MAX_RETRIES:
                    _time.sleep(self.RETRY_BASE_DELAY * attempt)
        self.stats["errors"] += 1
        return None

    # ── 搜索入口 ──────────────────────────────────────────────────────────

    def search_and_parse(self, keyword: str, max_pages: int = 3, **kwargs) -> list[ParsedTiebaItem]:
        if not self._page:
            raise RuntimeError("Spider 未启动，请先调用 start()")

        max_items = kwargs.get("max_items", 0)
        use_incremental = kwargs.get("incremental", False)
        start_page = kwargs.get("start_page", 1)
        checkpoint_cb = kwargs.get("checkpoint_callback")
        all_items = []
        consecutive_empty = 0
        page_num = start_page - 1

        while True:
            page_num += 1
            if max_pages > 0 and page_num > max_pages:
                break
            label = f"第{page_num}页" if max_pages <= 0 else f"第{page_num}/{max_pages}页"
            logger.info(f"搜索 [{keyword}] {label}")
            try:
                url = self._build_url(keyword, page_num)
                html = self.fetch_page(
                    url,
                    wait_selector="div[class*=\"threadcard\"], div.s_post",
                    referer="https://tieba.baidu.com/index.html",
                )
                if not html:
                    consecutive_empty += 1
                    if consecutive_empty >= self.BACKOFF_THRESHOLD:
                        break
                    continue

                cards = self._parse_search_results(html, keyword)
                new_count = 0
                for card in cards:
                    if use_incremental and self._should_skip(keyword, card.collected_at):
                        continue

                    if self.fetch_replies and card.thread_id:
                        try:
                            thread_detail = self._fetch_thread_detail(card.thread_id)
                            if thread_detail:
                                card.content_raw = thread_detail.get("content_raw", card.content_raw)
                                card.author_uid = thread_detail.get("author_uid", card.author_uid)
                                card.author_username = thread_detail.get("author_username", card.author_username)
                                card.metadata["replies"] = thread_detail.get("replies", [])
                                card.metadata["reply_count"] = len(thread_detail.get("replies", []))
                            time.sleep(1.0 + random.random() * 1.5)
                        except Exception as exc:
                            logger.debug(f"  获取帖子 {card.thread_id} 详情失败: {exc}")

                    all_items.append(card)
                    new_count += 1
                    self._update_last_collected(keyword, card.collected_at or datetime.utcnow())

                    if max_items and len(all_items) >= max_items:
                        break

                logger.info(f"  第{page_num}页: 解析 {len(cards)} 条, 新增 {new_count} 条")

                if len(cards) == 0:
                    consecutive_empty += 1
                    if consecutive_empty >= self.BACKOFF_THRESHOLD:
                        break
                else:
                    consecutive_empty = 0

                if max_items and len(all_items) >= max_items:
                    break

            except Exception as exc:
                logger.error(f"  第{page_num}页处理失败: {exc}")
                self.stats["errors"] += 1
                time.sleep(3.0)
                continue

            if checkpoint_cb:
                checkpoint_cb(keyword, page_num, len(all_items))

            self._adaptive_delay(consecutive_empty)

        logger.info(f"[{keyword}] 完成: {len(all_items)} 条 ({self.stats['pages_loaded']} 页, {self.stats['retries']} 次重试)")
        return all_items

    # ── 解析搜索结果 ──────────────────────────────────────────────────────

    def _parse_search_results(self, html: str, keyword: str) -> list[ParsedTiebaItem]:
        """解析搜索结果 — 优先 DOM 提取，HTML 解析兜底。"""
        items = []
        # 1) DOM 提取（新版 React 页面）
        dom_items = self._parse_from_dom(keyword)
        if dom_items:
            return dom_items
        # 2) HTML 解析（旧版兜底）
        cards = self._extract_search_cards(html)
        for card_html in cards:
            try:
                item = self._parse_one_card(card_html, keyword)
                if item and item.content_raw:
                    items.append(item)
            except Exception:
                continue
        return items

    def _parse_from_dom(self, keyword: str) -> list[ParsedTiebaItem]:
        """通过 page.evaluate() 从 DOM 提取搜索结果。

        贴吧新版搜索结果页结构:
          div.thread-content-box  ← 搜索结果容器
            ├── 第1行: 吧名
            ├── 第2行: 作者名 发布于 日期
            ├── 第3行+: 帖子正文/标题
            ├── a.action-link-bg / a.item-link-bg (href*="/p/", innerText为空)
            └── a.comment-link-zone (innerText=回复数)

        旧版 JS 直接从 a.innerText 取文本，新版 a 标签无文本内容，
        需要改为从父级 .thread-content-box 提取。
        """
        js_code = """
        () => {
            const seen = new Set();
            const results = [];

            // 直接定位搜索结果容器 .thread-content-box
            document.querySelectorAll('div.thread-content-box').forEach(box => {
                const link = box.querySelector('a[href*="/p/"]');
                if (!link) return;
                const match = link.href.match(/\\/p\\/(\\d+)/);
                if (!match) return;
                const tid = match[1];
                if (seen.has(tid)) return;
                seen.add(tid);

                const fullText = box.innerText.trim();
                const lines = fullText.split('\\n').map(l => l.trim()).filter(l => l.length > 0);

                // 第1行=吧名, 第2行=作者+时间, 第3行+=正文
                const forum = lines.length > 0 ? lines[0] : '';

                let author = '';
                const authorMatch = (lines.length > 1 ? lines[1] : '').match(/([^\\s]{2,15})\\s*发布于/);
                if (authorMatch) author = authorMatch[1];

                // 正文 = 跳过吧名和作者行
                const contentLines = lines.slice(1).filter(l => !l.includes('发布于'));
                const title = contentLines.length > 0 ? contentLines[0] : (lines.length > 2 ? lines[2] : fullText.substring(0, 100));

                if (title.length < 4) return;  // 跳过太短的

                results.push({
                    title: title.substring(0, 200),
                    link: link.href,
                    threadId: tid,
                    author: author,
                    forum: forum,
                    snippet: fullText.substring(0, 300)
                });
            });

            // 也处理右侧热门帖子 .card-item .hot-thread
            if (!results.length) {
                document.querySelectorAll('div.card-item a.hot-thread[href*="/p/"]').forEach(a => {
                    const match = a.href.match(/\\/p\\/(\\d+)/);
                    if (!match) return;
                    const tid = match[1];
                    if (seen.has(tid)) return;
                    seen.add(tid);
                    const title = a.innerText.trim();
                    if (title.length < 4) return;
                    const parent = a.closest('div.card-item');
                    const parentText = parent ? parent.innerText.trim() : '';
                    const lines = parentText.split('\\n').filter(l => l.trim());
                    const forum = lines.length > 0 ? lines[0] : '';
                    results.push({
                        title: title.substring(0, 200),
                        link: a.href,
                        threadId: tid,
                        author: '',
                        forum: forum,
                        snippet: parentText.substring(0, 300)
                    });
                });
            }

            // 兜底: 其他容器中的帖子链接
            if (!results.length) {
                document.querySelectorAll('div[class*="thread"], div[class*="search-result"]').forEach(el => {
                    const link = el.querySelector('a[href*="/p/"]');
                    if (!link) return;
                    const tid = (link.href.match(/\\/p\\/(\\d+)/) || [])[1];
                    if (!tid || seen.has(tid)) return;
                    seen.add(tid);
                    const text = el.innerText.trim();
                    if (text.length > 8) {
                        const lines = text.split('\\n').filter(l => l.trim());
                        results.push({
                            title: (lines.length > 2 ? lines[2] : lines[0]).substring(0, 100),
                            link: link.href,
                            threadId: tid,
                            author: '',
                            forum: lines.length > 0 ? lines[0] : '',
                            snippet: text.substring(0, 300)
                        });
                    }
                });
            }

            return results;
        }
        """
        try:
            raw = self._page.evaluate(js_code)
            items = []
            for r in raw:
                if not r.get("title") or not r.get("threadId"):
                    continue
                item = ParsedTiebaItem(
                    content_raw=r["title"],
                    source_url=r.get("link", ""),
                    thread_id=r.get("threadId", ""),
                    author_username=r.get("author", ""),
                    bar_name=r.get("forum", ""),
                    keyword=keyword,
                    metadata={
                        "keyword": keyword,
                        "bar_name": r.get("forum", ""),
                        "has_image": False,
                        "has_emoji": False,
                    },
                )
                items.append(item)
            return items
        except Exception as e:
            logger.debug(f"DOM extraction failed: {e}")
            return []

    @staticmethod
    def _extract_search_cards(html: str) -> list[str]:
        """提取搜索结果的帖子卡片 HTML 片段（新版 React 渲染 + 旧版兼容）。"""
        cards = []
        # 新版: div[class*="threadcard"]
        for m in re.finditer(r'<div[^>]*class="[^"]*threadcard[^"]*"[^>]*>', html):
            start = m.start()
            depth, pos = 0, start
            while pos < len(html):
                next_open = html.find("<div", pos + 1)
                next_close = html.find("</div>", pos + 1)
                if next_close == -1:
                    break
                if next_open != -1 and next_open < next_close:
                    depth += 1; pos = next_open
                elif depth == 0:
                    cards.append(html[start:next_close + 6]); break
                else:
                    depth -= 1; pos = next_close
        # 旧版兼容: s_post / threadcardclass
        if not cards:
            for pattern in [r'<div[^>]*class="[^"]*s_post[^"]*"[^>]*>',
                          r'<div[^>]*class="[^"]*threadcardclass[^"]*"[^>]*>']:
                for m in re.finditer(pattern, html):
                    start = m.start()
                    depth, pos = 0, start
                    while pos < len(html):
                        next_open = html.find("<div", pos + 1)
                        next_close = html.find("</div>", pos + 1)
                        if next_close == -1:
                            break
                        if next_open != -1 and next_open < next_close:
                            depth += 1; pos = next_open
                        elif depth == 0:
                            cards.append(html[start:next_close + 6]); break
                        else:
                            depth -= 1; pos = next_close
                if cards:
                    break
        return cards

    def _parse_one_card(self, card_html: str, keyword: str) -> ParsedTiebaItem | None:
        item = ParsedTiebaItem(keyword=keyword)
        # 标题（新版: thread-title / title class; 旧版: title-wrap span / bluelink）
        title = ""
        for pattern in [
            r'class="[^"]*thread-title[^"]*"[^>]*>\s*(.+?)\s*</',
            r'class="[^"]*title[^"]*"[^>]*>\s*(.+?)\s*</',
            r'class="[^"]*title-wrap[^"]*"[^>]*>.*?<span[^>]*>(.*?)</span>',
            r'<a[^>]*class="[^"]*bluelink[^"]*"[^>]*>([^<]+)</a>',
            r'<a[^>]*href="[^"]*/p/\d+[^"]*"[^>]*>([^<]+)</a>',
        ]:
            m = re.search(pattern, card_html, re.DOTALL)
            if m:
                title = self.clean_html(m.group(1)).strip()
                if title and len(title) > 1:
                    break
        # 摘要
        snippet = ""
        abstract_m = re.search(
            r'class="[^"]*abstract-wrap[^"]*"[^>]*>.*?<span[^>]*>(.*?)</span>',
            card_html, re.DOTALL,
        )
        if abstract_m:
            snippet = self.clean_html(abstract_m.group(1))
        if not snippet:
            content_m = re.search(
                r'<div[^>]*class="[^"]*p_content[^"]*"[^>]*>(.*?)</div>',
                card_html, re.DOTALL,
            )
            if content_m:
                snippet = self.clean_html(content_m.group(1))
        snippet = self._extract_emojis_inline(snippet)
        parts = [p for p in [title, snippet] if p]
        item.content_raw = "\n".join(parts)
        # 链接 + thread_id
        url_m = re.search(r'href="(https?://tieba\.baidu\.com/p/(\d+)[^"]*)"', card_html)
        if url_m:
            item.source_url = url_m.group(1)
            item.thread_id = url_m.group(2)
        # 作者
        author_m = re.search(
            r'class="[^"]*forum-attention[^"]*user[^"]*"[^>]*>\s*([^<]+?)\s*</span>', card_html,
        )
        if not author_m:
            author_m = re.search(r'class="[^"]*p_author_name[^"]*"[^>]*>([^<]+)</', card_html)
        if author_m:
            item.author_username = author_m.group(1).strip()
        uid_m = re.search(r'/home\?uid=(\w+)', card_html)
        if uid_m:
            item.author_uid = uid_m.group(1)
        # 贴吧名
        bar_m = re.search(r'class="[^"]*forum-name-text[^"]*"[^>]*>([^<]+)</span>', card_html)
        if not bar_m:
            bar_m = re.search(r'class="[^"]*forum-name[^"]*"[^>]*>[^<]*<span[^>]*>([^<]+)</span>', card_html)
        if not bar_m:
            bar_m = re.search(r'class="[^"]*p_forum_name[^"]*"[^>]*>([^<]+)</', card_html)
        if bar_m:
            item.bar_name = bar_m.group(1).strip()
        # 回复数
        action_numbers = re.findall(r'class="[^"]*action-number[^"]*"[^>]*>\s*(\d+)\s*<', card_html)
        if action_numbers:
            item.reply_count = int(action_numbers[0])
        item.collected_at = self._extract_time(card_html)
        item.metadata = {
            "keyword": keyword,
            "bar_name": item.bar_name,
            "reply_count": item.reply_count,
            "has_image": "image-card-wrapper" in card_html or "img" in card_html.lower() or "图片" in card_html,
            "has_emoji": bool(re.search(r'class="[^"]*BDE_Smiley[^"]*"', card_html)),
        }
        return item

    # ── 帖子详情页 ────────────────────────────────────────────────────────

    def _fetch_thread_detail(self, thread_id: str) -> dict | None:
        url = f"https://tieba.baidu.com/p/{thread_id}"
        html = self.fetch_page(url, wait_selector="div.d_post_content, div.l_post")
        if not html:
            return None
        posts = self._parse_thread_posts(html)
        if not posts:
            return None
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

    def _parse_thread_posts(self, html: str) -> list[dict]:
        posts = []
        for m in re.finditer(r'<div[^>]*class="[^"]*l_post[^"]*"[^>]*>', html):
            start = m.start()
            depth, pos = 0, start
            while pos < len(html):
                next_open = html.find("<div", pos + 1)
                next_close = html.find("</div>", pos + 1)
                if next_close == -1:
                    break
                if next_open != -1 and next_open < next_close:
                    depth += 1; pos = next_open
                elif depth == 0:
                    parsed = self._parse_one_post(html[start:next_close + 6])
                    if parsed:
                        posts.append(parsed)
                    break
                else:
                    depth -= 1; pos = next_close
        return posts

    def _parse_one_post(self, post_html: str) -> dict | None:
        result = {"author_username": "", "author_uid": "", "content": "", "reply_time": None, "floor": 0}
        author_m = re.search(r'class="[^"]*d_author[^"]*"[^>]*>.*?<a[^>]*>([^<]+)</a>', post_html, re.DOTALL)
        if not author_m:
            author_m = re.search(r'<a[^>]*class="[^"]*p_author_name[^"]*"[^>]*>([^<]+)</a>', post_html)
        if author_m:
            result["author_username"] = author_m.group(1).strip()
        uid_m = re.search(r'data-field="[^"]*user_id[^:]*:(\d+)', post_html)
        if uid_m:
            result["author_uid"] = uid_m.group(1)
        content_m = re.search(
            r'<div[^>]*class="[^"]*d_post_content[^"]*"[^>]*>(.*?)</div>',
            post_html, re.DOTALL,
        )
        if not content_m:
            content_m = re.search(r'<div[^>]*id="post_content[^"]*"[^>]*>(.*?)</div>', post_html, re.DOTALL)
        if content_m:
            text = self.clean_html(content_m.group(1))
            text = self._extract_emojis_inline(text)
            result["content"] = text
        floor_m = re.search(r'class="[^"]*tail-info[^"]*"[^>]*>(\d+)楼', post_html)
        if floor_m:
            result["floor"] = int(floor_m.group(1))
        result["reply_time"] = self._extract_time(post_html)
        return result

    # ── 辅助 ──────────────────────────────────────────────────────────────

    @staticmethod
    def _extract_emojis_inline(text: str) -> str:
        return text  # emoji 保留在文本中

    @staticmethod
    def _extract_time(html: str) -> datetime:
        now = datetime.utcnow()
        pub_m = re.search(r"发布于\s*(\d{4})[-/](\d{1,2})[-/](\d{1,2})", html)
        if pub_m:
            y, mo, d = map(int, pub_m.groups())
            return datetime(y, mo, d)
        abs_m = re.search(r"(\d{2,4})[-/](\d{1,2})[-/](\d{1,2})\s+(\d{1,2}):(\d{2})", html)
        if abs_m:
            parts = [int(x) for x in abs_m.groups()]
            if parts[0] < 100:
                parts[0] += 2000
            try:
                return datetime(parts[0], parts[1], parts[2], parts[3], parts[4])
            except ValueError:
                pass
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
        today_m = re.search(r"今天\s*(\d{1,2}):(\d{2})", html)
        if today_m:
            hour, minute = map(int, today_m.groups())
            return datetime(now.year, now.month, now.day, hour, minute)
        min_m = re.search(r"(\d+)分钟前", html)
        if min_m:
            return now - timedelta(minutes=int(min_m.group(1)))
        hour_m = re.search(r"(\d+)小时前", html)
        if hour_m:
            return now - timedelta(hours=int(hour_m.group(1)))
        yday_m = re.search(r"昨天\s*(\d{1,2}):(\d{2})", html)
        if yday_m:
            hour, minute = map(int, yday_m.groups())
            yday = now - timedelta(days=1)
            return datetime(yday.year, yday.month, yday.day, hour, minute)
        sec_m = re.search(r"(\d+)秒前", html)
        if sec_m:
            return now - timedelta(seconds=int(sec_m.group(1)))
        date_m = re.search(r"(\d{4})-(\d{1,2})-(\d{1,2})", html)
        if date_m:
            y, mo, d = map(int, date_m.groups())
            return datetime(y, mo, d)
        return now

    def _build_url(self, keyword: str, page: int = 1) -> str:
        from urllib.parse import quote
        encoded = quote(keyword)
        pn = (page - 1) * self.PAGE_SIZE
        return f"{self.SEARCH_URL}?ie=utf-8&kw=&qw={encoded}&pn={pn}"
