"""Data cleaning pipeline: normalize, deduplicate with SimHash, filter noise, mark high-risk.

v0.8: Platform-aware noise filter, emoji translation, metadata enrichment.
"""
import re
import hashlib
from typing import Optional
from loguru import logger

from config.settings import settings
from schema import HIGH_RISK_KEYWORDS, Priority

# SimHash import – fall back to pure-Python if the C extension isn't available
try:
    from simhash import SimHash as _SimHashC  # type: ignore

    def _compute_simhash(text: str) -> str:
        return hex(_SimHashC(text).value)
except ImportError:
    logger.warning("simhash-py not installed, using built-in SimHash fallback")
    from cleaner.simhash_py import SimHash as _SimHashPy

    def _compute_simhash(text: str) -> str:
        return hex(_SimHashPy(text).value)


# ── 平台感知最小字符数 ───────────────────────────────────────────────────

_PLATFORM_MIN_CHARS: dict[str, int] = {
    "douyin": 2,          # 抖音描述极短，2字+emoji+标签也有效
    "xiaohongshu": 3,     # 小红书笔记标题+正文足够
}
_DEFAULT_MIN_CHARS = 3    # 贴吧/知乎/微博/Telegram


class CleaningPipeline:
    """Cleaning pipeline with platform-aware noise detection and emoji support."""

    # ------------------------------------------------------------------
    # Step 0: Emoji translation & metadata enrichment
    # ------------------------------------------------------------------

    @staticmethod
    def _translate_emojis(text: str) -> tuple[str, bool, str]:
        """Translate emoji to gray-market meanings. Returns (enriched_text, has_emoji, emoji_text)."""
        has_e = False
        emoji_text = ""
        try:
            from cleaner.emoji_translator import emoji_translator
            if emoji_translator.contains_emoji(text):
                has_e = True
                emoji_text = emoji_translator.translate(text, use_llm=False)
                # 把翻译追加到原文后面，保留原始 emoji + 添加语义解释
                return emoji_text, has_e, emoji_text
        except ImportError:
            pass
        return text, has_e, text

    @staticmethod
    def _enrich_metadata(text: str, metadata: dict, platform: str) -> str:
        """Append structured metadata as searchable text for downstream analysis."""
        if not metadata:
            return text
        parts = [text]
        if platform == "douyin":
            hashtags = metadata.get("hashtags", [])
            if hashtags:
                parts.append("【标签】" + " ".join("#" + h for h in hashtags))
            play = metadata.get("play_count", 0)
            if play and play > 0:
                parts.append(f"【播放量】{play}")
            like = metadata.get("like_count", 0)
            if like and like > 0:
                parts.append(f"【点赞】{like}")
        elif platform == "xiaohongshu":
            tags = metadata.get("tags", [])
            if tags:
                parts.append("【标签】" + " ".join("#" + t for t in tags))
            like = metadata.get("like_count", 0)
            if like and like > 0:
                parts.append(f"【点赞】{like}")
            collect = metadata.get("collect_count", 0)
            if collect and collect > 0:
                parts.append(f"【收藏】{collect}")
        return "\n".join(parts)

    # ------------------------------------------------------------------
    # Step 1: Basic normalization
    # ------------------------------------------------------------------

    @staticmethod
    def normalize(text: str) -> str:
        """Remove HTML tags, normalize whitespace, keep emoji and numbers."""
        # strip HTML
        text = re.sub(r"<[^>]+>", " ", text)
        # collapse whitespace
        text = re.sub(r"\s+", " ", text)
        # normalize common unicode
        text = text.replace("​", "").replace("\xa0", " ")
        return text.strip()

    # ------------------------------------------------------------------
    # Step 2: SimHash dedup
    # ------------------------------------------------------------------

    @staticmethod
    def compute_simhash(text: str) -> str:
        return _compute_simhash(text)

    @staticmethod
    def hamming_distance(a: str, b: str) -> int:
        """Hamming distance between two hex SimHash strings."""
        if len(a) != len(b):
            return max(len(a), len(b)) * 4
        x = int(a, 16) ^ int(b, 16)
        return x.bit_count()

    def is_duplicate(self, new_hash: str, existing_hashes: list[str]) -> bool:
        for h in existing_hashes:
            if self.hamming_distance(new_hash, h) <= settings.simhash_threshold:
                return True
        return False

    # ------------------------------------------------------------------
    # Step 3: Platform-aware noise filter
    # ------------------------------------------------------------------

    @classmethod
    def is_noise(cls, text: str, platform: str = "",
                 metadata: dict | None = None) -> tuple[bool, str, float]:
        """Platform-aware noise detection.

        Returns (is_noise, reason, noise_score 0.0-1.0).
        noise_score > 0 means flagged but not necessarily discarded;
        noise_score == 0 means hard noise → should discard.

        Platform rules:
          - douyin: min 2 chars; emoji+hashtag can save very short text
          - xiaohongshu: min 3 chars (notes have title+body)
          - text platforms: min 3 chars (existing behavior)
        """
        metadata = metadata or {}

        # Hard noise: completely empty
        if not text or not text.strip():
            return True, "empty", 1.0

        # Platform-specific minimum length
        min_chars = _PLATFORM_MIN_CHARS.get(platform, _DEFAULT_MIN_CHARS)

        # 检测 emoji 和 hashtag 信号
        has_emoji = False
        try:
            from cleaner.emoji_translator import contains_emoji as _ce
            has_emoji = _ce(text)
        except ImportError:
            pass

        has_hashtag = bool(metadata.get("hashtags") or metadata.get("tags"))

        stripped_len = len(text.strip())

        if stripped_len < min_chars:
            # 短但有视觉信号 → 不丢弃，标记低置信度
            if has_emoji or has_hashtag:
                return False, "short_with_signals", 0.4
            return True, "too_short", 1.0

        # 中文检测（修复原 LOW_VALUE_PATTERNS 的 \\u 转义 bug）
        has_chinese = bool(re.search(r'[一-鿿]', text))

        if not has_chinese:
            # 短视频平台的 emoji+数字+标签 文本也算有效
            if platform in ("douyin", "xiaohongshu"):
                if has_emoji or has_hashtag:
                    return False, "no_chinese_with_signals", 0.35
            if platform == "douyin" and stripped_len >= 2:
                return False, "short_douyin_no_chinese", 0.35
            # 纯英文/数字长文本不算噪声（可能含 URL/联系方式）
            if stripped_len >= 10:
                return False, "", 0.0
            return True, "no_chinese_no_signals", 0.8

        return False, "", 0.0

    # ------------------------------------------------------------------
    # Step 4: High-risk marker
    # ------------------------------------------------------------------

    @staticmethod
    def mark_priority(text: str) -> str:
        """Scan for high-risk keywords; return Priority value."""
        text_lower = text.lower()
        for kw in HIGH_RISK_KEYWORDS:
            if kw in text_lower:
                return Priority.HIGH
        return Priority.NORMAL

    # ------------------------------------------------------------------
    # Step 5: Entity detection — check for contact/money trail indicators
    # ------------------------------------------------------------------

    # 实体检测正则：联系方式、资金线索、链接
    ENTITY_PATTERNS = [
        (re.compile(r'微信[：:]\s*[\w\-_]+'), 'wechat_explicit'),
        (re.compile(r'[wW][xX]\s*[：:]?\s*[\w\-_]{5,}'), 'wechat_abbr'),
        (re.compile(r'[微Ｖ][信][号]?\s*[：:]\s*[\w\-_]+'), 'wechat_cn'),
        (re.compile(r'[Qq]{2}\s*[：:]?\s*\d{4,}'), 'qq'),
        (re.compile(r'1[3-9]\d{9}'), 'phone'),
        (re.compile(r'https?://[^\s]{5,}'), 'url'),
        (re.compile(r'[a-zA-Z0-9][\w\-]{3,}\.[a-zA-Z]{2,}/'), 'domain_path'),
        (re.compile(r'群[号]?\s*[：:]?\s*\d{4,}'), 'group'),
        (re.compile(r'联系[：:]\s*[\w\-_@]+'), 'contact'),
        (re.compile(r'下载[：:地址]?\s*https?://'), 'download_link'),
    ]

    @classmethod
    def has_entities(cls, text: str) -> bool:
        """检测文本是否包含联系方式、资金线索、链接等可追溯实体。"""
        for pattern, _ in cls.ENTITY_PATTERNS:
            if pattern.search(text):
                return True
        return False

    # ------------------------------------------------------------------
    # Step 6: Risk relevance check
    # ------------------------------------------------------------------

    @classmethod
    def is_risk_relevant(cls, text: str, priority: str) -> tuple[bool, str]:
        """判断数据是否具有风险情报价值。

        保留逻辑:
          ✅ priority = high  → 命中高危关键词，无论有没有实体都保留
          ✅ 含可追溯实体（微信/QQ/手机/链接） → 即使没命中关键词也保留，供下游提取
          ❌ priority = normal 且无实体 → 普通讨论，不具情报价值，丢弃

        这样确保入库的都是"有线索可追"或"有风险可判"的数据。
        """
        if priority == Priority.HIGH:
            return True, "high_risk_keyword"

        if cls.has_entities(text):
            return True, "has_entity"

        return False, "low_risk_no_entity"

    # ------------------------------------------------------------------
    # Main pipeline entry
    # ------------------------------------------------------------------

    def process(self, raw_text: str, existing_hashes: list[str] = None,
                platform: str = "", metadata: dict | None = None) -> dict:
        """Run full cleaning pipeline on a single text.

        Args:
            raw_text: 原始内容文本
            existing_hashes: 已有 SimHash 列表用于去重
            platform: 来源平台 (douyin/xiaohongshu/weibo/tieba/zhihu/telegram)
            metadata: 平台元数据 (hashtags, play_count, tags, etc.)

        Returns dict with keys: text, simhash, is_duplicate, is_noise,
            noise_reason, noise_score, priority, has_entity, risk_relevant,
            discard_reason, should_discard,
            has_emoji, emoji_translated.
        """
        existing_hashes = existing_hashes or []
        metadata = metadata or {}

        # Step 0: Emoji translation (v0.8)
        has_emoji = False
        emoji_translated = ""
        enriched = self._translate_emojis(raw_text)
        if enriched[1]:  # has_emoji
            has_emoji = True
            emoji_translated = enriched[2]
            # 用翻译后的文本替代原文本（保留原始 emoji + 添加 [emoji: 含义]）
            raw_text = emoji_translated if emoji_translated else raw_text

        # Step 0.5: Metadata enrichment (v0.8)
        raw_text = self._enrich_metadata(raw_text, metadata, platform)

        # Step 1: Normalize
        clean = self.normalize(raw_text)

        # Step 2: SimHash
        sh = self.compute_simhash(clean)
        dup = self.is_duplicate(sh, existing_hashes)

        # Step 3: Platform-aware noise filter
        noise, noise_reason, noise_score = self.is_noise(clean, platform, metadata)

        # Step 4: Priority
        priority = self.mark_priority(clean)

        # Step 5: Entity detection
        has_entity = self.has_entities(clean)

        # Step 6: Risk relevance
        relevant, risk_reason = self.is_risk_relevant(clean, priority)

        # 丢弃条件: 重复 or 硬噪声(noise_score >= 1.0) or 无风险价值
        discard_reasons = []
        if dup:
            discard_reasons.append("duplicate")
        if noise and noise_score >= 1.0:
            discard_reasons.append(f"noise:{noise_reason}")
        if not relevant:
            discard_reasons.append(f"low_risk:{risk_reason}")

        return {
            "text": clean,
            "simhash": sh,
            "is_duplicate": dup,
            "is_noise": noise,
            "noise_reason": noise_reason,
            "noise_score": noise_score,
            "priority": priority,
            "has_entity": has_entity,
            "risk_relevant": relevant,
            "risk_reason": risk_reason,
            "discard_reason": "; ".join(discard_reasons) if discard_reasons else "",
            "should_discard": dup or (noise and noise_score >= 1.0) or not relevant,
            "has_emoji": has_emoji,
            "emoji_translated": emoji_translated,
        }
