"""Collector registry – maps platform names to collector classes."""
from collectors.base import BaseCollector
from collectors.telegram_collector import TelegramCollector
from collectors.web_collector import WebCollector
from collectors.weibo_collector import WeiboCollector
from collectors.tieba_collector import TiebaCollector
from collectors.zhihu_collector import ZhihuCollector


def get_collector(platform: str, **kwargs) -> BaseCollector:
    registry = {
        "telegram": lambda: TelegramCollector(group_usernames=kwargs.get("group_usernames", [])),
        "weibo": lambda: WeiboCollector(
            keywords=kwargs.get("keywords", []),
            max_pages_per_keyword=kwargs.get("max_pages_per_keyword", 3),
        ),
        "tieba": lambda: TiebaCollector(
            keywords=kwargs.get("keywords", []),
            max_pages_per_keyword=kwargs.get("max_pages_per_keyword", 3),
            fetch_replies=kwargs.get("fetch_replies", True),
        ),
        "zhihu": lambda: ZhihuCollector(
            keywords=kwargs.get("keywords", []),
            max_pages_per_keyword=kwargs.get("max_pages_per_keyword", 3),
            fetch_answers=kwargs.get("fetch_answers", True),
            fetch_comments=kwargs.get("fetch_comments", False),
        ),
        "xiaohongshu": lambda: WebCollector(platform="xiaohongshu", urls=kwargs.get("urls", [])),
        "forum": lambda: WebCollector(platform="forum", urls=kwargs.get("urls", [])),
    }
    factory = registry.get(platform)
    if not factory:
        raise ValueError(f"Unknown platform: {platform}. Available: {list(registry)}")
    return factory()
