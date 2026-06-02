"""Telegram 公开群组采集器 — 使用 Telethon 客户端。

使用前需配置 .env:
  TELEGRAM_API_ID=your_api_id
  TELEGRAM_API_HASH=your_api_hash

获取方式: https://my.telegram.org → API Development Tools
"""

from typing import Iterator, Optional
from datetime import datetime

from loguru import logger

from collectors.base import BaseCollector, IntelItem


class TelegramCollector(BaseCollector):
    """Telegram 公开群组消息采集器。

    使用方式:
        collector = TelegramCollector(
            group_usernames=["group1", "group2"],
        )
        for item in collector.collect():
            print(item.content_raw)
    """

    def __init__(
        self,
        group_usernames: list[str],
        limit_per_group: int = 100,
        api_id: Optional[int] = None,
        api_hash: Optional[str] = None,
    ):
        """
        Args:
            group_usernames: TG 群组用户名列表（如 ["live_tech", "card_shop"]）
            limit_per_group: 每个群组最多拉取消息数
            api_id: Telegram API ID（留空则从环境变量 TELEGRAM_API_ID 读取）
            api_hash: Telegram API Hash（留空则从环境变量 TELEGRAM_API_HASH 读取）
        """
        import os
        self.group_usernames = group_usernames
        self.limit = limit_per_group
        self.api_id = api_id or int(os.getenv("TELEGRAM_API_ID", "0"))
        self.api_hash = api_hash or os.getenv("TELEGRAM_API_HASH", "")

    def collect(self) -> Iterator[IntelItem]:
        """使用 Telethon 采集各群组消息。"""
        if not self.api_id or not self.api_hash:
            logger.warning("Telegram API ID/Hash not configured, skipping")
            return

        try:
            from telethon import TelegramClient
        except ImportError:
            logger.error("telethon not installed, run: pip install telethon")
            return

        client = TelegramClient("bagi_session", self.api_id, self.api_hash)

        try:
            client.start()
            logger.info("Telegram client connected")

            for group in self.group_usernames:
                logger.info(f"Fetching messages from: {group}")
                try:
                    messages = client.iter_messages(
                        group, limit=self.limit,
                    )
                    count = 0
                    for msg in messages:
                        if msg.message:
                            item = self._to_intel_item(msg, group)
                            yield item
                            count += 1
                    logger.info(f"  [{group}] collected {count} messages")
                except Exception as exc:
                    logger.error(f"Failed to fetch from {group}: {exc}")

        finally:
            client.disconnect()
            logger.info("Telegram client disconnected")

    # ── 内部转换 ────────────────────────────────────────────────────────

    @staticmethod
    def _to_intel_item(msg, group_username: str) -> IntelItem:
        """将 Telethon Message 转换为 IntelItem。"""
        content_type = "text"
        has_image = bool(msg.photo or msg.video)
        has_video = bool(msg.video)

        if msg.video:
            content_type = "video"
        elif msg.photo:
            content_type = "image"

        return IntelItem(
            platform="telegram",
            content_raw=msg.message or "",
            content_type=content_type,
            source_url=f"https://t.me/{group_username}/{msg.id}",
            author_uid=str(msg.sender_id or ""),
            author_username=getattr(msg.sender, "username", "") if msg.sender else "",
            group_id=group_username,
            message_id=msg.id,
            collected_at=datetime.utcnow(),
            metadata={
                "keyword": group_username,
                "has_image": has_image,
                "has_video": has_video,
                "is_long_text": len(msg.message or "") > 500,
                "message_id": msg.id,
                "group_id": group_username,
            },
        )
