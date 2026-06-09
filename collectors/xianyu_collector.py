"""
闲鱼采集器 — BaseCollector 实现。

封装 XianyuSearchSpider 生命周期，
将 ParsedXianyuItem 转换为 IntelItem 通过 normalizer。
"""

from collectors.base import BaseCollector, IntelItem
from collectors.spiders.xianyu_spider import XianyuSearchSpider
from collectors.normalizer import normalize_xianyu
from loguru import logger


class XianyuCollector(BaseCollector):
    """闲鱼二手交易平台采集器。

    使用 v3 持久化浏览器进行搜索采集，
    支持关键词搜索 + 商品详情留言提取。
    """

    def __init__(
        self,
        keywords: list[str] = None,
        max_pages_per_keyword: int = 3,
        headless: bool = False,
    ):
        self.keywords = keywords or []
        self.max_pages = max_pages_per_keyword
        self.headless = headless  # 闲鱼强制非headless

    def collect(self) -> IntelItem:
        """执行采集，逐条产出 IntelItem。"""
        spider = XianyuSearchSpider(headless=False)
        try:
            spider.start()
            for keyword in self.keywords:
                logger.info(f"闲鱼搜索: [{keyword}]")
                items = spider.search_and_parse(
                    keyword, max_pages=self.max_pages,
                )
                for parsed in items:
                    yield normalize_xianyu(parsed)

                # 如果需要采集留言
                # for parsed in items[:5]:  # 限量前5条详情
                #     if parsed.item_id:
                #         messages = spider.fetch_item_messages(parsed.item_id)
                #         # messages 可附加到对应的 IntelItem.comments

        finally:
            spider.close()
