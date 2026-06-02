"""知乎关键词搜索采集器 — 符合 BaseCollector 接口，产出 IntelItem。"""

from typing import Iterator, Optional
from datetime import datetime

from loguru import logger

from collectors.base import BaseCollector, IntelItem
from collectors.spiders.zhihu_spider import ZhihuSearchSpider


class ZhihuCollector(BaseCollector):
    """知乎关键词搜索采集器。

    使用方式:
        collector = ZhihuCollector(
            keywords=["刷单", "接码"],
            max_pages_per_keyword=3,
            fetch_answers=True,
        )
        for item in collector.collect():
            print(item.content_raw)
    """

    def __init__(
        self,
        keywords: list[str],
        max_pages_per_keyword: int = 10,
        max_items_per_keyword: int = 0,
        fetch_answers: bool = True,
        fetch_comments: bool = False,
        incremental: bool = False,
        headless: bool = True,
    ):
        self.keywords = keywords
        self.max_pages = max_pages_per_keyword
        self.max_items = max_items_per_keyword
        self.fetch_answers = fetch_answers
        self.fetch_comments = fetch_comments
        self.incremental = incremental
        self.headless = headless

    def collect(self) -> Iterator[IntelItem]:
        """执行采集，逐条产出 IntelItem。"""
        spider: Optional[ZhihuSearchSpider] = None
        try:
            spider = ZhihuSearchSpider(
                headless=self.headless,
                fetch_answers=self.fetch_answers,
                fetch_comments=self.fetch_comments,
            )
            spider.start()

            for keyword in self.keywords:
                logger.info(f"开始采集知乎关键词: [{keyword}]")
                parsed_items = spider.search_and_parse(
                    keyword, max_pages=self.max_pages,
                    max_items=self.max_items,
                    incremental=self.incremental,
                )
                # 非增量模式：清空增量状态，全量采集
                if not self.incremental:
                    spider._last_collected_at.pop(keyword, None)
                for parsed in parsed_items:
                    yield self._to_intel_item(parsed)

                logger.info(f"知乎关键词 [{keyword}] 采集完成，共 {len(parsed_items)} 条")

        finally:
            if spider:
                spider.close()

    # ── 内部转换 ──────────────────────────────────────────────────────────

    @staticmethod
    def _to_intel_item(parsed) -> IntelItem:
        """将 ParsedZhihuItem 转换为 IntelItem。"""
        metadata = {
            "keyword": parsed.keyword,
            "question_id": parsed.question_id,
            "answer_id": parsed.answer_id,
            "voteup_count": parsed.voteup_count,
            "comment_count": parsed.comment_count,
            "topics": parsed.topics,
            "result_type": parsed.metadata.get("result_type", ""),
            "has_emoji": parsed.metadata.get("has_emoji", False),
            "answers": parsed.metadata.get("answers", []),
            "answer_count": parsed.metadata.get("answer_count", 0),
        }

        return IntelItem(
            platform="zhihu",
            content_raw=parsed.content_raw,
            content_type=parsed.content_type,
            source_url=parsed.source_url,
            author_uid=parsed.author_uid,
            author_username=parsed.author_username,
            group_id=parsed.keyword,       # 用搜索关键词作为分组标识
            collected_at=parsed.collected_at or datetime.utcnow(),
            metadata=metadata,
        )
