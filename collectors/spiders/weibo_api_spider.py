"""
微博 AJAX API Spider — 纯 HTTP 请求，无需浏览器。
基于微博内部 AJAX 接口，速度快、无验证码。

API 端点:
  - 搜索:  weibo.com/ajax/statuses/search?q={keyword}&page={page}&count={count}
  - 热搜:  weibo.com/ajax/side/hotSearch
  - 评论:  weibo.com/ajax/statuses/buildComments?id={post_id}&count={count}
"""

import time
import random
import requests
from datetime import datetime, timezone, timedelta
from dataclasses import dataclass, field
from loguru import logger

from collectors.base import now_bjt
from collectors.spiders.base_spider import BaseSpider


@dataclass
class ParsedWeiboAPIItem:
    platform: str = "weibo"
    content_raw: str = ""
    content_type: str = "text"
    source_url: str = ""
    author_uid: str = ""
    author_username: str = ""
    weibo_id: str = ""
    collected_at: datetime = field(default_factory=datetime.utcnow)
    keyword: str = ""
    reposts_count: int = 0
    comments_count: int = 0
    attitudes_count: int = 0
    metadata: dict = field(default_factory=dict)


class WeiboAPISpider:
    """微博 AJAX API Spider — 纯 requests，零浏览器开销。

    使用方式:
        spider = WeiboAPISpider()
        items = spider.search("刷单", max_pages=3, count=20)
        hot = spider.get_hot_search()
    """

    PLATFORM = "weibo"
    SEARCH_API = "https://weibo.com/ajax/statuses/search"
    HOT_SEARCH_API = "https://weibo.com/ajax/side/hotSearch"
    COMMENT_API = "https://weibo.com/ajax/statuses/buildComments"
    PAGE_SIZE = 20
    MIN_DELAY = 0.8
    MAX_DELAY = 2.0

    def __init__(self):
        self._session = requests.Session()
        self._cookies_loaded = False

    @classmethod
    def interactive_login(cls, headless: bool = False):
        """弹出浏览器完成微博登录，并保存给 HTTP API Spider 复用的 Cookie。

        WeiboAPISpider 本身是 requests 采集器，不继承 BaseSpider；
        这里仅提供一个兼容入口，避免答辩手册中的登录命令报错。
        """
        class _WeiboCookieLoginSpider(BaseSpider):
            PLATFORM = "weibo"
            HOME_URL = "https://weibo.com"
            PAGE_SIZE = cls.PAGE_SIZE

            def search_and_parse(self, keyword: str, max_pages: int = 3, **kwargs) -> list:
                return []

        return _WeiboCookieLoginSpider.interactive_login(headless=headless)

    # ═══════════════════════════════════════════════════════════════════════════
    # Cookie 管理
    # ═══════════════════════════════════════════════════════════════════════════

    def _load_cookies(self):
        """从文件/环境变量加载 Cookie 到 requests session。"""
        if self._cookies_loaded:
            return
        cookies = BaseSpider.load_cookies("weibo")
        if cookies:
            for c in cookies:
                self._session.cookies.set(
                    c.get("name", ""), str(c.get("value", "")),
                    domain=c.get("domain", ""), path=c.get("path", "/"),
                )
            logger.info(f"已加载 {len(cookies)} 条微博 Cookie")
        else:
            logger.warning("未找到微博 Cookie，搜索功能可能受限")
        self._cookies_loaded = True

    @property
    def headers(self) -> dict:
        return {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/131.0.0.0 Safari/537.36"
            ),
            "Referer": "https://weibo.com/",
            "X-Requested-With": "XMLHttpRequest",
            "Accept": "application/json, text/plain, */*",
        }

    # ═══════════════════════════════════════════════════════════════════════════
    # 热搜榜
    # ═══════════════════════════════════════════════════════════════════════════

    def get_hot_search(self) -> list[dict]:
        """获取微博热搜榜（公开 API，但加 Cookie 更稳定）。

        Returns:
            [{word, note, label_name, num, url, ...}, ...]
        """
        self._load_cookies()
        resp = self._session.get(
            self.HOT_SEARCH_API, headers=self.headers, timeout=15,
        )
        if resp.status_code != 200:
            logger.error(f"热搜 API 失败: HTTP {resp.status_code}")
            return []
        data = resp.json()
        realtime = data.get("data", {}).get("realtime", [])
        logger.info(f"获取热搜 {len(realtime)} 条")
        return realtime

    # ═══════════════════════════════════════════════════════════════════════════
    # 关键词搜索
    # ═══════════════════════════════════════════════════════════════════════════

    def search(
        self, keyword: str, max_pages: int = 3, count: int = 20,
    ) -> list[ParsedWeiboAPIItem]:
        """按关键词搜索微博帖子。

        Args:
            keyword: 搜索关键词
            max_pages: 最大翻页数
            count: 每页条数 (max ~50)

        Returns:
            ParsedWeiboAPIItem 列表
        """
        self._load_cookies()
        all_items = []
        page = 1

        while page <= max_pages:
            logger.info(f"搜索 [{keyword}] 第{page}/{max_pages}页")
            items = self._search_page(keyword, page, count)
            if not items:
                logger.info(f"  第{page}页无结果，停止翻页")
                break
            all_items.extend(items)
            logger.info(f"  第{page}页: {len(items)} 条 (累计 {len(all_items)})")
            page += 1
            if page <= max_pages:
                time.sleep(self.MIN_DELAY + random.random() * (self.MAX_DELAY - self.MIN_DELAY))

        logger.info(f"[{keyword}] 搜索完成: {len(all_items)} 条")
        return all_items

    def _search_page(
        self, keyword: str, page: int, count: int,
    ) -> list[ParsedWeiboAPIItem]:
        """请求单页搜索结果。"""
        from urllib.parse import quote
        url = f"{self.SEARCH_API}?q={quote(keyword)}&page={page}&count={count}"
        try:
            resp = self._session.get(url, headers=self.headers, timeout=15)
            if resp.status_code != 200:
                logger.warning(f"  搜索 API HTTP {resp.status_code}")
                return []
            data = resp.json()
            if data.get("ok") != 1:
                logger.warning(f"  搜索 API ok={data.get('ok')}")
                return []
            statuses = data.get("statuses", [])
            return [self._parse_status(s, keyword) for s in statuses]
        except Exception as exc:
            logger.error(f"  搜索请求异常: {exc}")
            return []

    def _parse_status(self, s: dict, keyword: str) -> ParsedWeiboAPIItem:
        """解析单个微博帖子。"""
        user = s.get("user", {})
        weibo_id = str(s.get("id", ""))

        # 文本（优先长文本）
        text = s.get("text_raw", "") or s.get("text", "")
        is_long = s.get("isLongText", False)

        # 图片
        pics = s.get("pic_ids", []) or []
        pic_num = s.get("pic_num", 0)

        # 转发
        retweeted = s.get("retweeted_status")
        if retweeted:
            rt_user = retweeted.get("user", {}).get("screen_name", "")
            rt_text = retweeted.get("text_raw", "")[:100]
            text = f"{text}\n//转发 @{rt_user}: {rt_text}"

        # 时间解析
        created_at = s.get("created_at", "")
        try:
            # "Tue Jun 02 18:12:10 +0800 2026"
            from datetime import datetime as dt
            collected = dt.strptime(created_at, "%a %b %d %H:%M:%S %z %Y")
        except Exception:
            collected = now_bjt()

        # 构建 source_url
        uid = str(user.get("id", ""))
        mid = s.get("mid", "") or weibo_id
        source_url = f"https://weibo.com/{uid}/{mid}" if uid else f"https://weibo.com/detail/{weibo_id}"

        item = ParsedWeiboAPIItem(
            content_raw=text,
            content_type="text",
            source_url=source_url,
            author_uid=str(user.get("id", "")),
            author_username=user.get("screen_name", ""),
            weibo_id=weibo_id,
            collected_at=collected,
            keyword=keyword,
            reposts_count=s.get("reposts_count", 0),
            comments_count=s.get("comments_count", 0),
            attitudes_count=s.get("attitudes_count", 0),
            metadata={
                "keyword": keyword,
                "weibo_id": weibo_id,
                "has_image": pic_num > 0,
                "has_video": s.get("page_info", {}).get("type", "") == "video",
                "is_long_text": is_long,
                "source": s.get("source", ""),
                "region_name": s.get("region_name", ""),
                "reposts_count": s.get("reposts_count", 0),
                "comments_count": s.get("comments_count", 0),
                "attitudes_count": s.get("attitudes_count", 0),
            },
        )
        return item

    # ═══════════════════════════════════════════════════════════════════════════
    # 评论获取
    # ═══════════════════════════════════════════════════════════════════════════

    def get_comments(
        self, weibo_id: str, max_pages: int = 3, count: int = 20,
    ) -> list[dict]:
        """获取指定微博的评论。

        Args:
            weibo_id: 微博帖子 ID
            max_pages: 最大翻页数
            count: 每页评论数

        Returns:
            [{id, screen_name, text_raw, like_counts, created_at, ...}, ...]
        """
        self._load_cookies()
        all_comments = []
        max_id = ""

        for _ in range(max_pages):
            params = f"is_reload=1&id={weibo_id}&is_show_bulletin=2&is_mix=0&count={count}&fetch_level=0&locale=zh-CN"
            url = f"{self.COMMENT_API}?{params}&max_id={max_id}" if max_id else f"{self.COMMENT_API}?{params}"

            try:
                resp = self._session.get(url, headers=self.headers, timeout=15)
                if resp.status_code != 200:
                    break
                data = resp.json()
                comments = data.get("data", [])
                if not comments:
                    break
                all_comments.extend(comments)
                max_id = str(data.get("max_id", ""))
                if not max_id:
                    break
                time.sleep(0.5 + random.random() * 1.0)
            except Exception as exc:
                logger.error(f"  评论获取异常 [{weibo_id}]: {exc}")
                break

        logger.info(f"  获取评论 {len(all_comments)} 条 [weibo_id={weibo_id}]")
        return all_comments
