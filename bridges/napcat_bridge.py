"""
NapCatQQ WebSocket 桥接客户端。

NapCatQQ 是基于 NTQQ 的无头客户端，通过 WebSocket 提供实时消息推送。
本项目通过此桥接模块连接 NapCatQQ，被动监听 QQ 群消息采集灰产情报。

前置条件:
  1. 安装 NapCatQQ: https://github.com/NapNeko/NapCatQQ
  2. 配置 napcat.json 填入 QQ 账号
  3. 启动 NapCatQQ: ./napcat.sh (Linux) 或 napcat.bat (Windows)
  4. 扫码登录后，桥接自动连接

架构:
  [QQ桌面端(NTQQ)] ←IPC→ [NapCatQQ] ←WebSocket→ [napcat_bridge.py] → [QQGroupCollector]

消息格式参考: NapCatQQ OneBot 11 标准事件
  - 群消息: {"post_type": "message", "message_type": "group", ...}
  - 私聊消息: {"post_type": "message", "message_type": "private", ...}
"""

import asyncio
import json
import time
from datetime import datetime
from typing import AsyncIterator
from loguru import logger

from collectors.base import IMMessageItem


class NapCatBridge:
    """NapCatQQ WebSocket 桥接客户端。

    连接 NapCatQQ 的 WebSocket 正向/反向推送，
    过滤群消息并转换为 IMMessageItem。
    """

    def __init__(
        self,
        ws_url: str = "ws://localhost:3001",
        buffer_size: int = 50,
        buffer_timeout: float = 300.0,
        reconnect_delay: float = 5.0,
        max_reconnect_attempts: int = 10,
    ):
        """
        Args:
            ws_url: NapCatQQ WebSocket 地址（默认 ws://localhost:3001）
            buffer_size: 消息缓冲阈值（达到后批量flush）
            buffer_timeout: 缓冲超时秒数（超时后强制flush）
            reconnect_delay: 重连间隔秒数
            max_reconnect_attempts: 最大重连次数
        """
        self.ws_url = ws_url
        self.buffer_size = buffer_size
        self.buffer_timeout = buffer_timeout
        self.reconnect_delay = reconnect_delay
        self.max_reconnect_attempts = max_reconnect_attempts

        self._buffer: list[dict] = []
        self._ws = None
        self._running = False
        self._reconnect_count = 0

    async def connect(self) -> bool:
        """建立 WebSocket 连接到 NapCatQQ。

        Returns:
            True 如果连接成功
        """
        try:
            import websockets
            self._ws = await websockets.connect(
                self.ws_url,
                ping_interval=20,
                ping_timeout=10,
            )
            self._running = True
            self._reconnect_count = 0
            logger.info(f"已连接到 NapCatQQ: {self.ws_url}")
            return True
        except Exception as exc:
            logger.error(f"无法连接到 NapCatQQ ({self.ws_url}): {exc}")
            logger.error("请确认 NapCatQQ 已启动且 WebSocket 端口配置正确")
            return False

    async def listen(self) -> AsyncIterator[IMMessageItem]:
        """监听群消息，批量产出 IMMessageItem。

        缓冲策略：达到 buffer_size 条或 buffer_timeout 秒后flush。

        Yields:
            IMMessageItem: 即时消息条目
        """
        if not self._ws and not await self.connect():
            return

        last_flush = time.time()
        self._running = True

        while self._running:
            try:
                # 接收消息（带超时以支持定期flush）
                raw = await asyncio.wait_for(self._ws.recv(), timeout=1.0)

                try:
                    event = json.loads(raw)
                except json.JSONDecodeError:
                    continue

                # 过滤群消息
                if self._is_group_message(event):
                    msg = self._parse_group_message(event)
                    if msg:
                        self._buffer.append(msg)

                # 检查是否需要flush
                if len(self._buffer) >= self.buffer_size:
                    for item in self._flush_buffer():
                        yield item
                    last_flush = time.time()

                # 检查超时flush
                if self._buffer and (time.time() - last_flush) >= self.buffer_timeout:
                    for item in self._flush_buffer():
                        yield item
                    last_flush = time.time()

            except asyncio.TimeoutError:
                # 超时时flush缓冲
                if self._buffer and (time.time() - last_flush) >= self.buffer_timeout:
                    for item in self._flush_buffer():
                        yield item
                    last_flush = time.time()

            except Exception as exc:
                logger.warning(f"NapCatQQ 连接异常: {exc}")
                if self._buffer:
                    for item in self._flush_buffer():
                        yield item

                if self._reconnect_count < self.max_reconnect_attempts:
                    self._reconnect_count += 1
                    logger.info(
                        f"尝试重连 ({self._reconnect_count}/{self.max_reconnect_attempts})..."
                    )
                    await asyncio.sleep(self.reconnect_delay)
                    if await self.connect():
                        continue
                else:
                    logger.error("达到最大重连次数，停止监听")
                    break

    # ── 消息解析 ──────────────────────────────────────────────────────────

    @staticmethod
    def _is_group_message(event: dict) -> bool:
        """判断是否为群消息事件。"""
        return (
            event.get("post_type") == "message"
            and event.get("message_type") == "group"
        )

    @staticmethod
    def _parse_group_message(event: dict) -> dict | None:
        """解析 NapCatQQ 群消息事件为中间字典格式。"""
        try:
            sender = event.get("sender", {}) or {}

            # 提取消息文本和媒体
            raw_msg = event.get("raw_message", "")
            message = event.get("message", "")
            images = []
            text_parts = []

            if isinstance(message, list):
                for seg in message:
                    if not isinstance(seg, dict):
                        text_parts.append(str(seg))
                        continue
                    stype = seg.get("type", "")
                    sdata = seg.get("data", {}) or {}
                    if stype == "text":
                        text_parts.append(sdata.get("text", ""))
                    elif stype in ("image", "mface", "face"):
                        url = sdata.get("url", "") or sdata.get("file", "")
                        if url:
                            images.append({"type": stype, "url": url})
                        desc = sdata.get("summary", "") or sdata.get("alt", "")
                        text_parts.append(f"[{desc or stype}]")
                    elif stype == "video":
                        text_parts.append("[视频]")
                    elif stype == "file":
                        text_parts.append(f"[文件:{sdata.get('name','')}]")
                    elif stype == "at":
                        text_parts.append(f"@{sdata.get('qq','')}")
                    elif stype == "reply":
                        text_parts.append("[回复]")
                    elif stype == "record":
                        text_parts.append("[语音]")
                if not raw_msg:
                    raw_msg = "".join(text_parts)
            else:
                raw_msg = str(message) if message else ""

            if not raw_msg.strip() and not images:
                return None

            return {
                "group_id": str(event.get("group_id", "")),
                "sender_uid": str(event.get("user_id", "")),
                "sender_nickname": sender.get("nickname", "")
                                    or sender.get("card", ""),
                "content_raw": raw_msg.strip() or "(纯媒体消息)",
                "message_id": str(event.get("message_id", "")),
                "timestamp": event.get("time", int(time.time())),
                "images": images,  # 🆕 图片/动图/表情包
            }
        except Exception as exc:
            logger.debug(f"群消息解析失败: {exc}")
            return None

    def _flush_buffer(self) -> list[IMMessageItem]:
        """将缓冲消息批量转换为 IMMessageItem。"""
        items = []
        for raw in self._buffer:
            timestamp = raw.get("timestamp", 0)
            try:
                if isinstance(timestamp, (int, float)) and timestamp > 0:
                    collected_at = datetime.utcfromtimestamp(timestamp)
                else:
                    collected_at = datetime.utcnow()
            except (ValueError, OSError):
                collected_at = datetime.utcnow()

            items.append(IMMessageItem(
                group_id=raw.get("group_id", ""),
                sender_uid=raw.get("sender_uid", ""),
                sender_nickname=raw.get("sender_nickname", ""),
                content_raw=raw.get("content_raw", ""),
                message_id=raw.get("message_id", ""),
                collected_at=collected_at,
                images=raw.get("images", []),
                metadata={"source": "napcat_ws"},
            ))
        self._buffer.clear()
        return items

    # ── 生命周期 ──────────────────────────────────────────────────────────

    async def close(self):
        """关闭 WebSocket 连接。"""
        self._running = False
        if self._ws:
            try:
                await self._ws.close()
            except Exception:
                pass
            logger.info("NapCatQQ 连接已关闭")

    async def __aenter__(self):
        await self.connect()
        return self

    async def __aexit__(self, *args):
        await self.close()
