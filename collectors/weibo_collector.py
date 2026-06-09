"""微博关键词搜索采集器 — 纯HTTP AJAX API，零浏览器开销，产出 IntelItem。"""

from typing import Iterator
from loguru import logger

from collectors.base import BaseCollector, IntelItem
from collectors.spiders.weibo_api_spider import WeiboAPISpider
from collectors.normalizer import normalize_weibo


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
        fetch_comments: bool = True,
    ):
        """
        Args:
            keywords: 搜索关键词列表
            max_pages_per_keyword: 每个关键词最多翻页数
            fetch_comments: 是否采集评论
        """
        self.keywords = keywords
        self.max_pages = max_pages_per_keyword
        self.fetch_comments = fetch_comments

    def collect(self) -> Iterator[IntelItem]:
        """执行采集，逐条产出 IntelItem。"""
        spider = WeiboAPISpider()

        for keyword in self.keywords:
            logger.info(f"开始采集关键词: [{keyword}]")
            parsed_items = spider.search(keyword, max_pages=self.max_pages)

            for parsed in parsed_items:
                # 采集评论
                if self.fetch_comments and parsed.weibo_id:
                    try:
                        comments = spider.get_comments(parsed.weibo_id, max_pages=2)
                        parsed.metadata["comments"] = comments
                    except Exception as exc:
                        logger.debug(f"  评论采集失败 [{parsed.weibo_id}]: {exc}")

                yield normalize_weibo(parsed)

            logger.info(f"关键词 [{keyword}] 采集完成，共 {len(parsed_items)} 条")
