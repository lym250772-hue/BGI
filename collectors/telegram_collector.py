"""Telegram public group collector using Telethon."""
import hashlib
from typing import Iterator
from datetime import datetime

from loguru import logger
from telethon import TelegramClient, events

from config.settings import settings
from collectors.base import BaseCollector, IntelItem


class TelegramCollector(BaseCollector):
    """Collect messages from public Telegram groups/channels.

    Requires TELEGRAM_API_ID and TELEGRAM_API_HASH env vars.
    Stores session in data/telegram_session.session.
    """

    def __init__(self, group_usernames: list[str]):
        self.group_usernames = group_usernames
        self.client = TelegramClient(
            str(settings.raw_data_dir / "telegram_session"),
            api_id=self._env("TELEGRAM_API_ID"),
            api_hash=self._env("TELEGRAM_API_HASH"),
        )

    @staticmethod
    def _env(key: str) -> str:
        import os
        v = os.getenv(key, "")
        if not v:
            raise RuntimeError(f"Missing env var: {key}")
        return v

    async def _start(self):
        await self.client.start()

    async def _fetch_messages(self):
        for username in self.group_usernames:
            try:
                entity = await self.client.get_entity(username)
                async for msg in self.client.iter_messages(entity, limit=200):
                    yield msg, username
            except Exception as exc:
                logger.error(f"Failed to fetch from {username}: {exc}")

    def collect(self) -> Iterator[IntelItem]:
        import asyncio

        async def _run():
            await self._start()
            async for msg, username in self._fetch_messages():
                text = msg.text or msg.caption or ""
                if not text.strip():
                    continue
                content_type = "text"
                image_hash = ""
                if msg.photo or msg.video or msg.document:
                    content_type = "image" if msg.photo else "video"
                    # compute hash from media if available
                    raw = (msg.text or msg.caption or "").encode() + str(msg.date).encode()
                    image_hash = hashlib.md5(raw).hexdigest()
                yield IntelItem(
                    platform="telegram",
                    content_raw=text,
                    content_type=content_type,
                    source_url=f"https://t.me/{username}/{msg.id}",
                    author_uid=str(msg.sender_id) if msg.sender_id else "",
                    author_username=getattr(msg.sender, "username", "") or "",
                    image_hash=image_hash,
                    group_id=username,
                    message_id=msg.id,
                    collected_at=msg.date.replace(tzinfo=None) if msg.date else datetime.utcnow(),
                    metadata={
                        "views": getattr(msg, "views", 0),
                        "forwards": getattr(msg, "forwards", 0),
                        "reply_to_msg_id": getattr(msg, "reply_to", None) and msg.reply_to.reply_to_msg_id,
                    },
                )
            await self.client.disconnect()

        return iter(asyncio.get_event_loop().run_until_complete(_run()))
