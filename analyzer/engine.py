"""Analysis engine — classifies, extracts entities, syncs to all stores.

Includes LLM degradation with tenacity exponential backoff retry and
graceful fallback to L1 (regex) + L2 (local model) when LLM fails.
"""

import hashlib
import json
from loguru import logger

from analyzer.classifier import classifier as _classifier
from analyzer.entity_extractor import EntityExtractor
from schema import Priority


def _mysql():
    from storage.mysql_store import mysql as m
    return m


def _neo4j():
    from storage.neo4j_store import neo4j as n
    return n


def _milvus():
    from storage.milvus_store import milvus as v
    return v


# ── LLM retry helper ─────────────────────────────────────────────────────────

def _tenacity_available() -> bool:
    try:
        import tenacity
        return True
    except ImportError:
        return False


def _with_retry(func, max_attempts: int = 3, base_delay: float = 2.0):
    """Wrap a callable with exponential backoff retry if tenacity is installed.

    On failure, sleeps base_delay * (2 ** (attempt-1)) seconds before retry.
    If tenacity is not installed, calls the function directly (no retry).
    """
    if _tenacity_available():
        import tenacity
        return tenacity.retry(
            stop=tenacity.stop_after_attempt(max_attempts),
            wait=tenacity.wait_exponential(multiplier=base_delay, min=1, max=30),
            retry=tenacity.retry_if_exception_type(Exception),
            reraise=True,
        )(func)
    else:
        return func


# ── Engine ───────────────────────────────────────────────────────────────────

class AnalysisEngine:
    """Full analysis pipeline with LLM degradation and graceful fallback."""

    DEGRADED_METHOD = "degraded"

    def __init__(self):
        self.entity_extractor = EntityExtractor()
        self._embed_fn = None
        self._llm_failure_count = 0
        self._circuit_open = False
        self._circuit_threshold = 5  # open circuit after N consecutive LLM failures

    def load_embedding_model(self):
        if self._embed_fn is not None:
            return
        from sentence_transformers import SentenceTransformer
        from config.settings import settings
        model = SentenceTransformer(settings.embedding_model_name)
        self._embed_fn = lambda text: model.encode(text).tolist()
        logger.info("Embedding model loaded")

    # ── Public API ────────────────────────────────────────────────────────

    def run(self, raw_data_id: int, text: str, platform: str):
        """Run full analysis with LLM degradation support.

        If the circuit breaker is open (consecutive LLM failures exceed
        threshold), classification falls back to L1+L2 only and marks
        results as [Degraded/降级运行].
        """
        # 1. Classify (with degradation)
        cls_result = self._classify_with_degradation(text)

        # 2. Extract entities (with degradation)
        self.load_embedding_model()
        entities = self._extract_with_degradation(text, cls_result["intent_label"])

        # 3. Persist to MySQL
        is_high = 1 if cls_result.get("intent_label") in ("诈骗", "引流") else 0
        _mysql().insert_analysis({
            "raw_data_id": raw_data_id,
            "intent_label": cls_result["intent_label"],
            "sub_label": cls_result["sub_label"],
            "confidence": cls_result["confidence"],
            "classification_method": cls_result["method"],
            "is_high_risk": is_high,
        })

        saved_entities = []
        for ent in entities:
            _mysql().insert_entity({
                "raw_data_id": raw_data_id,
                "entity_type": ent["entity_type"].value,
                "entity_value": ent["entity_value"],
                "extraction_method": ent.get("extraction_method", cls_result.get("method", "degraded")),
                "context": ent.get("context", ""),
                "metadata": _json_dumps(ent.get("metadata", {})),
            })
            saved_entities.append(ent)

        logger.info(
            f"[{raw_data_id}] Classified: {cls_result['intent_label']}/"
            f"{cls_result['sub_label']} conf={cls_result['confidence']:.2f}"
            f" via {cls_result['method']} | Entities: {len(entities)}"
        )

        # 4. Sync to Neo4j
        self._sync_neo4j(raw_data_id, platform, text, saved_entities)

        # 5. Embed → Milvus
        try:
            vec = self._embed_fn(text)
            text_hash = hashlib.md5(text.encode()).hexdigest()
            _milvus().insert_intel(raw_data_id, text_hash, vec)
        except Exception as exc:
            logger.warning(f"Milvus insert failed [{raw_data_id}]: {exc}")

        return cls_result, entities

    # ── Degradation-aware classification ──────────────────────────────────

    def _classify_with_degradation(self, text: str) -> dict:
        """Classify text. If LLM fails, fall back to L1+L2 only."""
        if self._circuit_open:
            logger.warning("Circuit breaker OPEN — using L1+L2 fallback")
            result = _classifier.classify(text, skip_llm=True)
            result["method"] = self.DEGRADED_METHOD
            return result

        try:
            classify_fn = _with_retry(
                lambda: _classifier.classify(text, skip_llm=False),
                max_attempts=3,
                base_delay=2.0,
            )
            result = classify_fn()
            self._llm_failure_count = 0  # reset on success
            return result
        except Exception as exc:
            self._llm_failure_count += 1
            logger.error(
                f"LLM classification failed (consecutive failures: "
                f"{self._llm_failure_count}/{self._circuit_threshold}): {exc}"
            )
            if self._llm_failure_count >= self._circuit_threshold:
                self._circuit_open = True
                logger.critical(
                    "CIRCUIT BREAKER OPENED — all subsequent requests "
                    "will use L1+L2 fallback until restart"
                )
            # Fall back
            result = _classifier.classify(text, skip_llm=True)
            result["method"] = self.DEGRADED_METHOD
            return result

    def _extract_with_degradation(self, text: str, intent_label: str) -> list[dict]:
        """Extract entities. If LLM extraction fails, use L1+L2 only."""
        try:
            extract_fn = _with_retry(
                lambda: self.entity_extractor.extract(
                    text,
                    embed_fn=self._embed_fn,
                    intent_label=intent_label,
                ),
                max_attempts=2,
                base_delay=1.5,
            )
            return extract_fn()
        except Exception as exc:
            logger.warning(f"LLM entity extraction failed, using L1+L2: {exc}")
            return self.entity_extractor.extract_l1_l2_only(
                text, embed_fn=self._embed_fn, intent_label=intent_label
            )

    # ── Neo4j sync ────────────────────────────────────────────────────────

    def _sync_neo4j(self, raw_data_id: int, platform: str, text: str,
                    entities: list[dict]):
        """Push entities and relationships to Neo4j with refined schema."""
        try:
            neo = _neo4j()
            neo.upsert_intel(raw_data_id, platform, text[:200])

            for ent in entities:
                etype = ent["entity_type"].value
                evalue = ent["entity_value"]
                neo.upsert_entity_refined(etype, evalue)
                neo.link_entity_to_intel_refined(etype, evalue, raw_data_id)

            # Co-occurrence for gang detection
            for i in range(len(entities)):
                for j in range(i + 1, len(entities)):
                    neo.link_co_occurrence_refined(
                        entities[i]["entity_type"].value,
                        entities[i]["entity_value"],
                        entities[j]["entity_type"].value,
                        entities[j]["entity_value"],
                        raw_data_id,
                    )

            # Discover shared-contact gangs
            neo.discover_gangs()

        except Exception as exc:
            logger.error(f"Neo4j sync failed [{raw_data_id}]: {exc}")

    # ── Health ────────────────────────────────────────────────────────────

    @property
    def is_degraded(self) -> bool:
        return self._circuit_open

    def reset_circuit(self):
        """Reset the circuit breaker (e.g., after API key rotation)."""
        self._circuit_open = False
        self._llm_failure_count = 0
        logger.info("Circuit breaker reset")


def _json_dumps(obj) -> str:
    def default(o):
        if hasattr(o, "value"):
            return o.value
        return str(o)
    return json.dumps(obj, ensure_ascii=False, default=default)


# Singleton
engine = AnalysisEngine()
