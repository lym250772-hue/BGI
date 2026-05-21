"""Pure-Python SimHash fallback when simhash-py is not installed.

Simple 64-bit SimHash: tokenize → hash each token → weighted bitwise vote.
"""

import hashlib
import re


class SimHash:
    def __init__(self, text: str, bits: int = 64):
        self.bits = bits
        self.value = self._compute(text)

    def _tokenize(self, text: str) -> list[str]:
        """Split text into tokens (character bigrams work well for Chinese)."""
        # For mixed Chinese/Latin text, use word bigrams
        tokens = []
        # Chinese char bigrams
        chinese = re.findall(r"[一-鿿]", text)
        for i in range(len(chinese) - 1):
            tokens.append(chinese[i] + chinese[i + 1])
        # Latin/num word unigrams
        latin = re.findall(r"[a-zA-Z0-9]+", text)
        tokens.extend(latin)
        if not tokens:
            tokens = [text]  # fallback
        return tokens

    def _hash_token(self, token: str) -> int:
        """Hash a token to a 64-bit integer."""
        digest = hashlib.md5(token.encode("utf-8")).hexdigest()[:16]
        return int(digest, 16) & ((1 << self.bits) - 1)

    def _compute(self, text: str) -> int:
        tokens = self._tokenize(text)
        weights = [0] * self.bits  # bitwise weight vector

        for token in tokens:
            h = self._hash_token(token)
            for i in range(self.bits):
                if h & (1 << i):
                    weights[i] += 1
                else:
                    weights[i] -= 1

        value = 0
        for i in range(self.bits):
            if weights[i] > 0:
                value |= (1 << i)
        return value
