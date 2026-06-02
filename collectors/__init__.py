"""数据采集层 — 多源情报采集器。

所有采集器产出统一格式 IntelItem，通过 registry.py 注册。
"""

from collectors.base import BaseCollector, IntelItem
from collectors.registry import get_collector, list_platforms

__all__ = ["BaseCollector", "IntelItem", "get_collector", "list_platforms"]
