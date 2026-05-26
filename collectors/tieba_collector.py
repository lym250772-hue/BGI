"""贴吧关键词搜索采集器 — 符合 BaseCollector 接口，产出 IntelItem。"""

from typing import Iterator, Optional
from datetime import datetime

from loguru import logger

from collectors.base import BaseCollector, IntelItem
from collectors.spiders.tieba_spider import TiebaSpider


class TiebaCollector(BaseCollector):
    """贴吧关键词搜索采集器。

    使用方式:
        collector = TiebaCollector(
            keywords=["刷单", "接码"],
            max_pages_per_keyword=3,
            fetch_replies=True,
        )
        for item in collector.collect():
            print(item.content_raw)
    """

    def __init__(
        self,
        keywords: list[str],
        max_pages_per_keyword: int = 3,
        fetch_replies: bool = True,
        headless: bool = True,
    ):
        """
        Args:
            keywords: 搜索关键词列表
            max_pages_per_keyword: 每个关键词最多翻页数
            fetch_replies: 是否进入帖子详情页采集回复
            headless: 是否无头模式
        """
        self.keywords = keywords
        self.max_pages = max_pages_per_keyword
        self.fetch_replies = fetch_replies
        self.headless = headless

    def collect(self) -> Iterator[IntelItem]:
        """执行采集，逐条产出 IntelItem。"""
        spider: Optional[TiebaSpider] = None
        try:
            spider = TiebaSpider(
                headless=self.headless,
                fetch_replies=self.fetch_replies,
            )
            spider.start()

            for keyword in self.keywords:
                logger.info(f"开始采集贴吧关键词: [{keyword}]")
                parsed_items = spider.search_and_parse(
                    keyword, max_pages=self.max_pages,
                )
                for parsed in parsed_items:
                    yield self._to_intel_item(parsed)

                logger.info(f"贴吧关键词 [{keyword}] 采集完成，共 {len(parsed_items)} 条")

        finally:
            if spider:
                spider.close()

    # ── 内部转换 ──────────────────────────────────────────────────────────

    @staticmethod
    def _to_intel_item(parsed) -> IntelItem:
        """将 ParsedTiebaItem 转换为 IntelItem。"""
        # 序列化回复列表为 JSON 字符串存入 metadata
        metadata = {
            "keyword": parsed.keyword,
            "bar_name": parsed.bar_name,
            "thread_id": parsed.thread_id,
            "reply_count": parsed.reply_count,
            "has_image": parsed.metadata.get("has_image", False),
            "has_emoji": parsed.metadata.get("has_emoji", False),
            "replies": parsed.metadata.get("replies", []),
        }

        return IntelItem(
            platform="tieba",
            content_raw=parsed.content_raw,
            content_type=parsed.content_type,
            source_url=parsed.source_url,
            author_uid=parsed.author_uid,
            author_username=parsed.author_username,
            group_id=parsed.bar_name,       # 用贴吧名作为分组标识
            collected_at=parsed.collected_at or datetime.utcnow(),
            metadata=metadata,
        )
