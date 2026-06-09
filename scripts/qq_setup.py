#!/usr/bin/env python3
"""NapCat QQ group collection helper.

Usage:
    python scripts/qq_setup.py test
    python scripts/qq_setup.py collect --duration 30
    python scripts/qq_setup.py collect --groups "123456,789012"
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

GROUPS_FILE = PROJECT_ROOT / "data" / "raw" / "qq_groups.json"
GREY_KEYWORDS = [
    "刷单", "刷手", "接码", "账号", "号商", "卡商",
    "解封", "涨粉", "数据", "投票", "水军",
    "推广", "引流", "协议", "白号", "企业认证",
    "抖音号", "快手号", "小红书号", "代实名", "代理",
]


def load_group_list() -> list[dict]:
    """Load the locally marked QQ group list."""
    if not GROUPS_FILE.exists():
        return []
    with open(GROUPS_FILE, "r", encoding="utf-8") as f:
        data = json.load(f)
    return data.get("groups", [])


def save_group_list(groups: list[dict]):
    """Save the locally marked QQ group list."""
    GROUPS_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(GROUPS_FILE, "w", encoding="utf-8") as f:
        json.dump({"groups": groups}, f, ensure_ascii=False, indent=2)
    print(f"已保存 {len(groups)} 个群到 {GROUPS_FILE}")


async def test_connection():
    """Test NapCat HTTP API and auto-mark grey-industry-looking groups."""
    import urllib.request

    print("=" * 60)
    print("测试 NapCatQQ 连接")
    print("=" * 60)

    try:
        resp = urllib.request.urlopen("http://localhost:3000/api/get_login_info", timeout=5)
        payload = json.loads(resp.read())
        if payload.get("status") != "ok":
            print(f"[FAIL] API 返回异常: {payload}")
            return
        user = payload.get("data", {})
        print("[OK] NapCatQQ 已连接")
        print(f"QQ号: {user.get('user_id', '?')}")
        print(f"昵称: {user.get('nickname', '?')}")
    except Exception as exc:
        print("[FAIL] 无法连接 NapCatQQ HTTP API: http://localhost:3000")
        print(exc)
        return

    try:
        resp = urllib.request.urlopen("http://localhost:3000/api/get_group_list", timeout=10)
        payload = json.loads(resp.read())
        groups = payload.get("data", []) if payload.get("status") == "ok" else []
    except Exception as exc:
        print(f"[FAIL] 获取群列表失败: {exc}")
        return

    saved = load_group_list()
    saved_ids = {str(g.get("id")) for g in saved}
    print("\n已加入的 QQ 群:")

    for group in groups[:30]:
        gid = str(group.get("group_id", ""))
        gname = group.get("group_name", "未知群名")
        member_count = group.get("member_count", "?")
        marked = "[MARK]" if gid in saved_ids else "      "
        print(f"{marked} {gid} | {gname} ({member_count}人)")

        if gid not in saved_ids and any(keyword in gname for keyword in GREY_KEYWORDS):
            saved.append({
                "id": gid,
                "name": gname,
                "member_count": member_count,
                "source": "auto_detect",
            })
            saved_ids.add(gid)
            print("       [AUTO] 自动识别为灰产相关群，已加入采集列表")

    save_group_list(saved)
    print(f"\n共 {len(groups)} 个群，{len(saved)} 个已标记为采集目标")


async def collect_messages(duration_minutes: int = 60, target_groups: list[str] | None = None):
    """Collect QQ group messages through the NapCat WebSocket bridge."""
    import time as _time

    from bridges.napcat_bridge import NapCatBridge
    from collectors.normalizer import im_to_intel
    from storage.mysql_store import mysql

    print("=" * 60)
    print(f"QQ 群消息采集，持续 {duration_minutes} 分钟")
    print(f"目标群: {', '.join(target_groups) if target_groups else '全部已监听群'}")
    print("=" * 60)

    bridge = NapCatBridge(ws_url="ws://localhost:3001")
    if not await bridge.connect():
        print("[FAIL] 无法连接 NapCatQQ WebSocket: ws://localhost:3001")
        return

    start_time = _time.time()
    timeout = duration_minutes * 60
    count = 0
    db_count = 0

    try:
        async for im_item in bridge.listen():
            if target_groups and im_item.group_id not in target_groups:
                continue

            count += 1
            content_preview = im_item.content_raw[:60].replace("\n", " ")
            flag = "[GREY]" if any(kw in im_item.content_raw for kw in GREY_KEYWORDS) else "      "
            print(f"{flag} [{im_item.group_id}] {im_item.sender_nickname}: {content_preview}")

            try:
                intel_item = im_to_intel(im_item)
                mysql.insert_raw({
                    "source_platform": "qq_group",
                    "source_url": intel_item.source_url,
                    "author_id": intel_item.author_uid,
                    "author_name": intel_item.author_username,
                    "content_type": "text",
                    "content_raw": intel_item.content_raw,
                    "raw_status": "RAW_COLLECTED",
                    "collect_time": intel_item.collected_at,
                    "metadata": json.dumps(intel_item.metadata, ensure_ascii=False, default=str),
                })
                db_count += 1
            except Exception as exc:
                print(f"[WARN] 入库失败: {exc}")

            if _time.time() - start_time >= timeout:
                print(f"\n[OK] 采集完成: {count} 条消息，{db_count} 条已入库")
                break
    except KeyboardInterrupt:
        print(f"\n用户中断: {count} 条消息，{db_count} 条已入库")
    finally:
        await bridge.close()


async def main():
    parser = argparse.ArgumentParser(description="QQ 群采集设置工具")
    parser.add_argument("action", choices=["test", "collect"], help="test=测试连接，collect=开始采集")
    parser.add_argument("--duration", type=int, default=60, help="采集时长，单位分钟")
    parser.add_argument("--groups", default="", help="指定群号，多个群号用逗号分隔")
    args = parser.parse_args()

    if args.action == "test":
        await test_connection()
    else:
        target = [g.strip() for g in args.groups.split(",") if g.strip()] if args.groups else None
        await collect_messages(args.duration, target)


if __name__ == "__main__":
    asyncio.run(main())
