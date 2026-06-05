"""
QQ群聊采集器 — 通过 NapCatQQ 桥接被动监听群消息。

设计思路:
  - QQ群没有公开搜索API，采集方式是被动监听已加入的群
  - 群发现：用户手动通过QQ客户端搜索和加入灰产相关群
  - 消息采集：通过NapCatQQ WebSocket实时推送
  - 批处理：每50条消息或每5分钟flush一次，合并为IntelItem

灰产关键词参考（用户加入群时使用）:
  刷单、接码、代实名、账号交易、解封、涨粉、数据维护、
  投票、协议号、白号、企业认证、抖音推广、小红书推广
"""

import asyncio
from loguru import logger
from collectors.base import BaseCollector, IntelItem
from collectors.normalizer import im_to_intel


class QQGroupCollector(BaseCollector):
    """QQ群消息被动采集器。

    通过 NapCatQQ bridge 监听已加入的QQ群，
    实时采集群聊消息并转换为 IntelItem。

    Usage:
        collector = QQGroupCollector(group_ids=["123456789"], duration=60)
        for item in collector.collect():
            save_to_db(item)
    """

    def __init__(
        self,
        group_ids: list[str] = None,
        collection_duration_minutes: int = 60,
        ws_url: str = "ws://localhost:3001",
    ):
        """
        Args:
            group_ids: 目标群号列表（空=监听所有已加入的群）
            collection_duration_minutes: 采集时长（分钟）
            ws_url: NapCatQQ WebSocket 地址
        """
        self.group_ids = group_ids or []
        self.duration = collection_duration_minutes
        self.ws_url = ws_url

    def collect(self):
        """同步采集入口（封装异步桥接）。"""
        return asyncio.run(self._collect_async())

    async def _collect_async(self):
        """异步采集主循环。"""
        from bridges.napcat_bridge import NapCatBridge

        bridge = NapCatBridge(ws_url=self.ws_url)
        connected = await bridge.connect()
        if not connected:
            logger.error(
                "无法连接到 NapCatQQ。请确认：\n"
                "  1. NapCatQQ 已安装并启动\n"
                "  2. WebSocket 端口正确（默认 ws://localhost:3001）\n"
                "  3. QQ 账号已扫码登录"
            )
            return

        try:
            import time
            start_time = time.time()
            timeout = self.duration * 60  # 转换为秒
            count = 0

            logger.info(
                f"QQ群聊采集开始（时长={self.duration}分钟，"
                f"目标群={self.group_ids if self.group_ids else '全部'}）"
            )

            async for im_item in bridge.listen():
                # 过滤指定群
                if self.group_ids and im_item.group_id not in self.group_ids:
                    continue

                # 转换为 IntelItem 并产出
                intel_item = im_to_intel(im_item)
                yield intel_item

                count += 1
                if count % 10 == 0:
                    logger.info(f"QQ群采集: {count} 条消息")

                # 检查超时
                if time.time() - start_time >= timeout:
                    logger.info(f"QQ群采集完成: {count} 条消息（达到时长限制）")
                    break

        finally:
            await bridge.close()

        logger.info(f"QQ群采集结束: 共采集 {count} 条消息")
