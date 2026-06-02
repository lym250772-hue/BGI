"""
Metadata 增强分类器 (L1.5) — 利用平台元数据增强风险分类，零 API 开销。

在 L1(关键词) 和 L2(RoBERTa) 之间运行，利用 hashtag、播放量、互动数据
等 metadata 信号提供分类提示和置信度加权。

设计原则:
  - 纯规则匹配，零 LLM 开销
  - 不覆盖 L1 的结果，只做增强
  - 对文本平台(贴吧/知乎/微博)为空操作
  - 对抖音/小红书提供有效的分类线索

用法:
    from analyzer.metadata_classifier import metadata_classifier

    result = metadata_classifier.classify("加微信xxx", {"hashtags":["无人直播"]}, "douyin")
    # → {"label_hint": "LIVE_VIOLATION", "sub_label_hint": "无人直播",
    #    "confidence_boost": 0.25, "signals": ["hashtag匹配: #无人直播"]}
"""

from __future__ import annotations
from schema import IntentLabel

# ═══════════════════════════════════════════════════════════════════════════════
# Hashtag 信号规则 — 标签 → 风险分类映射
# ═══════════════════════════════════════════════════════════════════════════════

# 格式: (hashtag_pattern, (IntentLabel, sub_label))
# pattern 支持子串匹配（不区分大小写）
HASHTAG_RULES: list[tuple[str, tuple[str, str]]] = [
    # ── 直播违规 ──
    ("无人直播",  (IntentLabel.LIVE_VIOLATION, "无人直播")),
    ("数字人",    (IntentLabel.LIVE_VIOLATION, "数字人直播")),
    ("录播",      (IntentLabel.LIVE_VIOLATION, "录播带货")),
    ("挂播",      (IntentLabel.LIVE_VIOLATION, "挂机直播")),
    ("矩阵号",    (IntentLabel.LIVE_VIOLATION, "矩阵号直播")),
    ("循环播放",  (IntentLabel.LIVE_VIOLATION, "无人直播")),
    ("无人带货",  (IntentLabel.LIVE_VIOLATION, "无人直播带货")),

    # ── 诈骗 ──
    ("兼职",       (IntentLabel.FRAUD, "刷单诈骗")),
    ("日赚",       (IntentLabel.FRAUD, "刷单诈骗")),
    ("日结",       (IntentLabel.FRAUD, "刷单诈骗")),
    ("宝妈兼职",   (IntentLabel.FRAUD, "刷单诈骗")),
    ("学生兼职",   (IntentLabel.FRAUD, "刷单诈骗")),
    ("副业",       (IntentLabel.FRAUD, "金融诈骗")),
    ("搞钱",       (IntentLabel.FRAUD, "金融诈骗")),
    ("快速回本",   (IntentLabel.FRAUD, "金融诈骗")),
    ("包赚",       (IntentLabel.FRAUD, "金融诈骗")),
    ("稳赚",       (IntentLabel.FRAUD, "金融诈骗")),
    ("代收代付",   (IntentLabel.FRAUD, "洗钱")),
    ("跑分",       (IntentLabel.FRAUD, "洗钱")),

    # ── 作弊 ──
    ("刷粉",       (IntentLabel.CHEATING, "刷量刷单")),
    ("刷赞",       (IntentLabel.CHEATING, "刷量刷单")),
    ("涨粉",       (IntentLabel.CHEATING, "刷量刷单")),
    ("刷播放",     (IntentLabel.CHEATING, "刷量刷单")),
    ("刷单",       (IntentLabel.CHEATING, "刷量刷单")),
    ("薅羊毛",     (IntentLabel.CHEATING, "营销套利")),
    ("撸货",       (IntentLabel.CHEATING, "营销套利")),
    ("外挂",       (IntentLabel.CHEATING, "游戏外挂")),
    ("脚本",       (IntentLabel.CHEATING, "游戏外挂")),
    ("辅助",       (IntentLabel.CHEATING, "游戏外挂")),
    ("云手机",     (IntentLabel.CHEATING, "群控作弊")),
    ("群控",       (IntentLabel.CHEATING, "群控作弊")),

    # ── 引流 ──
    ("引流",       (IntentLabel.TRAFFIC_DRIVEN, "站外导流")),
    ("私域",       (IntentLabel.TRAFFIC_DRIVEN, "站外导流")),
    ("加微信",     (IntentLabel.TRAFFIC_DRIVEN, "站外导流")),
    ("加V",        (IntentLabel.TRAFFIC_DRIVEN, "站外导流")),
    ("免费领",     (IntentLabel.TRAFFIC_DRIVEN, "站外导流")),
    ("菠菜",       (IntentLabel.TRAFFIC_DRIVEN, "赌博引流")),
    ("博彩",       (IntentLabel.TRAFFIC_DRIVEN, "赌博引流")),

    # ── 账号黑产 ──
    ("出号",       (IntentLabel.ACCOUNT_BLACK, "账号买卖")),
    ("账号交易",   (IntentLabel.ACCOUNT_BLACK, "账号买卖")),
    ("千粉号",     (IntentLabel.ACCOUNT_BLACK, "账号买卖")),
    ("万粉号",     (IntentLabel.ACCOUNT_BLACK, "账号买卖")),
    ("接码",       (IntentLabel.ACCOUNT_BLACK, "接码/打码")),
    ("打码",       (IntentLabel.ACCOUNT_BLACK, "接码/打码")),
    ("老号",       (IntentLabel.ACCOUNT_BLACK, "账号买卖")),
    ("新号",       (IntentLabel.ACCOUNT_BLACK, "批量注册")),
    ("白号",       (IntentLabel.ACCOUNT_BLACK, "批量注册")),

    # ── 工具交易 ──
    ("卡密",       (IntentLabel.TOOL_TRADE, "卡密交易")),
    ("发卡",       (IntentLabel.TOOL_TRADE, "卡密交易")),
    ("数据",       (IntentLabel.TOOL_TRADE, "数据买卖")),
    ("料子",       (IntentLabel.TOOL_TRADE, "数据买卖")),

    # ── 内容违规 ──
    ("色情",       (IntentLabel.CONTENT_VIOLATION, "色情低俗")),
    ("裸聊",       (IntentLabel.CONTENT_VIOLATION, "色情低俗")),
    ("福利姬",     (IntentLabel.CONTENT_VIOLATION, "色情低俗")),
]


# ═══════════════════════════════════════════════════════════════════════════════
# MetadataClassifier
# ═══════════════════════════════════════════════════════════════════════════════

class MetadataClassifier:
    """L1.5 分类器 — 使用 metadata 信号增强风险分类。"""

    def classify(self, text: str, metadata: dict, platform: str) -> dict:
        """分析 metadata 信号并返回分类提示。

        Args:
            text: 清洗后的文本
            metadata: 平台元数据 (hashtags, play_count, like_count, tags, etc.)
            platform: 来源平台 (douyin / xiaohongshu / ...)

        Returns:
            {
                "label_hint": str | None,       # 风险大类提示
                "sub_label_hint": str | None,   # 风险子类提示
                "confidence_boost": float,       # 置信度加权 (0.0-0.5)
                "signals": [str],                # 命中的信号描述
                "should_skip_llm": bool,         # 信号足够强时可跳过 LLM
            }
        """
        if platform not in ("douyin", "xiaohongshu"):
            return self._empty_result()

        metadata = metadata or {}
        signals = []
        label_hint = None
        sub_label_hint = None
        max_confidence = 0.0

        # ── 信号1: Hashtag/标签匹配 ──────────────────────────────────────
        hashtags = metadata.get("hashtags", []) or metadata.get("tags", [])
        if isinstance(hashtags, str):
            hashtags = [hashtags]
        if hashtags:
            for tag in hashtags:
                tag_lower = str(tag).lower().replace("#", "")
                for pat, (label, sub) in HASHTAG_RULES:
                    if pat in tag_lower:
                        signals.append(f"hashtag匹配: #{tag} → {sub}")
                        if 0.3 > max_confidence:
                            label_hint = label
                            sub_label_hint = sub
                            max_confidence = 0.3

        # ── 信号2: 文本 + hashtag 联合分析 ─────────────────────────────
        text_lower = text.lower() if text else ""

        # 包含"微信/vx/加V" + 高播放量 → 引流
        has_contact_in_text = any(kw in text_lower for kw in
                                  ("微信", "wx", "vx", "加v", "加微信", "私信"))
        play_count = int(metadata.get("play_count", 0) or 0)
        if has_contact_in_text and play_count > 10000:
            signals.append(f"高播放({play_count})+联系方式 → 站外导流")
            if 0.25 > max_confidence:
                label_hint = IntentLabel.TRAFFIC_DRIVEN
                sub_label_hint = "站外导流"
                max_confidence = 0.25

        # ── 信号3: 播放量异常（高播放低互动） → 刷量 ────────────────────
        like_count = int(metadata.get("like_count", 0) or 0)
        if play_count > 100000 and like_count < 1000:
            signals.append(f"播放量异常: {play_count}播放/{like_count}点赞 → 刷量")
            if 0.2 > max_confidence:
                label_hint = IntentLabel.CHEATING
                sub_label_hint = "刷量刷单"
                max_confidence = 0.2

        # ── 信号4: 短视频+联系方式 → 导流广告 ─────────────────────────
        duration = int(metadata.get("duration", 0) or 0)
        if duration > 0 and duration < 30 and has_contact_in_text:
            signals.append(f"短视频({duration}s)+联系方式 → 导流广告")
            if 0.15 > max_confidence:
                label_hint = IntentLabel.TRAFFIC_DRIVEN
                sub_label_hint = "站外导流"
                max_confidence = 0.15

        # ── 信号5: 图片列表非空+文本含微信 → 图片含联系方式 ───────────
        image_list = metadata.get("image_list", []) or []
        if image_list and has_contact_in_text:
            signals.append("含图片+联系方式 → 图片可能含二维码/微信号")
            if 0.15 > max_confidence:
                label_hint = label_hint or IntentLabel.TRAFFIC_DRIVEN
                sub_label_hint = sub_label_hint or "站外导流"

        if not signals:
            return self._empty_result()

        return {
            "label_hint": str(label_hint) if label_hint else None,
            "sub_label_hint": sub_label_hint,
            "confidence_boost": round(max_confidence, 2),
            "signals": signals,
            "should_skip_llm": max_confidence >= 0.3,
        }

    @staticmethod
    def _empty_result() -> dict:
        return {
            "label_hint": None,
            "sub_label_hint": None,
            "confidence_boost": 0.0,
            "signals": [],
            "should_skip_llm": False,
        }


# ── 单例 ────────────────────────────────────────────────────────────────────

metadata_classifier = MetadataClassifier()
