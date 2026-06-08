"""
QQ群聊采集器 — 通过 NapCatQQ 桥接实现被动监听 + 主动历史拉取双模式。

设计思路:
  - QQ群没有公开搜索API，采集方式:
    1. 被动监听：通过NapCatQQ WebSocket实时推送（已实现）
    2. 主动拉取：通过NapCatQQ HTTP API获取群聊历史消息（🆕 已集成）
  - 群发现：用户手动通过QQ客户端搜索和加入灰产相关群
  - 双模式可独立或组合使用

灰产关键词参考（用户加入群时使用）:
  刷单、接码、代实名、账号交易、解封、涨粉、数据维护、
  投票、协议号、白号、企业认证、抖音推广、小红书推广
"""

import asyncio
import json
import time
import urllib.request
from datetime import datetime, timezone
from loguru import logger
from collectors.base import BaseCollector, IntelItem, IMMessageItem
from collectors.normalizer import im_to_intel


class QQGroupCollector(BaseCollector):
    """QQ群消息采集器 — 被动监听 + 主动历史拉取。

    通过 NapCatQQ bridge 实现双模式采集:
      - 被动模式 (listen): WebSocket 实时监听群消息
      - 主动模式 (fetch): HTTP API 拉取群聊历史记录
      - 混合模式 (both): 先拉历史，再持续监听

    Usage:
        # 纯监听（原功能）
        collector = QQGroupCollector(group_ids=["123456789"], duration=60)
        for item in collector.collect():
            save_to_db(item)

        # 仅拉取历史
        collector = QQGroupCollector(group_ids=["123456789"], mode="fetch", fetch_count=500)
        for item in collector.collect():
            save_to_db(item)

        # 先拉历史再监听（推荐 — 完整覆盖）
        collector = QQGroupCollector(group_ids=["123456789"], mode="both",
                                     fetch_count=300, duration=30)
        for item in collector.collect():
            save_to_db(item)
    """

    def __init__(
        self,
        group_ids: list[str] = None,
        collection_duration_minutes: int = 60,
        ws_url: str = "ws://localhost:3001",
        http_api_base: str = "http://localhost:3000",
        mode: str = "listen",       # "listen" | "fetch" | "both"
        fetch_count: int = 200,     # 每个群拉取的历史消息数
    ):
        """
        Args:
            group_ids: 目标群号列表（空=监听所有已加入的群）
            collection_duration_minutes: 被动监听时长（分钟）
            ws_url: NapCatQQ WebSocket 地址
            http_api_base: NapCatQQ HTTP API 地址
            mode: 采集模式 — listen(仅监听) / fetch(仅拉历史) / both(先拉后监)
            fetch_count: 主动拉取时每个群获取的历史消息数
        """
        self.group_ids = group_ids or []
        self.duration = collection_duration_minutes
        self.ws_url = ws_url
        self.http_api_base = http_api_base
        self.mode = mode
        self.fetch_count = fetch_count

    def collect(self):
        """同步采集入口（封装异步桥接）。"""
        if self.mode == "fetch":
            return self._collect_history()
        elif self.mode == "both":
            # 先拉历史，再监听
            yield from self._collect_history()
            yield from asyncio.run(self._collect_async())
        else:
            return asyncio.run(self._collect_async())

    # ── 主动历史拉取 ──────────────────────────────────────────────────────

    def _collect_history(self):
        """通过 NapCatQQ HTTP API 主动拉取群聊历史消息。

        使用 get_group_msg_history API，支持多起点轮询以覆盖更长历史。
        """
        logger.info(
            f"QQ群历史拉取开始: {len(self.group_ids) if self.group_ids else '全部'} 群, "
            f"每群最多 {self.fetch_count} 条"
        )

        # 加载群列表（如果未指定 group_ids）
        groups = self._resolve_groups()
        seen_ids = set()
        total = 0

        for gi, group in enumerate(groups):
            gid = group["id"]
            gname = group.get("name", gid)

            logger.info(f"[{gi+1}/{len(groups)}] 拉取群 {gid} ({gname}) 历史消息...")

            msgs = self._fetch_single_group_history(gid, gname, self.fetch_count)
            new_count = 0

            for msg in msgs:
                mid = msg.get("message_id", "")
                if mid in seen_ids:
                    continue
                seen_ids.add(mid)

                # 构建 IMMessageItem
                im_item = IMMessageItem(
                    platform="qq_group",
                    group_id=gid,
                    group_name=gname,
                    sender_uid=msg.get("sender_uid", ""),
                    sender_nickname=msg.get("sender_nickname", ""),
                    content_raw=msg.get("content_raw", ""),
                    content_type=msg.get("content_type", "text"),
                    message_id=mid,
                    collected_at=msg.get("collected_at", datetime.now(timezone.utc)),
                    images=msg.get("images", []),
                    metadata={
                        "source": "napcat_api_history",
                        "group_name": gname,
                        "time": msg.get("time", 0),
                        "videos": msg.get("videos", []),
                        "files": msg.get("files", []),
                    },
                )

                # 转换为 IntelItem 并产出
                intel_item = im_to_intel(im_item)
                yield intel_item
                new_count += 1

            total += new_count
            logger.info(f"  {gid}: {new_count} 条新消息 (去重后)")
            time.sleep(0.5)  # API限速

        logger.info(f"QQ群历史拉取完成: {total} 条消息 (共 {len(groups)} 群)")

    def _fetch_single_group_history(
        self, group_id: str, group_name: str, count: int
    ) -> list[dict]:
        """拉取单个群的历史消息，尝试多个 sequence 起点以覆盖更多历史。

        NapCatQQ API: GET /get_group_msg_history?group_id={id}&message_seq={seq}&count={n}
        """
        messages = []

        # 多起点轮询，从不同 sequence 位置往回拉
        for start_seq in [0, 100000, 200000, 500000]:
            if len(messages) >= count:
                break
            try:
                url = (
                    f"{self.http_api_base}/get_group_msg_history"
                    f"?group_id={group_id}&message_seq={start_seq}&count={count}"
                )
                req = urllib.request.Request(url)
                resp = urllib.request.urlopen(req, timeout=15)
                data = json.loads(resp.read())

                if data.get("status") == "ok":
                    raw_msgs = data.get("data", {}).get("messages", [])
                    for msg in raw_msgs:
                        parsed = self._parse_history_message(msg, group_id, group_name)
                        if parsed:
                            messages.append(parsed)

                elif "群不存在" in str(data.get("wording", "")):
                    logger.warning(f"群 {group_id} 不存在，跳过")
                    break

            except Exception as exc:
                logger.debug(f"群 {group_id} seq={start_seq} 拉取失败: {exc}")
                continue

            time.sleep(0.3)  # 请求间隔

        # 按时间排序
        messages.sort(key=lambda m: m.get("time", 0))
        return messages

    @staticmethod
    def _parse_history_message(
        msg: dict, group_id: str, group_name: str
    ) -> dict | None:
        """解析 NapCatQQ 历史消息为中间字典格式。

        复用与 napcat_bridge.py 相同的消息解析逻辑，
        确保历史消息与实时消息格式一致。
        """
        try:
            sender = msg.get("sender", {}) or {}
            text_parts = []
            images = []
            videos = []
            files = []

            raw_message = msg.get("message", "")

            if isinstance(raw_message, list):
                for seg in raw_message:
                    if not isinstance(seg, dict):
                        text_parts.append(str(seg))
                        continue
                    stype = seg.get("type", "")
                    sdata = seg.get("data", {}) or {}

                    if stype == "text":
                        text_parts.append(sdata.get("text", ""))
                    elif stype in ("image", "mface", "face"):
                        img_url = sdata.get("url", "") or sdata.get("file", "")
                        img_info = {
                            "type": stype,
                            "url": img_url,
                            "file": sdata.get("file", ""),
                            "summary": sdata.get("summary", ""),
                        }
                        if img_url:
                            images.append(img_info)
                        desc = sdata.get("summary", "") or sdata.get("alt", "")
                        if desc:
                            text_parts.append(f"[{stype}:{desc}]")
                        elif stype == "face":
                            text_parts.append(f"[QQ表情:{sdata.get('id', '')}]")
                        else:
                            text_parts.append(f"[{stype}]")
                    elif stype == "video":
                        v_url = sdata.get("url", "") or sdata.get("file", "")
                        videos.append({"url": v_url, "file": sdata.get("file", "")})
                        text_parts.append("[视频]")
                    elif stype == "file":
                        files.append({
                            "name": sdata.get("name", ""),
                            "url": sdata.get("url", ""),
                            "size": sdata.get("file_size", ""),
                        })
                        text_parts.append(f"[文件:{sdata.get('name', '')}]")
                    elif stype == "at":
                        text_parts.append(f"@{sdata.get('qq', '')}")
                    elif stype == "reply":
                        text_parts.append("[回复]")
                    elif stype == "record":
                        text_parts.append("[语音]")
                    else:
                        if sdata.get("text"):
                            text_parts.append(sdata["text"])
                raw = "".join(text_parts)
            else:
                raw = str(raw_message) if raw_message else ""
                if raw in ("None", ""):
                    raw = ""

            raw = raw.strip()
            has_media = images or videos or files
            if not raw and not has_media:
                return None
            if not raw and has_media:
                raw = "(纯媒体消息)"

            msg_time = msg.get("time", 0)
            if isinstance(msg_time, (int, float)) and msg_time > 0:
                try:
                    collected_at = datetime.fromtimestamp(msg_time, tz=timezone.utc)
                except (ValueError, OSError):
                    collected_at = datetime.now(timezone.utc)
            else:
                collected_at = datetime.now(timezone.utc)

            return {
                "group_id": group_id,
                "group_name": group_name,
                "sender_uid": str(msg.get("user_id", "")),
                "sender_nickname": sender.get("nickname", ""),
                "content_raw": raw,
                "content_type": "text",
                "message_id": str(msg.get("message_id", "")),
                "time": msg_time,
                "images": images,
                "videos": videos,
                "files": files,
                "collected_at": collected_at,
            }
        except Exception as exc:
            logger.debug(f"历史消息解析失败: {exc}")
            return None

    def _resolve_groups(self) -> list[dict]:
        """解析目标群列表。

        如果初始化时指定了 group_ids，用 group_ids 构建；
        否则从 data/raw/qq_groups.json 加载。
        """
        if self.group_ids:
            # 尝试从 qq_groups.json 补充群名称
            name_map = {}
            try:
                from pathlib import Path
                groups_file = Path(__file__).resolve().parent.parent / "data" / "raw" / "qq_groups.json"
                if groups_file.exists():
                    with open(groups_file, "r", encoding="utf-8") as f:
                        saved = json.load(f)
                    for g in saved.get("groups", []):
                        name_map[g["id"]] = g.get("name", g["id"])
            except Exception:
                pass

            return [
                {"id": gid, "name": name_map.get(gid, gid)}
                for gid in self.group_ids
            ]

        # 从文件加载
        try:
            from pathlib import Path
            groups_file = Path(__file__).resolve().parent.parent / "data" / "raw" / "qq_groups.json"
            if groups_file.exists():
                with open(groups_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                return data.get("groups", [])
        except Exception:
            pass

        logger.warning("未找到目标群列表（group_ids 为空且 qq_groups.json 不存在）")
        return []

    # ── 被动监听 ──────────────────────────────────────────────────────────

    async def _collect_async(self):
        """异步被动监听主循环（原功能保持不变）。"""
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
            start_time = time.time()
            timeout = self.duration * 60
            count = 0

            logger.info(
                f"QQ群被动监听开始（时长={self.duration}分钟，"
                f"目标群={self.group_ids if self.group_ids else '全部'}）"
            )

            async for im_item in bridge.listen():
                # 过滤指定群
                if self.group_ids and im_item.group_id not in self.group_ids:
                    continue

                im_item.metadata["source"] = "napcat_ws_listen"
                intel_item = im_to_intel(im_item)
                yield intel_item

                count += 1
                if count % 10 == 0:
                    logger.info(f"QQ群监听: {count} 条消息")

                if time.time() - start_time >= timeout:
                    logger.info(f"QQ群监听完成: {count} 条消息（达到时长限制）")
                    break

        finally:
            await bridge.close()

        logger.info(f"QQ群监听结束: 共 {count} 条消息")
