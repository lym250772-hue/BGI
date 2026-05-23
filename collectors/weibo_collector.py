"""微博关键词搜索采集器 — 符合 BaseCollector 接口，产出 IntelItem。"""

from typing import Iterator, Optional
from datetime import datetime

from loguru import logger

from collectors.base import BaseCollector, IntelItem
from collectors.spiders.weibo_spider import WeiboSearchSpider


class WeiboCollector(BaseCollector):
    """微博关键词搜索采集器。

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
        headless: bool = True,
    ):
        """
        Args:
            keywords: 搜索关键词列表
            max_pages_per_keyword: 每个关键词最多翻页数
            headless: 是否无头模式（调试时可设为 False 看到浏览器操作）
        """
        self.keywords = keywords
        self.max_pages = max_pages_per_keyword
        self.headless = headless

    def collect(self) -> Iterator[IntelItem]:
        """执行采集，逐条产出 IntelItem。"""
        spider: Optional[WeiboSearchSpider] = None
        try:
            spider = WeiboSearchSpider(headless=self.headless)
            spider.start()

            for keyword in self.keywords:
                logger.info(f"开始采集关键词: [{keyword}]")
                parsed_items = spider.search_and_parse(
                    keyword, max_pages=self.max_pages
                )
                for parsed in parsed_items:
                    yield self._to_intel_item(parsed)

                logger.info(f"关键词 [{keyword}] 采集完成，共 {len(parsed_items)} 条")

        finally:
            if spider:
                spider.close()

    # ── 内部转换 ──────────────────────────────────────────────────────────

    @staticmethod
    def _to_intel_item(parsed) -> IntelItem:
        """将 ParsedWeiboItem 转换为 IntelItem。"""
        return IntelItem(
            platform="weibo",
            content_raw=parsed.content_raw,
            content_type=parsed.content_type,
            source_url=parsed.source_url,
            author_uid=parsed.author_uid,
            author_username=parsed.author_username,
            group_id=parsed.keyword,  # 用搜索关键词作为分组标识
            collected_at=parsed.collected_at,
            metadata={
                "keyword": parsed.keyword,
                "weibo_id": parsed.weibo_id,
                "has_image": parsed.metadata.get("has_image", False),
                "has_video": parsed.metadata.get("has_video", False),
                "is_long_text": parsed.metadata.get("is_long_text", False),
            },
        )
