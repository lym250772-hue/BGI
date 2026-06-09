"""平台感知过滤器 — 各平台特有的噪声模式识别和清洗规则。

每个平台预定义了常见的噪声模式（系统提示、模板文字、无效内容等），
以及特定的文本规范化规则。

设计原则：
  - 过滤器返回 (cleaned_text, is_noise, noise_reason) 三元组
  - 尽量保留原始信息，只去除明确的噪声
  - 平台特定规则在前，通用规则兜底
"""

from __future__ import annotations

import re
from typing import Tuple, Optional


# ═══════════════════════════════════════════════════════════════════════════════
# 类型定义
# ═══════════════════════════════════════════════════════════════════════════════

FilterResult = Tuple[str, bool, str]  # (cleaned_text, is_noise, reason)


# ═══════════════════════════════════════════════════════════════════════════════
# 通用噪声模式（所有平台适用）
# ═══════════════════════════════════════════════════════════════════════════════

# 硬广告/平台垃圾关键词（判断整条为噪声，在黑灰产语境中极少是情报）
HARD_NOISE_KEYWORDS = [
    "免费领取", "扫码关注", "点击链接", "点击领取",
    "全网最低", "限时优惠", "名额有限", "马上行动",
    "复制到浏览器", "下载APP", "注册送",
    "在家就能", "手机就能", "免费带", "免费教",
    "招代理", "微商",
]
# 注意：以下关键词在黑灰产语境中可能是情报信号，不放入硬噪声：
#   "兼职刷单" — 讨论刷单的新闻/受害者自述/行业分析都属于情报
#   "加微信"/"加我QQ"/"私我" — 可能是黑产交易引流
#   "日赚"/"日入"/"月入过万" — 可能是刷单/赌博平台宣传语（情报本身）
#   "刷单" — 核心情报关键词

# ═══════════════════════════════════════════════════════════════════════════════
# 关键词误匹配上下文（避免假阳性）
# ═══════════════════════════════════════════════════════════════════════════════

# 某些黑话关键词在特定上下文中是误匹配
# 如 "刷单" 在 "刷题本" 中，"出号" 在 "出号码" 中，"跑分" 在 "跑步分数" 中
FALSE_POSITIVE_CONTEXTS: list[tuple[str, str, str]] = [
    # (关键词, 误匹配模式, 说明)
    ("刷单", r"刷题", "刷题本/刷题库（学习资料，非灰产刷单）"),
    ("出号", r"出号码", "出号码（手机号/通讯，非灰产出号）"),
    ("跑分", r"跑步", "跑步分数（运动，非灰产跑分）"),
    ("搬砖", r"搬砖块|搬砖头|游戏搬砖", "游戏搬砖/工地搬砖（非灰产）"),
    ("上车", r"公交上车|地铁上车|上车请", "交通语境（非灰产上车）"),
    ("下车", r"公交下车|地铁下车|下车请", "交通语境（非灰产下车）"),
    ("引流", r"引流管|医学引流|手术引流", "医学术语（非灰产引流）"),
    ("羊头", r"羊头肉|羊头汤|羊头火锅", "食物（非灰产羊头）"),
    ("大肉", r"大肉面|大肉饭|大肉包子", "食物（非灰产大肉）"),
]

# 低价值内容模式
LOW_VALUE_PATTERNS: list[Tuple[re.Pattern, str]] = [
    (re.compile(r"^[^一-鿿]{0,5}$"), "无中文字符且过短"),
    (re.compile(r"^(.)\1{9,}$"), "单字符重复刷屏"),
    (re.compile(r"^[?？]+$"), "纯问号"),
    (re.compile(r"^[!！.。]+$"), "纯标点符号"),
]

# URL 模式
URL_PATTERN = re.compile(r"https?://\S+")

# HTML 标签
HTML_TAG_PATTERN = re.compile(r"<[^>]+>")

# HTML 实体
HTML_ENTITY_PATTERN = re.compile(r"&[a-zA-Z]+;|&#\d+;")

# Unicode 转义序列 \uXXXX
UNICODE_ESCAPE_PATTERN = re.compile(r"\\u[0-9a-fA-F]{4}")

# 全角数字/字母 → 半角
FULLWIDTH_MAP = str.maketrans(
    "０１２３４５６７８９ＡＢＣＤＥＦＧＨＩＪＫＬＭＮＯＰＱＲＳＴＵＶＷＸＹＺａｂｃｄｅｆｇｈｉｊｋｌｍｎｏｐｑｒｓｔｕｖｗｘｙｚ，。！？＂＃＄％＆＇（）＊＋－／：；＜＝＞＠［＼］＾＿｀｛｜｝～",
    "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz,.!?\"#$%&'()*+-/:;<=>@[\\]^_`{|}~",
)


# ═══════════════════════════════════════════════════════════════════════════════
# 通用处理函数
# ═══════════════════════════════════════════════════════════════════════════════

def _normalize_whitespace(text: str) -> str:
    """规范化空白字符。"""
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def _normalize_unicode(text: str) -> str:
    """处理常见 Unicode 问题。"""
    text = text.replace("​", "")       # 零宽空格
    text = text.replace("\xa0", " ")        # 不换行空格
    text = text.replace("‎", "")       # 左右标记
    text = text.replace("‏", "")       # 右左标记
    text = text.replace("﻿", "")       # BOM
    text = text.replace("\r\n", "\n")       # Windows 换行
    text = text.replace("\r", "\n")         # Mac 换行
    text = text.translate(FULLWIDTH_MAP)    # 全角→半角
    return text


def _url_simplify(text: str) -> str:
    """URL 简化：保留域名，去除完整路径。

    如 https://www.xiaohongshu.com/explore/abc123?token=xxx
    → [链接:xiaohongshu.com]
    """
    def _simplify(match: re.Match) -> str:
        url = match.group()
        try:
            from urllib.parse import urlparse
            parsed = urlparse(url)
            domain = parsed.netloc or parsed.path.split("/")[0]
            # 去掉 www. 前缀
            if domain.startswith("www."):
                domain = domain[4:]
            return f"[链接:{domain}]"
        except Exception:
            return "[链接]"
    return URL_PATTERN.sub(_simplify, text)


def _html_to_plain(text: str) -> str:
    """HTML → 纯文本。"""
    # 常见 HTML 实体
    entities = {
        "&amp;": "&", "&lt;": "<", "&gt;": ">",
        "&quot;": '"', "&apos;": "'", "&nbsp;": " ",
        "&#39;": "'", "&ldquo;": '"', "&rdquo;": '"',
        "&hellip;": "...", "&mdash;": "—", "&ndash;": "–",
    }
    for entity, char in entities.items():
        text = text.replace(entity, char)
    text = HTML_TAG_PATTERN.sub(" ", text)
    text = HTML_ENTITY_PATTERN.sub(" ", text)
    return text


def _unescape_unicode(text: str) -> str:
    """将 \\uXXXX 转义序列还原为实际字符。"""
    try:
        return UNICODE_ESCAPE_PATTERN.sub(
            lambda m: chr(int(m.group()[2:], 16)),
            text,
        )
    except (ValueError, OverflowError):
        return text


def _check_ad_noise(text: str) -> FilterResult:
    """检查是否为硬广告/平台垃圾（不是情报信号）。"""
    # 先检查误匹配上下文（避免假阳性）
    for keyword, fp_pattern, explanation in FALSE_POSITIVE_CONTEXTS:
        if keyword in text and re.search(fp_pattern, text):
            # 这是误匹配，不作为噪声处理
            return text, False, ""

    for kw in HARD_NOISE_KEYWORDS:
        if kw in text:
            return text, True, f"硬广告关键词: {kw}"
    return text, False, ""


def check_keyword_context(text: str) -> dict:
    """检查文本中是否有黑话关键词的误匹配。

    Returns:
        {"has_false_positive": bool, "matched_kw": str, "context": str}
    """
    for keyword, fp_pattern, explanation in FALSE_POSITIVE_CONTEXTS:
        if keyword in text and re.search(fp_pattern, text):
            return {
                "has_false_positive": True,
                "matched_kw": keyword,
                "context": explanation,
            }
    return {"has_false_positive": False, "matched_kw": "", "context": ""}


def _check_low_value(text: str) -> FilterResult:
    """检查是否为低价值内容。"""
    for pattern, reason in LOW_VALUE_PATTERNS:
        if pattern.match(text.strip()):
            return text, True, reason
    return text, False, ""


def apply_common(text: str) -> FilterResult:
    """通用清洗：HTML、Unicode、URL、空白规范化。"""
    text = _html_to_plain(text)
    text = _unescape_unicode(text)
    text = _normalize_unicode(text)
    text = _url_simplify(text)
    text = _normalize_whitespace(text)
    return text, False, ""


# ═══════════════════════════════════════════════════════════════════════════════
# 微博平台
# ═══════════════════════════════════════════════════════════════════════════════

WEIBO_BOILERPLATE = [
    re.compile(r"抱歉[，,][^\n]*没有[^\n]+"),
    re.compile(r"抱歉[，,]根据作者设置[^\n]+"),
    re.compile(r"展开全文"),
    re.compile(r"转发微博"),
    re.compile(r"#微博辟谣#"),
    re.compile(r"O网页链接"),
    re.compile(r"L[^\s]*的微博视频"),
    re.compile(r"//@[^:：]+:[^\n]*"),  # 转发链
]

# 微博短话题（保留话题文本，去#号）
WEIBO_TOPIC_PATTERN = re.compile(r"#([^#]+)#")


def _weibo_clean_topics(text: str) -> str:
    """微博话题 → 保留话题文本。"""
    return WEIBO_TOPIC_PATTERN.sub(r"[话题:\1]", text)


def filter_weibo(text: str) -> FilterResult:
    """微博平台专用过滤。"""
    text, is_noise, reason = apply_common(text)

    # 去除转发链（//@xxx:...）但保留原创内容
    for pattern in WEIBO_BOILERPLATE:
        text = pattern.sub(" ", text)

    # 话题处理
    text = _weibo_clean_topics(text)
    text = _normalize_whitespace(text)

    # 噪声判断
    text, is_noise, reason = _check_low_value(text)
    if is_noise:
        return text, is_noise, reason

    text, is_noise, reason = _check_ad_noise(text)
    if is_noise:
        return text, is_noise, reason

    # 微博特有：太短且无内容
    if len(text) < 5 and not any('一' <= c <= '鿿' for c in text):
        return text, True, "微博无实质内容"

    return text, False, ""


# ═══════════════════════════════════════════════════════════════════════════════
# 知乎平台
# ═══════════════════════════════════════════════════════════════════════════════

ZHIHU_BOILERPLATE = [
    re.compile(r"谢邀[，。]?"),
    re.compile(r"谢邀@[^\s]+[，。]?"),
    re.compile(r"以上[，。]?"),
    re.compile(r"知乎用户[，。]?"),
    re.compile(r"发布于 [\d/]+"),
    re.compile(r"著作权归作者所有[^\n]*"),
    re.compile(r"转载[请需]联系作者[^\n]*"),
    re.compile(r"编辑于 [\d/: ]+"),
    re.compile(r"^#盐选[^\n]*"),      # 盐选推广
    re.compile(r"^本回答来自[^\n]*"),   # 知乎合作
    re.compile(r"^补充[：:][^\n]*"),   # 补充说明标记（保留内容）
]


def filter_zhihu(text: str) -> FilterResult:
    """知乎平台专用过滤。"""
    text, is_noise, reason = apply_common(text)

    for pattern in ZHIHU_BOILERPLATE:
        text = pattern.sub("", text)

    text = _normalize_whitespace(text)

    text, is_noise, reason = _check_low_value(text)
    if is_noise:
        return text, is_noise, reason

    text, is_noise, reason = _check_ad_noise(text)
    if is_noise:
        return text, is_noise, reason

    return text, False, ""


# ═══════════════════════════════════════════════════════════════════════════════
# 贴吧平台
# ═══════════════════════════════════════════════════════════════════════════════

TIEBA_BOILERPLATE = [
    re.compile(r"该楼层疑似违规已被系统折叠[^\n]*"),
    re.compile(r"隐藏此楼[^\n]*"),
    re.compile(r"^回复\s*\d+楼[^\n]*"),      # "回复 3楼"
    re.compile(r"^来自[^\n]+客户端[^\n]*"),   # "来自iPhone客户端"
    re.compile(r"^----[^-\n]*----"),           # 分割线
]

TIEBA_SYSTEM_MSGS = [
    "由于用户举报", "因违反", "被删除", "被禁言",
    "联系贴吧客服", "贴吧安全局",
]


def filter_tieba(text: str) -> FilterResult:
    """贴吧平台专用过滤。"""
    text, is_noise, reason = apply_common(text)

    for pattern in TIEBA_BOILERPLATE:
        text = pattern.sub(" ", text)

    text = _normalize_whitespace(text)

    # 检查系统消息
    for msg in TIEBA_SYSTEM_MSGS:
        if msg in text:
            return text, True, f"贴吧系统消息: {msg}"

    # 纯 emoji/表情刷屏（检查是否只有少量中文）
    from cleaner.emoji_translator import has_excessive_emojis
    if has_excessive_emojis(text, threshold=0.6):
        return text, True, "贴吧表情刷屏"

    text, is_noise, reason = _check_low_value(text)
    if is_noise:
        return text, is_noise, reason

    text, is_noise, reason = _check_ad_noise(text)
    if is_noise:
        return text, is_noise, reason

    return text, False, ""


# ═══════════════════════════════════════════════════════════════════════════════
# 抖音平台
# ═══════════════════════════════════════════════════════════════════════════════

DOUYIN_BOILERPLATE = [
    re.compile(r"在抖音[，,]?[^\n]{0,20}看全文"),
    re.compile(r"#抖音[^\s#]*"),
    re.compile(r"@抖音[^\s]+"),
    re.compile(r"点击[^\n]{0,10}链接[^\n]*"),
    re.compile(r"长按[^\n]{0,10}复制[^\n]*"),
    re.compile(r"打开抖音[^\n]*"),
]

# 检测 hashtag 数量
DOUYIN_HASHTAG_RE = re.compile(r"#[^\s#]+")


def filter_douyin(text: str) -> FilterResult:
    """抖音平台专用过滤。"""
    text, is_noise, reason = apply_common(text)

    # 检测 hashtag 泛滥
    hashtags = DOUYIN_HASHTAG_RE.findall(text)
    if len(hashtags) > 5:
        # 保留前3个话题
        for h in hashtags[3:]:
            text = text.replace(h, "")
        text = _normalize_whitespace(text)

    for pattern in DOUYIN_BOILERPLATE:
        text = pattern.sub(" ", text)

    # 保留话题信息（转为 [话题:xxx]）
    text = DOUYIN_HASHTAG_RE.sub(lambda m: f"[话题:{m.group()[1:]}]", text)
    text = _normalize_whitespace(text)

    text, is_noise, reason = _check_low_value(text)
    if is_noise:
        return text, is_noise, reason

    text, is_noise, reason = _check_ad_noise(text)
    if is_noise:
        return text, is_noise, reason

    return text, False, ""


# ═══════════════════════════════════════════════════════════════════════════════
# 小红书平台
# ═══════════════════════════════════════════════════════════════════════════════

XHS_BOILERPLATE = [
    re.compile(r"#小红书[^\s#]*"),
    re.compile(r"@小红书[^\s]+"),
    re.compile(r"图文来源[^\n]*"),
    re.compile(r"以上内容仅供参考[^\n]*"),
    re.compile(r"笔记分类[^\n]*"),
    re.compile(r"#笔记灵感[^\n]*"),
]

XHS_HASHTAG_RE = re.compile(r"#[^\s#]+")


def filter_xiaohongshu(text: str) -> FilterResult:
    """小红书平台专用过滤。"""
    text, is_noise, reason = apply_common(text)

    for pattern in XHS_BOILERPLATE:
        text = pattern.sub(" ", text)

    # 话题处理
    hashtags = XHS_HASHTAG_RE.findall(text)
    # 小红书通常带很多话题标签，保留前5个
    if len(hashtags) > 5:
        for h in hashtags[5:]:
            text = text.replace(h, "")
    text = XHS_HASHTAG_RE.sub(lambda m: f"[话题:{m.group()[1:]}]", text)
    text = _normalize_whitespace(text)

    # 小红书特有的：纯话题标签无正文
    from cleaner.emoji_translator import has_excessive_emojis
    if has_excessive_emojis(text, threshold=0.5):
        return text, True, "小红书纯表情/标签帖"

    text, is_noise, reason = _check_low_value(text)
    if is_noise:
        return text, is_noise, reason

    text, is_noise, reason = _check_ad_noise(text)
    if is_noise:
        return text, is_noise, reason

    return text, False, ""


# ═══════════════════════════════════════════════════════════════════════════════
# 闲鱼平台
# ═══════════════════════════════════════════════════════════════════════════════

XIANYU_BOILERPLATE = [
    re.compile(r"^我在闲鱼发布了[^\n]*"),
    re.compile(r"^在闲鱼搜[^\n]*"),
    re.compile(r"^本店[^\n]{0,10}出售"),
    # 注意：以下关键词只去除短语本身，不吞整行
    # "诚信经营"/"支持花呗付款" — 在黑灰产语境中可能是商品描述的一部分
]


def filter_xianyu(text: str) -> FilterResult:
    """闲鱼平台专用过滤。

    闲鱼特殊处理：保留价格信息、商品描述，去除营销模板。
    """
    text, is_noise, reason = apply_common(text)

    for pattern in XIANYU_BOILERPLATE:
        text = pattern.sub(" ", text)

    text = _normalize_whitespace(text)

    text, is_noise, reason = _check_low_value(text)
    if is_noise:
        return text, is_noise, reason

    text, is_noise, reason = _check_ad_noise(text)
    if is_noise:
        return text, is_noise, reason

    return text, False, ""


# ═══════════════════════════════════════════════════════════════════════════════
# QQ群平台
# ═══════════════════════════════════════════════════════════════════════════════

QQ_SYSTEM_PATTERNS = [
    re.compile(r"^\[系统消息\][^\n]*"),
    re.compile(r"^\[群通知\][^\n]*"),
    re.compile(r"^\[公告\][^\n]*"),
    re.compile(r"你已加入[^\n]*"),
    re.compile(r"已退出群聊"),
    re.compile(r"被管理员[^\n]*"),
    re.compile(r"被禁言[^\n]*"),
    re.compile(r"开启了全员禁言"),
    re.compile(r"修改群名为[^\n]*"),
    re.compile(r"邀请[^\n]*加入了群聊"),
    re.compile(r"^\[QQ红包\][^\n]*"),
    re.compile(r"^\[戳一戳\][^\n]*"),
]

# QQ 表情代码 [CQ:face,id=xxx]
QQ_FACE_PATTERN = re.compile(r"\[CQ:[^\]]+\]")

# 纯表情/符号消息（无中文）
QQ_PURE_EMOJI_RE = re.compile(r"^[^一-鿿a-zA-Z0-9]+$")


def filter_qq_group(text: str) -> FilterResult:
    """QQ群平台专用过滤。"""
    text, is_noise, reason = apply_common(text)

    # 检查系统消息
    for pattern in QQ_SYSTEM_PATTERNS:
        if pattern.match(text):
            return text, True, f"QQ系统消息: {text[:30]}"

    # 去除 CQ 码（保留描述文字）
    text = QQ_FACE_PATTERN.sub(" ", text)
    text = _normalize_whitespace(text)

    # 纯表情消息
    if QQ_PURE_EMOJI_RE.match(text.strip()):
        return text, True, "QQ纯表情/符号消息"

    text, is_noise, reason = _check_low_value(text)
    if is_noise:
        return text, is_noise, reason

    text, is_noise, reason = _check_ad_noise(text)
    if is_noise:
        return text, is_noise, reason

    return text, False, ""


# ═══════════════════════════════════════════════════════════════════════════════
# 平台过滤器注册表
# ═══════════════════════════════════════════════════════════════════════════════

PLATFORM_FILTERS: dict[str, callable] = {
    "weibo": filter_weibo,
    "zhihu": filter_zhihu,
    "tieba": filter_tieba,
    "douyin": filter_douyin,
    "xiaohongshu": filter_xiaohongshu,
    "xianyu": filter_xianyu,
    "qq_group": filter_qq_group,
}


def filter_by_platform(platform: str, text: str) -> FilterResult:
    """根据平台调用对应过滤器。

    Args:
        platform: 平台标识 (weibo/zhihu/tieba/douyin/xiaohongshu/xianyu/qq_group)
        text: 原始文本

    Returns:
        (cleaned_text, is_noise, reason)
    """
    filter_func = PLATFORM_FILTERS.get(platform)
    if filter_func:
        return filter_func(text)
    # 未知平台：仅通用清洗
    text, _, _ = apply_common(text)
    text, is_noise, reason = _check_low_value(text)
    if not is_noise:
        text, is_noise, reason = _check_ad_noise(text)
    return text, is_noise, reason
