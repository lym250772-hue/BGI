"""微博关键词搜索采集器 — 纯 AJAX API，符合 BaseCollector 接口，产出 IntelItem。"""

from typing import Iterator, Optional
from datetime import datetime

from loguru import logger

from collectors.base import BaseCollector, IntelItem
from collectors.spiders.weibo_api_spider import WeiboAPISpider


class WeiboCollector(BaseCollector):
    """微博关键词搜索采集器（AJAX API 模式，无需浏览器）。

    使用方式:
        collector = WeiboCollector(
            keywords=["刷单", "接码"],
            max_pages_per_keyword=3,
        )
        for item in collector.collect():
            print(item.content_raw)
    """

    def __init__(
        self,
        keywords: list[str],
        max_pages_per_keyword: int = 3,
        count_per_page: int = 20,
        fetch_comments: bool = False,
        headless: bool = True,  # 保留兼容
    ):
        """
        Args:
            keywords: 搜索关键词列表
            max_pages_per_keyword: 每个关键词最多翻页数
            count_per_page: 每页条数
            fetch_comments: 是否同时获取评论
            headless: 保留参数（API 模式不使用浏览器）
        """
        self.keywords = keywords
        self.max_pages = max_pages_per_keyword
        self.count_per_page = count_per_page
        self.fetch_comments = fetch_comments

    def collect(self) -> Iterator[IntelItem]:
        """执行采集，逐条产出 IntelItem。"""
        spider = WeiboAPISpider()

        for keyword in self.keywords:
            logger.info(f"开始采集关键词: [{keyword}]")
            try:
                parsed_items = spider.search(
                    keyword,
                    max_pages=self.max_pages,
                    count=self.count_per_page,
                )
            except Exception as exc:
                logger.error(f"关键词 [{keyword}] 采集失败: {exc}")
                continue

            for parsed in parsed_items:
                yield self._to_intel_item(parsed)

            logger.info(f"关键词 [{keyword}] 采集完成，共 {len(parsed_items)} 条")

        # 关掉 session
        spider._session.close()

    # ── 内部转换 ──────────────────────────────────────────────────────────

    @staticmethod
    def _to_intel_item(parsed) -> IntelItem:
        """将 ParsedWeiboAPIItem 转换为 IntelItem。"""
        return IntelItem(
            platform="weibo",
            content_raw=parsed.content_raw,
            content_type=parsed.content_type,
            source_url=parsed.source_url,
            author_uid=parsed.author_uid,
            author_username=parsed.author_username,
            group_id=parsed.keyword,
            collected_at=parsed.collected_at,
            metadata={
                "keyword": parsed.keyword,
                "weibo_id": parsed.weibo_id,
                "has_image": parsed.metadata.get("has_image", False),
                "has_video": parsed.metadata.get("has_video", False),
                "is_long_text": parsed.metadata.get("is_long_text", False),
                "reposts_count": parsed.reposts_count,
                "comments_count": parsed.comments_count,
                "attitudes_count": parsed.attitudes_count,
                "source": parsed.metadata.get("source", ""),
                "region_name": parsed.metadata.get("region_name", ""),
                "fetch_method": "ajax_api",
            },
        )
