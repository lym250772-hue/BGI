"""Web forum / BBS collector using Scrapy + Playwright (stub — extend for P0)."""
import hashlib
from typing import Iterator
from datetime import datetime

from collectors.base import BaseCollector, IntelItem


class WebCollector(BaseCollector):
    """Generic web scraper for public forums (Tieba, Zhihu, etc.).

    Currently a stub – implement Scrapy spiders in collectors/spiders/.
    """

    def __init__(self, platform: str, urls: list[str]):
        self.platform = platform
        self.urls = urls

    def collect(self) -> Iterator[IntelItem]:
        # Stub: yield a placeholder item to validate the pipeline
        for url in self.urls:
            yield IntelItem(
                platform=self.platform,
                content_raw=f"[STUB] Placeholder content from {url}",
                content_type="text",
                source_url=url,
                image_hash=hashlib.md5(url.encode()).hexdigest(),
                collected_at=datetime.utcnow(),
            )
        # TODO: Replace with actual Scrapy spider integration
        # See collectors/spiders/ for crawl logic
