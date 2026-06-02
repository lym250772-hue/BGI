"""通用 Web 采集器 — 小红书 / 论坛 / 垂直站点的 stub 实现。

当前为占位实现，待后续开发。
"""

from typing import Iterator
from datetime import datetime

from loguru import logger

from collectors.base import BaseCollector, IntelItem


class WebCollector(BaseCollector):
    """通用 Web 采集器（stub）。

    使用方式:
        collector = WebCollector(urls=["https://example.com/page1"])
        for item in collector.collect():
            print(item.content_raw)
    """

    def __init__(self, urls: list[str]):
        """
        Args:
            urls: 待采集的 URL 列表
        """
        self.urls = urls

    def collect(self) -> Iterator[IntelItem]:
        """当前为占位实现，等待后续开发。"""
        logger.warning(
            f"WebCollector is a stub — {len(self.urls)} URLs queued but not implemented"
        )
        # 占位：不产出任何数据
        # 后续实现: Playwright + Scrapy 通用网页采集
        return
        yield  # unreachable, makes this a generator
