#!/usr/bin/env python3
"""
QQ群采集 — 一键启动脚本。

用法:
  python scripts/qq_setup.py test        # 测试NapCatQQ连接 + 列出已加入的群
  python scripts/qq_setup.py collect     # 开始监听所有群消息(60分钟)
  python scripts/qq_setup.py collect --duration 30 --groups "123456,789012"

前置条件:
  1. NapCatQQ 已下载、配置、启动、扫码登录
  2. 已在QQ客户端手动加入灰产相关群
"""

import sys, os, json, asyncio, argparse
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))


def load_group_list():
    """加载已记录的QQ群列表。"""
    groups_file = PROJECT_ROOT / "data" / "raw" / "qq_groups.json"
    if groups_file.exists():
        with open(groups_file, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data.get("groups", [])
    return []


def save_group_list(groups: list):
    """保存QQ群列表。"""
    groups_file = PROJECT_ROOT / "data" / "raw" / "qq_groups.json"
    with open(groups_file, "r", encoding="utf-8") as f:
        data = json.load(f)
    data["groups"] = groups
    with open(groups_file, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    print(f"已保存 {len(groups)} 个群到 {groups_file.name}")


async def test_connection():
    """测试 NapCatQQ 连接并列出已加入的群。"""
    print("=" * 60)
    print("  测试 NapCatQQ 连接")
    print("=" * 60)

    # 测试 HTTP API
    try:
        import urllib.request
        resp = urllib.request.urlopen("http://localhost:3000/api/get_login_info", timeout=5)
        data = json.loads(resp.read())
        if data.get("status") == "ok":
            user = data.get("data", {})
            print(f"\n  [OK] NapCatQQ 已连接！")
            print(f"  QQ号: {user.get('user_id', '?')}")
            print(f"  昵称: {user.get('nickname', '?')}")
        else:
            print(f"\n  ⚠️  API返回异常: {data}")
            return
    except Exception as e:
        print(f"\n  [FAIL] 无法连接 NapCatQQ (http://localhost:3000)")
        print(f"  {e}")
        print(f"\n  请确认:")
        print(f"  1. NapCatQQ 已启动 (双击 napcat.bat)")
        print(f"  2. QQ 已扫码登录")
        print(f"  3. HTTP API 端口为 3000")
        return

    # 获取群列表
    print(f"\n  --- 已加入的QQ群 ---")
    try:
        resp = urllib.request.urlopen("http://localhost:3000/api/get_group_list", timeout=10)
        data = json.loads(resp.read())
        if data.get("status") == "ok":
            groups = data.get("data", [])
            if groups:
                saved = load_group_list()
                saved_ids = {g["id"] for g in saved}

                for g in groups[:30]:  # 最多显示30个
                    gid = str(g.get("group_id", ""))
                    gname = g.get("group_name", "未知群名")
                    member_count = g.get("member_count", "?")
                    marked = ""[MARK]"" if gid in saved_ids else "  "
                    print(f"  {marked} {gid} | {gname} ({member_count}人)")

                    # 自动添加灰产关键词匹配的群
                    if gid not in saved_ids:
                        grey_kw = [
                            "刷单", "刷手", "接码", "账号", "号商", "卡商",
                            "解封", "涨粉", "数据", "投票", "水军",
                            "推广", "引流", "协议", "白号", "企业认证",
                            "抖音号", "快手号", "小红书号",
                        ]
                        if any(kw in gname for kw in grey_kw):
                            saved.append({
                                "id": gid,
                                "name": gname,
                                "member_count": member_count,
                                "source": "auto_detect",
                            })
                            print(f"       "[AUTO]" 自动识别为灰产相关群，已加入采集列表")

                save_group_list(saved)

                if not groups:
                    print("  没有加入任何群。请在QQ客户端手动搜索并加入群。")
                print(f"\n  📊 共 {len(groups)} 个群，{len(saved)} 个已标记为灰产相关")
            else:
                print("  未获取到群列表（可能API格式不同）")
    except Exception as e:
        print(f"  获取群列表失败: {e}")
        print(f"  请手动在QQ客户端记下群号，填入 data/raw/qq_groups.json")

    print()
    print("=" * 60)


async def collect_messages(duration_minutes: int = 60, target_groups: list = None):
    """采集QQ群消息。"""
    print("=" * 60)
    print(f"  QQ群消息采集 — {duration_minutes} 分钟")
    if target_groups:
        print(f"  目标群: {', '.join(target_groups)}")
    else:
        print(f"  目标群: 全部已标记群")
    print("=" * 60)
    print()

    from bridges.napcat_bridge import NapCatBridge
    from collectors.normalizer import im_to_intel
    from storage.mysql_store import mysql
    import time as _time

    bridge = NapCatBridge(ws_url="ws://localhost:3001")
    connected = await bridge.connect()

    if not connected:
        print("\n[FAIL] 无法连接 NapCatQQ WebSocket (ws://localhost:3001)")
        print("请确认 NapCatQQ 已启动且 WebSocket 配置正确")
        return

    print("[OK] WebSocket 连接成功，开始监听群消息...")
    print("(按 Ctrl+C 停止)")
    print()

    start_time = _time.time()
    timeout = duration_minutes * 60
    count = 0
    db_count = 0

    try:
        async for im_item in bridge.listen():
            # 过滤指定群
            if target_groups and im_item.group_id not in target_groups:
                continue

            count += 1
            content_preview = im_item.content_raw[:60].replace('\n', ' ')

            # 灰产关键词高亮
            grey_kw = [
                "刷单", "接码", "出号", "卡商", "号商", "代实名",
                "解封", "涨粉", "代理", "协议号", "白号",
            ]
            flag = "[GREY]" if any(kw in im_item.content_raw for kw in grey_kw) else "  "

            print(f"{flag} [{im_item.group_id}] {im_item.sender_nickname}: {content_preview}")

            # 转换为 IntelItem 并存储
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
                    "metadata": json.dumps(
                        intel_item.metadata, ensure_ascii=False, default=str,
                    ),
                })
                db_count += 1
            except Exception:
                pass  # MySQL不可用时静默跳过

            # 检查超时
            if _time.time() - start_time >= timeout:
                print(f"\n[OK] 采集完成: {count} 条消息 ({db_count} 条已入库)")
                break

    except KeyboardInterrupt:
        print(f"\n⏹ 用户中断: {count} 条消息 ({db_count} 条已入库)")
    except Exception as exc:
        print(f"\n[FAIL] 采集异常: {exc}")
    finally:
        await bridge.close()


async def main():
    parser = argparse.ArgumentParser(description="QQ群采集设置工具")
    parser.add_argument("action", choices=["test", "collect"],
                        help="test=测试连接 / collect=开始采集")
    parser.add_argument("--duration", type=int, default=60,
                        help="采集时长(分钟), 默认60")
    parser.add_argument("--groups", default="",
                        help="指定群号(逗号分隔), 默认采集所有已标记群")
    args = parser.parse_args()

    if args.action == "test":
        await test_connection()
    elif args.action == "collect":
        target = [g.strip() for g in args.groups.split(",") if g.strip()] if args.groups else None
        await collect_messages(args.duration, target)


if __name__ == "__main__":
    asyncio.run(main())
