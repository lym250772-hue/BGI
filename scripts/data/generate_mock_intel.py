#!/usr/bin/env python3
"""Generate mock collected intel JSON data matching the collector output format.

Output: data/mock_collected_intel.json — ready to feed into AnalysisEngine.

Usage:
    python scripts/data/generate_mock_intel.py
    python scripts/data/generate_mock_intel.py -n 200
    python scripts/data/generate_mock_intel.py --seed 42
    python scripts/data/generate_mock_intel.py --output my_data.json
"""

import argparse
import json
import random
import sys
from datetime import datetime, timedelta
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))

# ── Platform-specific URL + ID generators ────────────────────────────────────

_PLATFORM_CONFIG = {
    "weibo": {
        "url_template": "https://weibo.com/{uid}/{weibo_id}",
        "uid_range": (1000000000, 9999999999),
        "weibo_id_format": lambda: ''.join(random.choices('ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789', k=8)),
        "username_pool": ["乔yo-", "今夜不设防", "一只小废柴", "锦鲤大王V", "吃瓜少女小圆", "科技数码君",
                          "兼职指南", "薅羊毛小能手", "快钱有道", "日赚500不是梦", "诚信出号", "数据圈内人"],
    },
    : {
        "url_template": "https://t.me/{group_id}/{message_id}",
        "uid_range": (100000000, 999999999),
        "weibo_id_format": None,
        "username_pool": ["黑产资源", "接码平台", "数据买卖", "薅羊毛线报", "卡商联盟",
                          "出号渠道", "外挂脚本", "棋牌引流", "色流精准"],
    },
    "tieba": {
        "url_template": "https://tieba.baidu.com/p/{message_id}",
        "uid_range": (10000000, 99999999),
        "weibo_id_format": lambda: str(random.randint(1000000000, 9999999999)),
        "username_pool": ["贴吧用户_" + ''.join(random.choices('0123456789abcdef', k=8)) for _ in range(8)],
    },
    "forum": {
        "url_template": "https://www.{domain}.com/thread-{message_id}-1-1.html",
        "uid_range": (10000, 99999),
        "weibo_id_format": lambda: str(random.randint(100000, 999999)),
        "username_pool": ["admin", "hacker007", "databroker", "carder_x", "tool_master",
                          "黑产老炮", "引流专家", "技术流"],
    },
}

# ── Realistic content templates (from OCR'd threat intel reports + real samples) ──

_TEMPLATES = [
    # === 诈骗 ===
    {
        "content_raw": "最新刷单返利项目，日赚500+，无需押金。加微信 shuadan666 了解详情，名额有限！链接：https://shuadan-hui.com/join?ref=abc123",
        "platform": "group_id": "刷单返利",
        "has_image": False,
    },
    {
        "content_raw": "信用贷款秒批，黑户可做，手续费仅5%。联系电话 13812345678，QQ群 85234671",
        "platform": "tieba",
        "group_id": "贷款交流",
        "has_image": False,
    },
    {
        "content_raw": "内部股票消息，跟单稳赚。免费推荐牛股，加群 99651234 领取每日金股。直播间 https://niugu-live.com/room/888",
        "platform": "group_id": "股票交流",
        "has_image": False,
    },
    {
        "content_raw": "恭喜您中奖！请点击链接 https://zhongjiang-fake.com/claim?code=XYZ 填写领取信息，过期作废。",
        "platform": "weibo",
        "group_id": "中奖通知",
        "has_image": False,
    },
    # === 引流 ===
    {
        "content_raw": "抖音无人直播技术，全套教程+工具，包教包会。详情看主页，联系微信 douyin_pro888。工具下载 https://linktr.ee/douyin_pro",
        "platform": "group_id": "直播技术",
        "has_image": False,
    },
    {
        "content_raw": "色流精准粉丝，日引500+，转化率高。QQ群：44567890，进群看效果数据",
        "platform": "forum",
        "group_id": "流量变现",
        "has_image": True,
    },
    {
        "content_raw": "小红书笔记代发，千粉账号矩阵，曝光10w+。合作加V：xhs_seo_vip",
        "platform": "xiaohongshu",
        "group_id": "品牌合作",
        "has_image": False,
    },
    {
        "content_raw": "菠菜平台推广，真人视讯百家乐，高返水。代理咨询TG：bocai_agent888",
        "platform": "group_id": "博彩推广",
        "has_image": True,
    },
    # === 作弊 ===
    {
        "content_raw": "抖音直播间挂铁，真人互动，在线人数瞬间破千。软件下载：https://douyin-bot.pro/download，客服QQ：55321987",
        "platform": "group_id": "直播辅助",
        "has_image": False,
    },
    {
        "content_raw": "薅羊毛自动化脚本，支持淘宝/京东/拼多多全平台。支持定制规则，联系 wx_pro_155",
        "platform": "group_id": "羊毛线报",
        "has_image": False,
    },
    {
        "content_raw": "王者荣耀/吃鸡/原神 全游戏外挂，透视自瞄稳定不封号。购买地址 https://gamecheat.club/buy/hack2024",
        "platform": "forum",
        "group_id": "游戏辅助",
        "has_image": True,
    },
    {
        "content_raw": "短视频刷播放量/点赞/评论，1元=1000播放，支持抖音快手。联系QQ 88234567",
        "platform": "tieba",
        "group_id": "短视频运营",
        "has_image": False,
    },
    # === 账号黑产 ===
    {
        "content_raw": "出售微信号/QQ号/抖音号，实名已过，可换绑手机。大量现货，价格美丽。联系 wx_pro_101",
        "platform": "group_id": "账号交易",
        "has_image": False,
    },
    {
        "content_raw": "接码平台，支持国内+海外，一码一用，价格低至0.1元。注册地址：https://jiema.pro/register?invite=abc",
        "platform": "group_id": "接码平台",
        "has_image": False,
    },
    {
        "content_raw": "支付宝/微信实名认证服务，无需本人。三要素/四要素均有。QQ群 77894561 下单",
        "platform": "forum",
        "group_id": "实名认证",
        "has_image": False,
    },
    {
        "content_raw": "批量注册抖音/快手账号，日出千号，支持API对接。联系wx_pro_188 获取测试额度",
        "platform": "group_id": "批量注册",
        "has_image": False,
    },
    # === 内容违规 ===
    {
        "content_raw": "全套高清影视资源，包含最新院线片。网盘群共享，加微信 movies_share_2024 进群。链接：https://pan.baidu.com/s/1abc123def",
        "platform": "weibo",
        "group_id": "影视资源",
        "has_image": False,
    },
    {
        "content_raw": "政治敏感内容代发，覆盖全网平台，按条计费。渠道稳定，联系TG：political_sender",
        "platform": "group_id": "代发推广",
        "has_image": False,
    },
    {
        "content_raw": "1V1裸聊平台招代理，高分成，日结。联系QQ 33445566 详谈",
        "platform": "forum",
        "group_id": "成人内容",
        "has_image": True,
    },
    # === 工具交易 ===
    {
        "content_raw": "出售Web漏洞扫描器/脱库工具/SQL注入工具包。支持担保交易。下载地址 https://hacktoolz.org/dl/scanner_pro，联系QQ 33456789",
        "platform": "group_id": "黑客工具",
        "has_image": False,
    },
    {
        "content_raw": "IP代理池，支持HTTP/SOCKS5，每日更新10w+IP，可用于爬虫/注册/刷量。购买：https://proxy-pool.io/buy/10w-ips",
        "platform": "group_id": "代理IP",
        "has_image": False,
    },
    {
        "content_raw": "云手机/群控系统，一机控百台，稳定不掉线。支持远程演示，联系 wx_pro_177",
        "platform": "forum",
        "group_id": "群控设备",
        "has_image": True,
    },
    # === 直播违规 ===
    {
        "content_raw": "抖音直播色情引流技术教学，规避平台审核。全套教程+话术，价格199。加微信 live_se_tech",
        "platform": "group_id": "直播技术",
        "has_image": False,
    },
    {
        "content_raw": "直播间内诱导未成年人打赏话术合集，已验证高转化。QQ群文件下载：55678901",
        "platform": "forum",
        "group_id": "直播运营",
        "has_image": False,
    },
    {
        "content_raw": "无人直播带货，AI数字人24小时不停播，月入10w+。设备+方案打包：https://ai-live.pro/package",
        "platform": "group_id": "无人直播",
        "has_image": True,
    },
    # === 数据泄露 ===
    {
        "content_raw": "出快递数据/电商订单/车主信息，一手货源，可测试。联系TG：data_broker_2025",
        "platform": "group_id": "数据买卖",
        "has_image": False,
    },
    {
        "content_raw": "查档服务：开房记录/通话记录/户籍信息/银行卡流水。加QQ 99887766，备注查档",
        "platform": "tieba",
        "group_id": "查档服务",
        "has_image": False,
    },
    {
        "content_raw": "2025最新银行客户数据，含姓名/手机/身份证/卡号。100万条起售，验证通过率90%+。联系@bankdata_seller",
        "platform": "group_id": "数据买卖",
        "has_image": False,
    },
    # === 信贷欺诈 (新增) ===
    {
        "content_raw": "AB贷操作，白户纯白，无视征信。下款后55分。加微信 ab_loan_master",
        "platform": "group_id": "贷款中介",
        "has_image": False,
    },
    {
        "content_raw": "职业背债人招募，到手50-100万，征信干净的来。包吃住，全程指导。联系QQ 22334455",
        "platform": "forum",
        "group_id": "背债招募",
        "has_image": False,
    },
    {
        "content_raw": "征信修复/洗白，银行内部渠道，成功率95%。先修复后付款。加V：credit_fix_pro",
        "platform": "weibo",
        "group_id": "征信修复",
        "has_image": False,
    }]


def _generate_item(template: dict, base_time: datetime) -> dict:
    """Fill a template with platform-specific fields and timestamps."""
    platform = template["platform"]
    cfg = _PLATFORM_CONFIG.get(platform, _PLATFORM_CONFIG["forum"])

    # Timestamp: spread across last 7 days
    offset_min = random.randint(0, 7 * 24 * 60)
    collected_at = base_time + timedelta(minutes=offset_min)

    # Platform-specific IDs
    uid = str(random.randint(*cfg["uid_range"]))
    if cfg["weibo_id_format"]:
        weibo_id = cfg["weibo_id_format"]()
    else:
        weibo_id = None

    # Build source_url
    msg_id = str(random.randint(10000000, 99999999))
    if platform == "weibo":
        source_url = cfg["url_template"].format(uid=uid, weibo_id=weibo_id)
    elif platform == :
        source_url = cfg["url_template"].format(group_id=template["group_id"], message_id=msg_id)
    elif platform == "tieba":
        source_url = cfg["url_template"].format(message_id=msg_id)
    elif platform == "forum":
        domain = random.choice(["blackforum", "darkweb-china", "hackbase"])
        source_url = cfg["url_template"].format(domain=domain, message_id=msg_id)
    else:
        source_url = f"https://{platform}.com/post/{msg_id}"

    username = random.choice(cfg["username_pool"])

    # Metadata
    metadata = {
        "keyword": template["group_id"],
        "has_image": template.get("has_image", False),
        "has_video": False,
        "is_long_text": len(template["content_raw"]) > 200,
    }
    if platform == "weibo" and weibo_id:
        metadata["weibo_id"] = weibo_id
    if platform == :
        metadata["message_id"] = int(msg_id)
    if platform == "forum":
        metadata["thread_id"] = int(msg_id)

    return {
        "platform": platform,
        "content_raw": template["content_raw"],
        "content_type": "text",
        "source_url": source_url,
        "author_uid": uid,
        "author_username": username,
        "group_id": template["group_id"],
        "collected_at": collected_at.strftime("%Y-%m-%dT%H:%M:%S"),
        "metadata": metadata,
    }


def generate_items(count: int = 50, seed: int = None) -> list[dict]:
    """Generate `count` mock intel items."""
    if seed is not None:
        random.seed(seed)
    base_time = datetime.now() - timedelta(days=7)
    items = []
    for _ in range(count):
        template = random.choice(_TEMPLATES)
        items.append(_generate_item(template, base_time))
    items.sort(key=lambda x: x["collected_at"])
    return items


def main():
    parser = argparse.ArgumentParser(
        description="Generate mock collected intel JSON (collector output format)"
    )
    parser.add_argument("-n", "--count", type=int, default=50)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("-o", "--output", default=None)
    args = parser.parse_args()

    output_path = args.output or str(PROJECT_ROOT / "data" / "mock_collected_intel.json")

    items = generate_items(args.count, args.seed)

    # Write JSON
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(items, f, ensure_ascii=False, indent=2)

    # Summary
    platforms = {}
    groups = {}
    for item in items:
        p = item["platform"]
        g = item["group_id"]
        platforms[p] = platforms.get(p, 0) + 1
        groups[g] = groups.get(g, 0) + 1

    print(f"Generated {len(items)} mock intel items → {output_path}")
    print(f"\nPlatform distribution:")
    for p, c in sorted(platforms.items(), key=lambda x: -x[1]):
        print(f"  {p}: {c}")
    print(f"\nCoverage: {len(groups)} unique groups across {len(platforms)} platforms")
    print(f"\nSample item:")
    print(json.dumps(items[0], ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
