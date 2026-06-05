"""Entity extraction: regex/dict → embedding → LLM cascade."""
import re
import json
from loguru import logger

from schema import EntityType, ExtractionMethod
from config.settings import settings

_milvus = None


def _get_milvus():
    global _milvus
    if _milvus is None:
        from storage.milvus_store import milvus as m
        _milvus = m
    return _milvus


class EntityExtractor:
    """Extract key entities from intel text using rule-first cascade."""

    # ------------------------------------------------------------------
    # L1: Regex patterns (zero cost, 100% precision)
    # ------------------------------------------------------------------

    REGEX_PATTERNS: dict[EntityType, re.Pattern] = {
        EntityType.PHONE: re.compile(r"1[3-9]\d{9}"),
        EntityType.WECHAT: re.compile(r"(?:微信|wx|vx|VX|薇信|微)[：:\s]*([a-zA-Z][a-zA-Z0-9_-]{4,19})"),
        EntityType.QQ: re.compile(r"(?:QQ|qq|扣扣)[：:\s]*(\d{5,11})"),
        EntityType.TELEGRAM: re.compile(r"(?:TG|Telegram|飞机|电报)[：:\s]*(@?[a-zA-Z][a-zA-Z0-9_]{4,31})"),
        EntityType.EMAIL: re.compile(r"\b[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}\b"),
        EntityType.URL: re.compile(r"https?://[^\s]+|t\.me/[^\s]+|t\.cn/[^\s]+"),
        EntityType.DOMAIN: re.compile(r"(?:[a-zA-Z0-9](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?\.)+[a-zA-Z]{2,}"),
        EntityType.IP: re.compile(r"(?:\d{1,3}\.){3}\d{1,3}"),
        EntityType.BANK_CARD: re.compile(r"\b(?:62|60|55|52|53|54|43|42|45|46|47|48|49)\d{14,18}\b"),
        EntityType.ALIPAY: re.compile(r"(?:支付宝|zfb)[：:\s]*([a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}|\d{11})"),
        EntityType.CRYPTO_WALLET: re.compile(r"\b(?:T[a-zA-Z0-9]{33}|0x[a-fA-F0-9]{40})\b"),
    }

    def extract_regex(self, text: str) -> list[dict]:
        """L1: Regex extraction. Returns list of entity dicts."""
        results = []
        for etype, pattern in self.REGEX_PATTERNS.items():
            for match in pattern.finditer(text):
                value = match.group(1) if match.lastindex else match.group(0)
                results.append({
                    "entity_type": etype,
                    "entity_value": value.strip(),
                    "extraction_method": ExtractionMethod.REGEX,
                    "context": text[max(0, match.start() - 20):match.end() + 20],
                })
        return results

    # ------------------------------------------------------------------
    # L2: Known slang dictionary (zero LLM cost)
    # ------------------------------------------------------------------

    # Entity types considered "high-value" — if enough of these are found by L1-L3,
    # the L4 LLM step can be skipped
    HIGH_VALUE_TYPES = {
        EntityType.WECHAT, EntityType.QQ, EntityType.PHONE, EntityType.URL,
        EntityType.DOMAIN, EntityType.BANK_CARD, EntityType.ALIPAY, EntityType.TELEGRAM,
        EntityType.EMAIL, EntityType.CRYPTO_WALLET, EntityType.SLANG, EntityType.TOOL,
    }

    def __init__(self):
        self._slang_dict: dict[str, str] = {}
        self._load_slang_from_db()

    def _load_slang_from_db(self):
        """Load known slang terms from MySQL dim_slang_dict."""
        try:
            from storage.mysql_store import mysql
            terms = mysql.list_slang("active")
            self._slang_dict = {t.get("term", ""): t.get("normalized_meaning", "") for t in terms}
            if self._slang_dict:
                logger.info(f"Loaded {len(self._slang_dict)} slang terms from dict")
        except Exception as exc:
            logger.warning(f"Slang dict load failed: {exc}")

    def refresh_slang_dict(self):
        """Manually refresh the slang dictionary from database."""
        self._slang_dict = {}
        self._load_slang_from_db()
        return len(self._slang_dict)

    def load_slang_dict(self, slang_dict: dict[str, str]):
        """Inject a slang dictionary, mainly for tests and offline demos."""
        self._slang_dict = dict(slang_dict or {})
        return len(self._slang_dict)

    def extract_dict(self, text: str) -> list[dict]:
        """L2: Exact-match known slang terms."""
        results = []
        for slang, meaning in self._slang_dict.items():
            if slang in text:
                results.append({
                    "entity_type": EntityType.SLANG,
                    "entity_value": slang,
                    "extraction_method": ExtractionMethod.DICT,
                    "context": meaning,
                    "metadata": {"meaning": meaning},
                })
        return results

    # ------------------------------------------------------------------
    # L3: Embedding-based slang variant detection (Milvus)
    # ------------------------------------------------------------------

    def detect_slang_variants(self, text: str, embed_fn) -> list[dict]:
        """L3: Split text into n-grams, embed each, search Milvus for similar slangs."""
        results = []
        # Split into 2~6 char windows
        words = self._extract_suspicious_ngrams(text)
        for word in set(words):
            # Skip if already matched by dict
            if word in self._slang_dict:
                continue
            try:
                vec = embed_fn(word)
                hits = _get_milvus().search_similar_slang(vec, top_k=3)
                for hit in hits:
                    if hit["score"] >= settings.slang_similarity_threshold:
                        results.append({
                            "entity_type": EntityType.SLANG,
                            "entity_value": word,
                            "extraction_method": ExtractionMethod.EMBEDDING,
                            "context": hit.get("meaning", ""),
                            "metadata": {
                                "similar_to": hit["slang"],
                                "similarity": hit["score"],
                                "candidate_meaning": hit.get("meaning", ""),
                            },
                        })
                        break  # best match only
            except Exception as exc:
                logger.debug(f"Embedding failed for '{word}': {exc}")
        return results

    @staticmethod
    def _extract_suspicious_ngrams(text: str) -> list[str]:
        """Extract candidate n-grams that could be slang (not plain common words)."""
        import jieba
        tokens = list(jieba.cut(text))
        candidates = []
        for t in tokens:
            t = t.strip()
            if len(t) >= 2 and len(t) <= 8:
                # Prefer tokens that look "special": mixed alnum, unusual chars
                candidates.append(t)
        # Also add character-level n-grams for short combos
        for i in range(len(text) - 1):
            for n in (2, 3, 4):
                if i + n <= len(text):
                    candidates.append(text[i:i + n])
        return candidates

    # ------------------------------------------------------------------
    # L4: LLM structured extraction (last resort, for complex entities)
    # ------------------------------------------------------------------

    def extract_llm(self, text: str, intent_label: str = "") -> dict:
        """L4: Use LLM for remaining entities (tools, features, complex patterns)."""
        prompt = f"""你是黑灰产情报分析专家。请从以下文本中提取关键实体。

文本：{text[:2000]}
已知意图：{intent_label}

请仅返回JSON格式：
{{
  "risk_tags": ["标签1"],
  "slang_candidates": ["疑似黑话1"],
  "accounts": [{{"type": "wechat/qq/phone", "value": "xxx"}}],
  "links": ["链接"],
  "contact": ["联系方式"],
  "features": ["特征"],
  "tools": ["工具/软件名"]
}}"""
        try:
            from openai import OpenAI
            client = OpenAI(api_key=settings.llm_api_key, base_url=settings.llm_api_base)
            resp = client.chat.completions.create(
                model=settings.llm_model,
                messages=[{"role": "user", "content": prompt}],
                temperature=0.1,
                max_tokens=500)
            return json.loads(resp.choices[0].message.content)
        except Exception as exc:
            logger.error(f"LLM entity extraction failed: {exc}")
            return {}

    # ------------------------------------------------------------------
    # Entry point
    # ------------------------------------------------------------------

    def extract(self, text: str, embed_fn=None, intent_label: str = "",
                classification_confidence: float = 0.0) -> list[dict]:
        """Run full extraction cascade. Returns list of entity dicts.

        Skips L4 LLM when L1-L3 have already found high-value entities with
        sufficient classification confidence (>= 0.8), saving cost and latency.
        """
        entities = []

        # L1: Regex
        entities.extend(self.extract_regex(text))

        # L2: Dict
        entities.extend(self.extract_dict(text))

        # L3: Embedding (if embed_fn provided)
        if embed_fn is not None:
            entities.extend(self.detect_slang_variants(text, embed_fn))

        # ── Decide: skip L4 LLM? ──
        pre_llm_types = set()
        for e in entities:
            et = e.get("entity_type", "")
            if hasattr(et, "value"):
                et = et.value
            pre_llm_types.add(et)

        high_value_hit = pre_llm_types & {
            "wechat", "qq", "phone", "url", "domain",
            "bank_card", "alipay", "email", "crypto_wallet", "slang", "tool",
        }
        skip_llm = (
            len(high_value_hit) >= 2
            and classification_confidence >= 0.8
        )

        if skip_llm:
            logger.info(
                f"LLM entity extraction skipped: {len(entities)} entities from L1-L3, "
                f"high-value types={high_value_hit}, confidence={classification_confidence:.2f}"
            )
            return entities

        # L4: LLM (structured JSON extraction for remaining)
        llm_result = self.extract_llm(text, intent_label)
        for tag in llm_result.get("risk_tags", []):
            entities.append({
                "entity_type": EntityType.FEATURE,
                "entity_value": tag,
                "extraction_method": ExtractionMethod.LLM,
            })
        for tool in llm_result.get("tools", []):
            entities.append({
                "entity_type": EntityType.TOOL,
                "entity_value": tool,
                "extraction_method": ExtractionMethod.LLM,
            })
        for link in llm_result.get("links", []):
            entities.append({
                "entity_type": EntityType.URL,
                "entity_value": link,
                "extraction_method": ExtractionMethod.LLM,
            })
        for acct in llm_result.get("accounts", []):
            raw_type = acct.get("type", "wechat")
            try:
                etype = EntityType(raw_type)
            except ValueError:
                etype = EntityType.WECHAT
            entities.append({
                "entity_type": etype,
                "entity_value": acct.get("value", ""),
                "extraction_method": ExtractionMethod.LLM,
            })
        # Slang candidates from LLM
        for slang in llm_result.get("slang_candidates", []):
            candidate = self._normalize_slang_candidate(slang, text)
            if not candidate:
                continue
            entities.append({
                "entity_type": EntityType.SLANG,
                "entity_value": candidate["term"],
                "extraction_method": ExtractionMethod.LLM,
                "confidence": candidate["confidence"],
                "context": candidate["evidence"],
                "metadata": {
                    "is_new_slang_candidate": True,
                    "candidate_meaning": candidate["suggested_meaning"],
                    "candidate_reason": candidate["reason"],
                },
            })

        return entities

    @staticmethod
    def _normalize_slang_candidate(candidate, text: str) -> dict | None:
        """Normalize LLM slang candidate output for both dict and string formats."""
        if isinstance(candidate, str):
            term = candidate.strip()
            suggested_meaning = ""
            reason = "LLM从上下文中识别出的疑似黑话"
            confidence = 0.6
            evidence = ""
        elif isinstance(candidate, dict):
            term = (
                candidate.get("term")
                or candidate.get("word")
                or candidate.get("slang")
                or candidate.get("value")
                or ""
            ).strip()
            suggested_meaning = (
                candidate.get("suggested_meaning")
                or candidate.get("meaning")
                or candidate.get("normalized_meaning")
                or ""
            )
            reason = candidate.get("reason") or "LLM从上下文中识别出的疑似黑话"
            confidence = candidate.get("confidence", 0.6)
            evidence = candidate.get("evidence") or ""
        else:
            return None

        if not term:
            return None
        if not evidence:
            idx = text.find(term)
            if idx >= 0:
                evidence = text[max(0, idx - 24): idx + len(term) + 24]
            else:
                evidence = text[:120]
        try:
            confidence = float(confidence)
        except (TypeError, ValueError):
            confidence = 0.6
        return {
            "term": term,
            "suggested_meaning": suggested_meaning or "待人工确认",
            "reason": reason,
            "confidence": max(0.0, min(confidence, 1.0)),
            "evidence": evidence,
        }

    def extract_l1_l2_only(self, text: str, embed_fn=None, intent_label: str = "") -> list[dict]:
        """Degraded extraction: L1 (regex) + L2 (dict) + L3 (embedding) only.

        Skips LLM entirely. Used when circuit breaker is open or LLM is unavailable.
        """
        entities = []
        entities.extend(self.extract_regex(text))
        entities.extend(self.extract_dict(text))
        if embed_fn is not None:
            entities.extend(self.detect_slang_variants(text, embed_fn))
        return entities
