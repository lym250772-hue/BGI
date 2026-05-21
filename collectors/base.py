"""Base collector interface."""
from abc import ABC, abstractmethod
from typing import Iterator
from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class IntelItem:
    platform: str
    content_raw: str
    content_type: str = "text"
    source_url: str = ""
    author_uid: str = ""
    author_username: str = ""
    image_hash: str = ""
    group_id: str = ""
    message_id: int = 0
    collected_at: datetime = field(default_factory=datetime.utcnow)
    metadata: dict = field(default_factory=dict)


class BaseCollector(ABC):
    """Interface that every collector must implement."""

    @abstractmethod
    def collect(self) -> Iterator[IntelItem]:
        """Yield IntelItem objects one at a time."""
        ...
