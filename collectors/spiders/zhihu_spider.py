"""
知乎关键词搜索 Spider（Playwright + API 直调，继承 BaseSpider）

核心策略: 浏览器中调用知乎搜索 API (/api/v4/search_v3)，获取结构化 JSON。
优势: 无需解析 HTML/DOM，不受页面改版影响，速度快。
"""

import time
import json
import random
from datetime import datetime
from dataclasses import dataclass, field
from loguru import logger

from collectors.spiders.base_spider import BaseSpider


@dataclass
class ParsedZhihuItem:
    platform: str = "zhihu"
    content_raw: str = ""
    content_type: str = "text"
    source_url: str = ""
    author_uid: str = ""
    author_username: str = ""
    question_id: str = ""
    answer_id: str = ""
    collected_at: datetime = field(default_factory=datetime.utcnow)
    keyword: str = ""
    voteup_count: int = 0
    comment_count: int = 0
    topics: list[str] = field(default_factory=list)
    metadata: dict = field(default_factory=dict)


class ZhihuSearchSpider(BaseSpider):
    """知乎搜索 Spider — API 直调，零 HTML 解析。"""

    PLATFORM = "zhihu"
    HOME_URL = "https://www.zhihu.com"
    SEARCH_API = "/api/v4/search_v3"
    ANSWERS_API = "https://www.zhihu.com/api/v4/questions/{qid}/answers"
    PAGE_SIZE = 20
    MIN_DELAY = 1.5
    MAX_DELAY = 3.0

    def __init__(
        self, headless: bool = True,
        fetch_answers: bool = True, fetch_comments: bool = False,
        max_answers_per_question: int = 3,
    ):
        super().__init__(headless)
        self.fetch_answers = fetch_answers
        self.fetch_comments = True  # 默认采集评论，大数据思路
        self.max_answers = max_answers_per_question

    # ── 搜索入口 ──────────────────────────────────────────────────────────

    def search_and_parse(self, keyword: str, max_pages: int = 3, **kwargs) -> list[ParsedZhihuItem]:
        if not self._page:
            raise RuntimeError("Spider 未启动，请先调用 start()")

        max_items = kwargs.get("max_items", 0)
        use_incremental = kwargs.get("incremental", False)
        all_items = []
        consecutive_empty = 0

        page_num = 0
        while True:
            page_num += 1
            if max_pages > 0 and page_num > max_pages:
                break
            offset = (page_num - 1) * self.PAGE_SIZE
            label = f"第{page_num}页" if max_pages <= 0 else f"第{page_num}/{max_pages}页"
            logger.info(f"搜索 [{keyword}] {label} (offset={offset})")

            try:
                items = self._call_search_api(keyword, offset)
                if not items:
                    consecutive_empty += 1
                    if consecutive_empty >= self.BACKOFF_THRESHOLD:
                        logger.info("  连续空结果，停止翻页")
                        break
                    continue

                new_count = 0
                for item in items:
                    if use_incremental and self._should_skip(keyword, item.collected_at):
                        continue

                    if self.fetch_answers and item.question_id:
                        try:
                            answers = self._call_answers_api(item.question_id)
                            if answers:
                                best = answers[0]
                                if best.get("content"):
                                    item.content_raw = (
                                        f"【问题】{item.content_raw}\n"
                                        f"【回答】@{best.get('author_username', '')}: "
                                        f"{best.get('content', '')}"
                                    )
                                item.metadata["answers"] = answers
                                item.metadata["answer_count"] = len(answers)
                            time.sleep(1.0 + random.random() * 1.5)
                        except Exception as exc:
                            logger.debug(f"  获取回答失败 (qid={item.question_id}): {exc}")

                    all_items.append(item)
                    new_count += 1
                    self._update_last_collected(keyword, item.collected_at or datetime.utcnow())

                    if max_items and len(all_items) >= max_items:
                        break

                logger.info(f"  第{page_num}页: {len(items)} 条, 新增 {new_count} 条")

                if len(items) == 0:
                    consecutive_empty += 1
                    if consecutive_empty >= self.BACKOFF_THRESHOLD:
                        break
                else:
                    consecutive_empty = 0

                if max_items and len(all_items) >= max_items:
                    logger.info(f"  已达到 max_items={max_items}")
                    break

            except Exception as exc:
                logger.error(f"  第{page_num}页失败: {exc}")
                self.stats["errors"] += 1
                time.sleep(3.0 + random.random() * 3.0)  # 错误后退避
                continue

            self._adaptive_delay(consecutive_empty)

        logger.info(
            f"[{keyword}] 完成: {len(all_items)} 条 "
            f"({self.stats['pages_loaded']} pages, {self.stats['retries']} retries, {self.stats['errors']} errors)"
        )
        return all_items

    # ── API 调用 ──────────────────────────────────────────────────────────

    def _call_search_api(self, keyword: str, offset: int = 0) -> list[ParsedZhihuItem]:
        """浏览器内 fetch 调用知乎搜索 API。"""
        from urllib.parse import quote
        encoded = quote(keyword)
        url = f"{self.SEARCH_API}?q={encoded}&type=content&offset={offset}&limit={self.PAGE_SIZE}"

        js_code = f"""
        async () => {{
            try {{
                const resp = await fetch('{url}', {{
                    method: 'GET', credentials: 'include',
                    headers: {{ 'Accept': 'application/json', 'X-Requested-With': 'XMLHttpRequest' }}
                }});
                if (!resp.ok) return {{ error: true, status: resp.status }};
                const json = await resp.json();
                return {{ count: (json.data || []).length, data: json.data || [] }};
            }} catch(e) {{ return {{ error: true, message: e.message }}; }}
        }}
        """
        result = self._page.evaluate(js_code)
        self.stats["pages_loaded"] += 1
        # API 请求间隔（知乎限制 ~30 req/min）
        time.sleep(1.5 + random.random() * 1.5)

        if not result or result.get("error"):
            status = result.get("status", "?") if result else "null"
            logger.warning(f"  搜索 API 异常 (status={status}, msg={result.get('message','')})")
            return []

        data = result.get("data", [])
        if not isinstance(data, list):
            return []

        items = []
        for raw in data:
            # API 包装层: {type:"search_result", object:{...}}
            obj = raw.get("object", raw)
            item = self._parse_api_item(obj, keyword)
            if item:
                items.append(item)
        return items

    def _call_answers_api(self, question_id: str) -> list[dict]:
        """浏览器内 fetch 获取问题回答。"""
        url = self.ANSWERS_API.format(qid=question_id)
        url += f"?limit={self.max_answers}&offset=0"
        url += "&include=data[*].content,comment_count,voteup_count,created_time,author"
        js_code = f"""
        async () => {{
            try {{
                const resp = await fetch('{url}', {{
                    method: 'GET', credentials: 'include',
                    headers: {{ 'Accept': 'application/json', 'X-Requested-With': 'XMLHttpRequest' }}
                }});
                if (!resp.ok) return {{ error: true }};
                const json = await resp.json();
                return {{ data: json.data || [] }};
            }} catch(e) {{ return {{ error: true }}; }}
        }}
        """
        result = self._page.evaluate(js_code)
        if not result or result.get("error"):
            return []

        data = result.get("data", [])
        if not isinstance(data, list):
            return []

        answers = []
        for a in data:
            author = a.get("author", {}) or {}
            answers.append({
                "author_username": author.get("name", ""),
                "author_uid": str(author.get("id", "")),
                "content": self.clean_html(a.get("content", "")),
                "voteup_count": a.get("voteup_count", 0),
                "comment_count": a.get("comment_count", 0),
                "created_time": self.ts_to_datetime(a.get("created_time", 0)),
            })
        return answers

    # ── 数据解析 ──────────────────────────────────────────────────────────

    def _parse_api_item(self, obj: dict, keyword: str) -> ParsedZhihuItem | None:
        """解析单条搜索 API 返回的 object。"""
        result_type = obj.get("type", "")
        question = obj.get("question", {}) or {}
        title = question.get("title", "") or obj.get("title", "")
        if not title:
            return None

        qid = str(question.get("id", "") or obj.get("id", ""))
        question_url = question.get("url", "") or obj.get("url", "")
        if question_url and not question_url.startswith("http"):
            question_url = f"https://www.zhihu.com{question_url}"

        excerpt = self.clean_html(obj.get("excerpt", ""))
        content_raw = f"【问题】{title}"
        if excerpt and excerpt != title:
            content_raw += f"\n【摘要】{excerpt}"

        author = obj.get("author", {}) or {}
        topics = [t.get("name", "") for t in (question.get("topics", []) or []) if isinstance(t, dict)]

        return ParsedZhihuItem(
            content_raw=content_raw,
            source_url=question_url,
            author_uid=str(author.get("id", "")),
            author_username=author.get("name", ""),
            question_id=qid,
            answer_id=str(obj.get("id", "")),
            collected_at=self.ts_to_datetime(obj.get("created_time", 0)),
            keyword=keyword,
            voteup_count=obj.get("voteup_count", 0),
            comment_count=obj.get("comment_count", 0),
            topics=topics,
            metadata={
                "keyword": keyword,
                "result_type": result_type,
                "voteup_count": obj.get("voteup_count", 0),
                "comment_count": obj.get("comment_count", 0),
                "topics": topics,
                "has_emoji": self.contains_emoji(title + excerpt),
            },
        )
