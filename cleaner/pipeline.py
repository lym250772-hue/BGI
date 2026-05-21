"""Data cleaning pipeline: normalize, deduplicate with SimHash, filter noise, mark high-risk."""
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


class CleaningPipeline:
    """Four-step cleaning pipeline. All steps are zero-LLM."""

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
        # convert hex to int, then XOR
        x = int(a, 16) ^ int(b, 16)
        return x.bit_count()

    def is_duplicate(self, new_hash: str, existing_hashes: list[str]) -> bool:
        for h in existing_hashes:
            if self.hamming_distance(new_hash, h) <= settings.simhash_threshold:
                return True
        return False

    # ------------------------------------------------------------------
    # Step 3: Noise filter
    # ------------------------------------------------------------------

    # Token-level junk (discard these entirely)
    NOISE_KEYWORDS = [
        "广告", "推广", "兼职刷单", "招代理", "微商",
        "加微信", "免费领取", "扫码关注", "点击链接",
    ]

    # Low-value patterns — flag as potential noise, not discard
    LOW_VALUE_PATTERNS = [
        (re.compile(r"^[^\\u4e00-\\u9fff]{0,5}$"), "no_chinese_short"),  # very short, no Chinese
    ]

    @classmethod
    def is_noise(cls, text: str) -> tuple[bool, str]:
        """Return (is_noise, reason)."""
        # completely empty after normalization
        if not text or len(text) < 3:
            return True, "too_short"

        # check low-value patterns
        for pattern, reason in cls.LOW_VALUE_PATTERNS:
            if pattern.match(text):
                return True, reason

        return False, ""

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
    # Main pipeline entry
    # ------------------------------------------------------------------

    def process(self, raw_text: str, existing_hashes: list[str] = None) -> dict:
        """Run full cleaning pipeline on a single text.

        Returns dict with keys: text, simhash, is_duplicate, is_noise,
        noise_reason, priority, should_discard.
        """
        existing_hashes = existing_hashes or []

        # Step 1
        clean = self.normalize(raw_text)

        # Step 2
        sh = self.compute_simhash(clean)
        dup = self.is_duplicate(sh, existing_hashes)

        # Step 3
        noise, reason = self.is_noise(clean)

        # Step 4
        priority = self.mark_priority(clean)

        return {
            "text": clean,
            "simhash": sh,
            "is_duplicate": dup,
            "is_noise": noise,
            "noise_reason": reason,
            "priority": priority,
            "should_discard": dup or noise,
        }
