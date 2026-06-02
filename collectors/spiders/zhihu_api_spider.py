"""
知乎 API Spider — 纯 HTTP 请求，无需浏览器。

基于知乎内部 /api/v4 端点，沿用微博 AJAX 模式：
  - 搜索:  /api/v4/search_v3?q={keyword}&type=content&offset={offset}&limit={limit}
  - 答案:  /api/v4/questions/{qid}/answers?limit={n}&offset=0
  - 评论:  /api/v4/answers/{aid}/comments?limit={n}&offset=0

速度: 3-5条/秒（vs Playwright 0.2条/秒）
"""

import time
import random
import requests
from datetime import datetime
from dataclasses import dataclass, field
from loguru import logger

from collectors.spiders.base_spider import BaseSpider


@dataclass
class ParsedZhihuAPIItem:
    """知乎搜索结果条目（纯API版本）。"""
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
    image_list: list[str] = field(default_factory=list)
    metadata: dict = field(default_factory=dict)


class ZhihuAPISpider:
    """知乎 API Spider — 纯 requests，零浏览器开销。

    使用方式:
        spider = ZhihuAPISpider()
        items = spider.search("刷单", max_pages=3)
        answers = spider.get_answers("question_id_123")
    """

    PLATFORM = "zhihu"
    SEARCH_API = "https://www.zhihu.com/api/v4/search_v3"
    ANSWERS_API = "https://www.zhihu.com/api/v4/questions/{qid}/answers"
    COMMENTS_API = "https://www.zhihu.com/api/v4/answers/{aid}/comments"
    PAGE_SIZE = 20
    MIN_DELAY = 1.5
    MAX_DELAY = 3.0

    def __init__(self, fetch_answers: bool = True, max_answers: int = 3,
                 fetch_comments: bool = True):
        self._session = requests.Session()
        self._cookies_loaded = False
        self.fetch_answers = fetch_answers
        self.max_answers = max_answers
        self.fetch_comments = fetch_comments

    # ═══════════════════════════════════════════════════════════════════════════
    # Cookie
    # ═══════════════════════════════════════════════════════════════════════════

    def _load_cookies(self):
        if self._cookies_loaded:
            return
        cookies = BaseSpider.load_cookies("zhihu")
        if cookies:
            for c in cookies:
                self._session.cookies.set(
                    c.get("name", ""), str(c.get("value", "")),
                    domain=c.get("domain", ""), path=c.get("path", "/"),
                )
            logger.info(f"已加载 {len(cookies)} 条知乎 Cookie")
        else:
            logger.warning("未找到知乎 Cookie，搜索可能受限")
        self._cookies_loaded = True

    @property
    def headers(self) -> dict:
        return {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/131.0.0.0 Safari/537.36"
            ),
            "Accept": "application/json, text/plain, */*",
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
            "X-Requested-With": "XMLHttpRequest",
            "Referer": "https://www.zhihu.com/search?type=content",
        }

    # ═══════════════════════════════════════════════════════════════════════════
    # 搜索
    # ═══════════════════════════════════════════════════════════════════════════

    def search(
        self, keyword: str, max_pages: int = 3, **kwargs,
    ) -> list[ParsedZhihuAPIItem]:
        """按关键词搜索知乎内容。

        Args:
            keyword: 搜索关键词
            max_pages: 最大翻页数

        Returns:
            ParsedZhihuAPIItem 列表
        """
        self._load_cookies()
        all_items = []
        page_num = 0
        consecutive_empty = 0

        while True:
            page_num += 1
            if max_pages > 0 and page_num > max_pages:
                break
            offset = (page_num - 1) * self.PAGE_SIZE
            label = f"第{page_num}/{max_pages}页" if max_pages else f"第{page_num}页"
            logger.info(f"搜索 [{keyword}] {label} (offset={offset})")

            items = self._search_page(keyword, offset)
            if not items:
                consecutive_empty += 1
                if consecutive_empty >= 3:
                    break
                continue

            for item in items:
                all_items.append(item)

            logger.info(f"  {label}: {len(items)} 条 (累计 {len(all_items)})")

            if page_num < max_pages:
                time.sleep(self.MIN_DELAY + random.random() * (self.MAX_DELAY - self.MIN_DELAY))

        logger.info(f"[{keyword}] 搜索完成: {len(all_items)} 条")
        return all_items

    def _search_page(
        self, keyword: str, offset: int,
    ) -> list[ParsedZhihuAPIItem]:
        """请求单页搜索结果，并可选拉取答案+评论。"""
        from urllib.parse import quote
        url = (
            f"{self.SEARCH_API}?q={quote(keyword)}&type=content"
            f"&offset={offset}&limit={self.PAGE_SIZE}"
        )
        try:
            resp = self._session.get(url, headers=self.headers, timeout=20)
            if resp.status_code != 200:
                logger.warning(f"  搜索 API HTTP {resp.status_code}")
                return []
            data = resp.json()
            raw_items = data.get("data", [])
            if not raw_items:
                return []

            parsed = []
            for obj in raw_items:
                item = self._parse_search_object(obj, keyword)
                if not item or not item.content_raw:
                    continue

                # 拉取问题的答案
                if self.fetch_answers and item.question_id:
                    try:
                        answers = self.get_answers(item.question_id,
                                                   limit=self.max_answers)
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

                            # 拉取答案的评论
                            if self.fetch_comments:
                                for ans in answers:
                                    aid = ans.get("answer_id", "")
                                    if aid:
                                        comments = self.get_comments(aid)
                                        if comments:
                                            ans["comments"] = comments
                                            item.metadata.setdefault(
                                                "comments", []).extend(comments)
                        time.sleep(0.5 + random.random() * 1.0)
                    except Exception as exc:
                        logger.debug(f"  拉取答案失败: {exc}")

                parsed.append(item)

            return parsed
        except Exception as exc:
            logger.error(f"  搜索请求异常: {exc}")
            return []

    def _parse_search_object(
        self, obj: dict, keyword: str,
    ) -> ParsedZhihuAPIItem | None:
        """解析单个搜索结果对象。"""
        obj_type = obj.get("type", "")
        target = obj.get("object", {}) or obj.get("target", {}) or obj

        if obj_type == "search_result":
            question = target.get("question", {})
            author = target.get("author", {})

            content_raw = self._clean_html(target.get("excerpt", ""))
            if not content_raw:
                content_raw = target.get("title", "") or question.get("title", "")

            question_id = str(question.get("id", ""))
            answer_id = str(target.get("id", ""))

            # 图片
            image_list = []
            for img_url in target.get("image_urls", []) or []:
                if img_url:
                    image_list.append(img_url)

            # 话题
            topics = []
            for t in question.get("topics", []) or []:
                if isinstance(t, dict):
                    topics.append(t.get("name", ""))

            return ParsedZhihuAPIItem(
                content_raw=content_raw,
                source_url=target.get("url", f"https://www.zhihu.com/question/{question_id}"),
                author_uid=str(author.get("id", "")),
                author_username=author.get("name", ""),
                question_id=question_id,
                answer_id=answer_id,
                collected_at=datetime.utcnow(),
                keyword=keyword,
                voteup_count=target.get("voteup_count", 0) or target.get("voteupCount", 0),
                comment_count=target.get("comment_count", 0) or target.get("commentCount", 0),
                topics=topics,
                image_list=image_list,
                metadata={
                    "keyword": keyword,
                    "question_id": question_id,
                    "answer_id": answer_id,
                    "voteup_count": target.get("voteup_count", 0),
                    "comment_count": target.get("comment_count", 0),
                    "topics": topics,
                    "image_list": image_list,
                },
            )

        # 回退 — 使用 title
        return None

    # ═══════════════════════════════════════════════════════════════════════════
    # 答案获取
    # ═══════════════════════════════════════════════════════════════════════════

    def get_answers(self, question_id: str, limit: int = 3) -> list[dict]:
        """获取某问题的高赞回答。

        Args:
            question_id: 知乎问题 ID
            limit: 最多获取几条回答

        Returns:
            [{answer_id, author_username, author_uid, content, voteup_count,
              comment_count, created_time}, ...]
        """
        self._load_cookies()
        url = self.ANSWERS_API.format(qid=question_id)
        params = (
            f"limit={limit}&offset=0"
            "&include=data[*].content,comment_count,voteup_count,created_time,author"
        )
        url = f"{url}?{params}"

        try:
            resp = self._session.get(url, headers=self.headers, timeout=20)
            if resp.status_code != 200:
                return []
            data = resp.json()
            raw_answers = data.get("data", [])
            answers = []
            for a in raw_answers:
                author = a.get("author", {})
                answers.append({
                    "answer_id": str(a.get("id", "")),
                    "author_username": author.get("name", ""),
                    "author_uid": str(author.get("id", "")),
                    "content": self._clean_html(a.get("content", "") or ""),
                    "voteup_count": a.get("voteup_count", 0),
                    "comment_count": a.get("comment_count", 0),
                    "created_time": datetime.fromtimestamp(
                        a.get("created_time", 0) or a.get("createdTime", 0),
                    ) if (a.get("created_time") or a.get("createdTime")) else None,
                })
            return answers
        except Exception as exc:
            logger.debug(f"  拉取答案异常 [{question_id}]: {exc}")
            return []

    # ═══════════════════════════════════════════════════════════════════════════
    # 评论获取
    # ═══════════════════════════════════════════════════════════════════════════

    def get_comments(self, answer_id: str, limit: int = 10) -> list[dict]:
        """获取某回答的评论。

        Args:
            answer_id: 知乎回答 ID
            limit: 最多获取几条评论

        Returns:
            [{comment_id, author_username, content, voteup_count, created_time}, ...]
        """
        self._load_cookies()
        url = self.COMMENTS_API.format(aid=answer_id)
        url = f"{url}?limit={limit}&offset=0"

        try:
            resp = self._session.get(url, headers=self.headers, timeout=20)
            if resp.status_code != 200:
                return []
            data = resp.json()
            raw_comments = data.get("data", [])
            comments = []
            for c in raw_comments:
                author = c.get("author", {}).get("member", {}) or c.get("author", {})
                comments.append({
                    "comment_id": str(c.get("id", "")),
                    "author_username": author.get("name", ""),
                    "author_uid": str(author.get("id", "")),
                    "content": self._clean_html(c.get("content", "") or ""),
                    "voteup_count": c.get("vote_count", 0),
                    "created_time": datetime.fromtimestamp(
                        c.get("created_time", 0),
                    ) if c.get("created_time") else None,
                })
            return comments
        except Exception as exc:
            logger.debug(f"  拉取评论异常 [{answer_id}]: {exc}")
            return []

    # ═══════════════════════════════════════════════════════════════════════════
    # 工具
    # ═══════════════════════════════════════════════════════════════════════════

    @staticmethod
    def _clean_html(text: str) -> str:
        """移除 HTML 标签，保留纯文本。"""
        import re
        if not text:
            return ""
        # Remove tags, entities, extra whitespace
        text = re.sub(r"<[^>]+>", "", text)
        text = text.replace("&nbsp;", " ").replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">")
        text = re.sub(r"\s+", " ", text).strip()
        return text
