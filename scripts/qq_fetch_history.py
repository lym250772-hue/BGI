#!/usr/bin/env python3
"""拉取QQ群历史消息，保存到 examples/qq_group_sample.json

用法:
  python scripts/qq_fetch_history.py              # 每个群拉200条
  python scripts/qq_fetch_history.py --count 500  # 每个群拉500条
  python scripts/qq_fetch_history.py --merge       # 增量追加+去重
"""
import json, sys, urllib.request, time, argparse, os
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
os.chdir(str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT))

EXAMPLES_FILE = PROJECT_ROOT / "examples" / "qq_group_sample.json"


def fetch_group_messages(group_id: str, group_name: str, count: int = 200) -> list:
    """拉取单个群的历史消息，尝试多个sequence起点。"""
    messages = []
    seen_ids = set()

    # 尝试不同的 message_seq 起点，覆盖更多历史
    for start_seq in [0, 100000, 200000, 500000]:
        if len(messages) >= count:
            break
        try:
            url = (
                f"http://localhost:3000/get_group_msg_history"
                f"?group_id={group_id}&message_seq={start_seq}&count={count}"
            )
            resp = urllib.request.urlopen(url, timeout=15)
            data = json.loads(resp.read())

            if data.get("status") == "ok":
                msgs = data.get("data", {}).get("messages", [])
                for msg in msgs:
                    mid = str(msg.get("message_id", ""))
                    if mid in seen_ids:
                        continue
                    seen_ids.add(mid)

                    sender = msg.get("sender", {}) or {}
                    raw = ""
                    text_parts = []
                    images = []     # 图片/动图/表情包 URL
                    files = []      # 文件
                    videos = []     # 视频

                    if isinstance(msg.get("message"), list):
                        for seg in msg["message"]:
                            if not isinstance(seg, dict):
                                continue
                            stype = seg.get("type", "")
                            sdata = seg.get("data", {}) or {}

                            if stype == "text":
                                t = sdata.get("text", "")
                                text_parts.append(t)
                            elif stype in ("image", "mface", "face"):
                                # 图片 / 动图表情 / QQ表情
                                img_url = sdata.get("url", "") or sdata.get("file", "")
                                img_info = {
                                    "type": stype,
                                    "url": img_url,
                                    "file": sdata.get("file", ""),
                                    "summary": sdata.get("summary", ""),
                                }
                                if img_url:
                                    images.append(img_info)
                                # 表情描述放入文本
                                desc = sdata.get("summary", "") or sdata.get("alt", "")
                                if desc:
                                    text_parts.append(f"[{stype}:{desc}]")
                                elif stype == "face":
                                    text_parts.append(f"[QQ表情:{sdata.get('id','')}]")
                                else:
                                    text_parts.append(f"[{stype}]")
                            elif stype == "video":
                                v_url = sdata.get("url", "") or sdata.get("file", "")
                                videos.append({"url": v_url, "file": sdata.get("file", "")})
                                text_parts.append("[视频]")
                            elif stype == "file":
                                files.append({"name": sdata.get("name", ""), "url": sdata.get("url", ""), "size": sdata.get("file_size", "")})
                                text_parts.append(f"[文件:{sdata.get('name','')}]")
                            elif stype == "at":
                                text_parts.append(f"@{sdata.get('qq','')}")
                            elif stype == "reply":
                                text_parts.append(f"[回复]")
                            elif stype == "record":
                                text_parts.append("[语音]")
                            else:
                                # 其他类型也记录
                                if sdata.get("text"):
                                    text_parts.append(sdata["text"])
                        raw = "".join(text_parts)
                    else:
                        raw = str(msg.get("message", ""))
                        if not raw or raw == "None":
                            raw = ""

                    raw = raw.strip()

                    # 纯媒体消息（无文本但有图/视频）也保存
                    has_media = images or videos or files
                    if not raw and not has_media:
                        continue
                    if not raw and has_media:
                        raw = "(纯媒体消息)"

                    messages.append({
                        "platform": "qq_group",
                        "group_id": group_id,
                        "group_name": group_name,
                        "sender_uid": str(msg.get("user_id", "")),
                        "sender_nickname": sender.get("nickname", ""),
                        "content_raw": raw,
                        "message_id": mid,
                        "time": msg.get("time", 0),
                        "images": images,       # 🆕 图片/动图/表情包
                        "videos": videos,       # 🆕 视频
                        "files": files,         # 🆕 文件
                        "collected_at": datetime.now(timezone.utc).isoformat(),
                    })

            elif "群不存在" in str(data.get("wording", "")):
                break  # 群号不对，跳过
        except Exception:
            continue
        time.sleep(0.3)

    # 按时间排序
    messages.sort(key=lambda m: m["time"])
    return messages


def load_existing():
    """加载已有数据，返回 messages + 已知 message_id 集合。"""
    if EXAMPLES_FILE.exists():
        with open(EXAMPLES_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        existing = data.get("messages", [])
        ids = {m["message_id"] for m in existing}
        return existing, ids
    return [], set()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--count", type=int, default=200, help="每个群拉取条数 (默认200)")
    parser.add_argument("--merge", action="store_true", help="增量追加模式，去重合并")
    args = parser.parse_args()

    # 加载群列表
    groups_file = PROJECT_ROOT / "data" / "raw" / "qq_groups.json"
    with open(groups_file, "r", encoding="utf-8") as f:
        meta = json.load(f)
    groups = meta.get("groups", [])

    # 加载已有数据
    existing_msgs, seen_ids = (load_existing() if args.merge else ([], set()))

    total_new = 0
    for i, g in enumerate(groups):
        gid = g["id"]
        gname = g["name"]
        sys.stderr.write(f"\r[{i+1}/{len(groups)}] {gid} ... ")
        sys.stderr.flush()

        msgs = fetch_group_messages(gid, gname, args.count)
        new = 0
        for m in msgs:
            if m["message_id"] not in seen_ids:
                seen_ids.add(m["message_id"])
                existing_msgs.append(m)
                new += 1
        total_new += new
        time.sleep(0.5)

    sys.stderr.write(f"\r{'':60s}\r")

    # 按时间排序
    existing_msgs.sort(key=lambda m: m["time"])

    # 统计
    from collections import Counter
    by_group = Counter(m["group_name"] for m in existing_msgs)

    def safe_str(s):
        return s.encode('ascii', errors='replace').decode('ascii')

    print(f"Groups: {len(groups)}")
    print(f"Total messages: {len(existing_msgs)} (new: {total_new})")
    print()
    print("Per group (group_id):")
    # Map group_id->name for reference
    id_to_name = {g["id"]: g["name"] for g in groups}
    for gid, cnt in Counter(m["group_id"] for m in existing_msgs).most_common():
        name = safe_str(id_to_name.get(gid, gid))
        print(f"  [{cnt:4d}] {gid} | {name}")

    # 转换为统一 IntelItem 格式（与 贴吧/小红书/微博 等一致）
    from collectors.normalizer import im_to_intel
    from collectors.base import IMMessageItem
    from dataclasses import asdict

    intel_items = []
    for m in existing_msgs:
        im = IMMessageItem(
            platform="qq_group",
            group_id=m.get("group_id", ""),
            group_name=m.get("group_name", ""),
            sender_uid=m.get("sender_uid", ""),
            sender_nickname=m.get("sender_nickname", ""),
            content_raw=m.get("content_raw", ""),
            content_type="text",
            message_id=m.get("message_id", ""),
            collected_at=datetime.fromisoformat(m["collected_at"]) if m.get("collected_at") else datetime.now(timezone.utc),
            images=m.get("images", []),
            metadata={
                "group_name": m.get("group_name", ""),
                "time": m.get("time", 0),
            },
        )
        intel_item = im_to_intel(im)
        intel_items.append(asdict(intel_item))

    # 保存
    EXAMPLES_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(EXAMPLES_FILE, "w", encoding="utf-8") as f:
        json.dump({
            "platform": "qq_group",
            "collected_at": datetime.now(timezone.utc).isoformat(),
            "groups": len(groups),
            "total": len(intel_items),
            "items": intel_items,
        }, f, ensure_ascii=False, indent=2, default=str)

    size_kb = EXAMPLES_FILE.stat().st_size / 1024
    print(f"\nSaved: examples/qq_group_sample.json ({size_kb:.0f} KB)")

    # 打印几条样本
    print("\n=== Sample ===")
    for m in existing_msgs[-5:]:
        ts = datetime.fromtimestamp(m["time"]).strftime("%H:%M") if m["time"] else "??:??"
        sender = safe_str(m['sender_nickname'])
        content = safe_str(m['content_raw'][:80])
        gname = safe_str(m['group_name'][:15])
        print(f"  [{ts}] [{gname}] {sender}: {content}")


if __name__ == "__main__":
    main()
