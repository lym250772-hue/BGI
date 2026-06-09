"""采集器注册表 — 平台名到采集器工厂函数的映射。

新增平台采集器步骤:
  1. 创建 collectors/{platform}_collector.py，继承 BaseCollector
  2. 在此注册表的 PLATFORM_MAP 中添加条目
  3. 在 main.py collect 命令中添加参数转发逻辑

当前已注册平台: weibo, tieba, zhihu, xiaohongshu, douyin, xianyu, qq_group
(Telegram 已于 2026-06-04 停用)
"""

from typing import Optional
from collectors.base import BaseCollector


# ── 平台 → 采集器工厂映射 ──────────────────────────────────────────────────
# 每个工厂函数签名为: (**kwargs) -> BaseCollector
# kwargs 由 CLI 传入 (keywords, max_pages, fetch_replies 等)


def _get_weibo_collector(**kwargs) -> BaseCollector:
    from collectors.weibo_collector import WeiboCollector
    return WeiboCollector(
        keywords=kwargs.get("keywords", []),
        max_pages_per_keyword=kwargs.get("max_pages_per_keyword", 3),
        headless=kwargs.get("headless", True))


def _get_tieba_collector(**kwargs) -> BaseCollector:
    from collectors.tieba_collector import TiebaCollector
    return TiebaCollector(
        keywords=kwargs.get("keywords", []),
        max_pages_per_keyword=kwargs.get("max_pages_per_keyword", 3),
        fetch_replies=kwargs.get("fetch_replies", True),
        headless=kwargs.get("headless", True))


def _get_zhihu_collector(**kwargs) -> BaseCollector:
    from collectors.zhihu_collector import ZhihuCollector
    return ZhihuCollector(
        keywords=kwargs.get("keywords", []),
        max_pages_per_keyword=kwargs.get("max_pages_per_keyword", 10),
        max_items_per_keyword=kwargs.get("max_items_per_keyword", 0),
        fetch_answers=kwargs.get("fetch_answers", True),
        fetch_comments=kwargs.get("fetch_comments", False),
        incremental=kwargs.get("incremental", False),
        headless=kwargs.get("headless", True))


def _get_xiaohongshu_collector(**kwargs) -> BaseCollector:
    from collectors.xiaohongshu_collector import XiaohongshuCollector
    return XiaohongshuCollector(
        keywords=kwargs.get("keywords", []),
        max_pages_per_keyword=kwargs.get("max_pages_per_keyword", 3),
        max_items_per_keyword=kwargs.get("max_items_per_keyword", 0),
        headless=kwargs.get("headless", True))


def _get_douyin_collector(**kwargs) -> BaseCollector:
    from collectors.douyin_collector import DouyinCollector
    return DouyinCollector(
        keywords=kwargs.get("keywords", []),
        max_pages_per_keyword=kwargs.get("max_pages_per_keyword", 3),
        max_items_per_keyword=kwargs.get("max_items_per_keyword", 0),
        headless=kwargs.get("headless", True))


def _get_xianyu_collector(**kwargs) -> BaseCollector:
    from collectors.xianyu_collector import XianyuCollector
    return XianyuCollector(
        keywords=kwargs.get("keywords", []),
        max_pages_per_keyword=kwargs.get("max_pages_per_keyword", 3))


def _get_qq_group_collector(**kwargs) -> BaseCollector:
    from collectors.qq_group_collector import QQGroupCollector
    return QQGroupCollector(
        group_ids=kwargs.get("group_ids", []),
        collection_duration_minutes=kwargs.get("collection_duration_minutes", 60),
        mode=kwargs.get("mode", "listen"),
        fetch_count=kwargs.get("fetch_count", 200),
        ws_url=kwargs.get("ws_url", "ws://localhost:3001"))


# ── 映射表 ──────────────────────────────────────────────────────────────────

PLATFORM_MAP: dict[str, callable] = {
    "weibo":       _get_weibo_collector,
    "tieba":       _get_tieba_collector,
    "zhihu":       _get_zhihu_collector,
    "xiaohongshu": _get_xiaohongshu_collector,
    "douyin":      _get_douyin_collector,
    "xianyu":      _get_xianyu_collector,
    "qq_group":    _get_qq_group_collector,
}


def get_collector(platform: str, **kwargs) -> BaseCollector:
    """根据平台名获取采集器实例。

    Args:
        platform: 平台标识 (weibo / tieba / zhihu / xiaohongshu / douyin / xianyu / qq_group)
        **kwargs: 传递给采集器构造函数的参数

    Returns:
        BaseCollector 子类实例

    Raises:
        ValueError: 平台不在 PLATFORM_MAP 中
    """
    factory = PLATFORM_MAP.get(platform)
    if factory is None:
        available = ", ".join(PLATFORM_MAP.keys())
        raise ValueError(f"Unknown platform '{platform}'. Available: {available}")
    return factory(**kwargs)


def list_platforms() -> list[str]:
    """返回所有已注册的平台名。"""
    return list(PLATFORM_MAP.keys())
