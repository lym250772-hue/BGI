"""抖音关键词搜索采集器 — Playwright + 首页搜索框交互，产出 IntelItem。

方案:
  - 从首页搜索框输入关键词触发搜索（绕过直接 /search/ URL 的验证码）
  - DOM 提取搜索结果卡片
  - 无需 API 签名
"""

from typing import Iterator

from loguru import logger

from collectors.base import BaseCollector, IntelItem
from collectors.spiders.douyin_spider import DouyinSearchSpider


class DouyinCollector(BaseCollector):
    """抖音关键词搜索采集器（Playwright 模式）。"""

    def __init__(
        self,
        keywords: list[str] = None,
        max_pages_per_keyword: int = 3,
        max_items_per_keyword: int = 0,
        headless: bool = True,
    ):
        self.keywords = keywords or []
        self.max_pages = max_pages_per_keyword
        self.max_items = max_items_per_keyword
        self.headless = headless

    def collect(self) -> Iterator[IntelItem]:
        spider = None
        try:
            spider = DouyinSearchSpider(headless=self.headless)
            spider.start()

            for keyword in self.keywords:
                logger.info(f"开始采集抖音关键词: [{keyword}]")
                try:
                    parsed_items = spider.search_and_parse(
                        keyword,
                        max_pages=self.max_pages,
                        max_items=self.max_items,
                    )
                except Exception as exc:
                    logger.error(f"抖音关键词 [{keyword}] 采集失败: {exc}")
                    continue

                for parsed in parsed_items:
                    yield self._to_intel_item(parsed)

                logger.info(f"抖音关键词 [{keyword}] 采集完成，共 {len(parsed_items)} 条")

        finally:
            if spider:
                spider.close()

    @staticmethod
    def _to_intel_item(parsed) -> IntelItem:
        return IntelItem(
            platform="douyin",
            content_raw=parsed.content_raw,
            content_type=parsed.content_type,
            source_url=parsed.source_url,
            author_uid=parsed.author_uid,
            author_username=parsed.author_username,
            group_id=parsed.keyword,
            collected_at=parsed.collected_at,
            metadata={
                "keyword": parsed.keyword,
                "aweme_id": parsed.metadata.get("aweme_id", ""),
                "has_emoji": parsed.metadata.get("has_emoji", False),
                "hashtags": parsed.hashtags,
                "like_count": parsed.like_count,
                "comment_count": parsed.comment_count,
                "share_count": parsed.share_count,
                "play_count": parsed.play_count,
                "duration": parsed.duration,
                "video_cover_url": parsed.video_cover_url,
                "parse_method": parsed.metadata.get("parse_method", "homepage_search_dom"),
            },
        )
