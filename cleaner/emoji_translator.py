"""Emoji 语义翻译器 — 将 emoji 转为中文语义描述，保留原文的同时追加翻译。

用于清洗管道 Step 0：使后续的 L1 关键词匹配和 L2 RoBERTa 分类器
能够理解 emoji 背后的语义（如 💰→金钱交易, 🔥→热门/紧急）。

纯字典映射，无外部依赖。
"""

from __future__ import annotations

import re
from typing import Tuple

# ═══════════════════════════════════════════════════════════════════════════════
# Emoji → 中文语义映射表（灰黑产语境）
# ═══════════════════════════════════════════════════════════════════════════════

EMOJI_MAP: dict[str, str] = {
    # ── 金钱/交易类 ──
    "💰": "[金钱/收益]",
    "💵": "[美元/现金]",
    "💴": "[日元/现金]",
    "💶": "[欧元/现金]",
    "💷": "[英镑/现金]",
    "💸": "[飞钱/快速赚钱]",
    "💳": "[银行卡/信用]",
    "💲": "[美元符号]",
    "🤑": "[暴富/贪婪]",
    "🧧": "[红包/转账]",
    "💎": "[钻石/高价值]",
    "🪙": "[硬币/代币]",
    "🏦": "[银行/金融机构]",

    # ── 交易/操作类 ──
    "🤝": "[合作/交易]",
    "📱": "[手机/联系]",
    "📲": "[拨打电话]",
    "📞": "[电话联系]",
    "✉️": "[邮件/私信]",
    "📩": "[私信联系]",
    "📨": "[收件/消息]",
    "🔗": "[链接/跳转]",
    "📎": "[附件/文件]",
    "📋": "[清单/任务]",
    "✅": "[已完成/可做]",
    "❌": "[不可/拒绝]",
    "⭕": "[圈定/范围]",
    "🔴": "[红色警示]",
    "🟢": "[绿色/可用]",
    "🟡": "[黄色/注意]",

    # ── 账号/身份类 ──
    "👤": "[个人账号]",
    "👥": "[多人/群组]",
    "👁️": "[观察/监控]",
    "🤫": "[保密/悄悄]",
    "🤐": "[封口/勿传]",
    "🔑": "[密钥/密码]",
    "🔒": "[锁定/安全]",
    "🔓": "[解锁/破解]",
    "🛡️": "[防护/盾牌]",
    "🎭": "[伪装/面具]",
    "👻": "[幽灵/隐身]",
    "🕵️": "[侦探/侦查]",

    # ── 刷量/数据类 ──
    "📊": "[数据/统计]",
    "📈": "[增长/上升]",
    "📉": "[下降/衰退]",
    "🔥": "[热门/火爆/紧急]",
    "💥": "[爆发/冲击]",
    "🚀": "[快速起飞/暴涨]",
    "⭐": "[星级/评分]",
    "🌟": "[明星/亮点]",
    "💯": "[满分/百分百]",
    "👍": "[点赞/好评]",
    "👎": "[差评/反对]",
    "❤️": "[喜欢/收藏]",
    "🔄": "[循环/转售]",
    "♻️": "[回收/复用]",

    # ── 平台/渠道类 ──
    "🐟": "[闲鱼/二手]",
    "📕": "[小红书]",
    "🎵": "[抖音/音乐]",
    "🐦": "[Twitter/X]",
    "💬": "[聊天/私信]",
    "📢": "[公告/广播]",
    "📣": "[扩音/宣传]",
    "🔔": "[通知/提醒]",
    "📌": "[置顶/固定]",

    # ── 风险/警告类 ──
    "⚠️": "[警告/风险]",
    "🚫": "[禁止/封禁]",
    "🚨": "[警报/执法]",
    "💀": "[死亡/危险]",
    "☠️": "[有毒/危险]",
    "🗡️": "[攻击/武器]",
    "💣": "[炸弹/威胁]",
    "🧨": "[炸药/危险]",
    "🔪": "[刀具/威胁]",

    # ── 常见正负面情绪 ──
    "😊": "[开心/友好]",
    "😢": "[悲伤/失望]",
    "😡": "[愤怒/不满]",
    "😱": "[震惊/恐惧]",
    "🤔": "[思考/怀疑]",
    "🙏": "[请求/感谢]",
    "💪": "[强力/靠谱]",
    "👏": "[鼓掌/赞许]",
    "🎉": "[庆祝/促销]",
    "🎁": "[礼物/福利]",

    # ── 技术/工具类 ──
    "🤖": "[机器人/自动]",
    "💻": "[电脑/在线]",
    "🖥️": "[桌面端]",
    "📡": "[信号/传输]",
    "🌐": "[网络/全球]",
    "🔧": "[工具/配置]",
    "⚙️": "[设置/齿轮]",
    "🧲": "[吸引/引流]",
    "🎯": "[精准/目标]",
    "🏷️": "[标签/分类]",
}

# 编译正则：匹配所有已知 emoji（按长度降序，避免短序列误匹配）
_EMOJI_PATTERN = re.compile(
    "|".join(re.escape(e) for e in sorted(EMOJI_MAP.keys(), key=len, reverse=True))
)

# 更宽泛的 emoji 检测：Unicode emoji 范围
# 精确 emoji Unicode 范围（仅十六进制转义，GBK/UTF-8 跨平台安全）
_BROAD_EMOJI_RE = re.compile(
    "[\U0001F600-\U0001F64F"      # 表情符号
    "\U0001F300-\U0001F5FF"       # 杂项符号和象形文字
    "\U0001F680-\U0001F6FF"       # 交通和地图符号
    "\U0001F700-\U0001F77F"       # 炼金术符号
    "\U0001F780-\U0001F7FF"       # 几何形状扩展
    "\U0001F800-\U0001F8FF"       # 补充箭头-C
    "\U0001F900-\U0001F9FF"       # 补充符号和象形文字
    "\U0001FA00-\U0001FA6F"       # 棋子
    "\U0001FA70-\U0001FAFF"       # 符号和象形文字扩展-A
    "\U00002600-\U000027BF"       # 杂项符号 + 装饰符号
    "\U000024C2-\U000024FF"       # 带圈字母数字 (ⓂⓃ...)
    "\U0001F100-\U0001F1FF"       # 带圈表意文字补充 + 旗帜
    "\U00002B05-\U00002B07"       # 箭头 (⬅⬆➡⬇)
    "\U00002934-\U00002935"       # 弯曲箭头 (⤴⤵)
    "\U000025AA-\U000025FE"       # 几何形状 (▪▫◾◽...)
    "\U000023CF"                   # 弹出 (⏏)
    "\U000023E9-\U000023F3"       # 控制符号 (⏩⏪...⏳...)
    "\U000023F8-\U000023FA"       # 控制符号 (⏸⏹⏺)
    "\U0000FE00-\U0000FE0F"       # 变体选择器-1 (VS1-VS16)
    "\U0000200D"                   # 零宽连接符 (ZWJ)
    "]+",
    re.UNICODE,
)


def extract_emojis(text: str) -> list[Tuple[int, str, str]]:
    """提取文本中的 emoji，返回 [(位置, emoji字符, 语义翻译), ...]。

    只返回在 EMOJI_MAP 中有映射的 emoji。
    """
    results: list[Tuple[int, str, str]] = []
    seen_positions: set[int] = set()
    for match in _EMOJI_PATTERN.finditer(text):
        pos = match.start()
        if pos not in seen_positions:
            emoji_char = match.group()
            meaning = EMOJI_MAP.get(emoji_char, "")
            results.append((pos, emoji_char, meaning))
            seen_positions.add(pos)
    return sorted(results, key=lambda x: x[0])


def translate(text: str, append: bool = True) -> str:
    """将文本中的 emoji 翻译为中文语义。

    Args:
        text: 原始文本
        append: True = 原文后追加 [Emoji语义: ...], False = 替换emoji

    Returns:
        处理后的文本
    """
    emojis = extract_emojis(text)
    if not emojis:
        return text

    if append:
        # 去重收集语义
        meanings = list(dict.fromkeys(m for _, _, m in emojis if m))
        if meanings:
            return text + " [Emoji语义: " + " ".join(meanings) + "]"
        return text
    else:
        # 替换模式：将 emoji 替换为语义标签
        result = text
        for _, emoji_char, meaning in emojis:
            if meaning:
                result = result.replace(emoji_char, meaning, 1)
        return result


def _count_emoji_chars(text: str) -> int:
    """统计文本中 emoji 字符数（逐个字符检查，避免 findall+量词只返回匹配数）。"""
    count = 0
    for ch in text:
        if _BROAD_EMOJI_RE.match(ch):
            count += 1
    return count


def has_excessive_emojis(text: str, threshold: float = 0.5) -> bool:
    """检查文本是否包含过多 emoji（超过总字符数的 threshold）。

    用于判断是否为纯表情/灌水内容。
    """
    if not text:
        return False
    emoji_chars = _count_emoji_chars(text)
    total_chars = len(text.replace(" ", "").replace("\n", ""))
    if total_chars == 0:
        return False
    return (emoji_chars / total_chars) > threshold


def emoji_density(text: str) -> float:
    """返回 emoji 密度 (0.0 ~ 1.0)。"""
    if not text:
        return 0.0
    emoji_chars = _count_emoji_chars(text)
    total_chars = len(text.replace(" ", "").replace("\n", ""))
    if total_chars == 0:
        return 0.0
    return emoji_chars / total_chars
