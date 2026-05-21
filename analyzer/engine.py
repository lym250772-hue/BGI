"""Analysis engine that orchestrates classification + entity extraction + storage."""
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


class AnalysisEngine:
    """Full analysis pipeline: classify → extract → store."""

    def __init__(self):
        self.entity_extractor = EntityExtractor()
        self._embed_fn = None

    def load_embedding_model(self):
        """Lazy-load the sentence-transformers model."""
        if self._embed_fn is not None:
            return
        from sentence_transformers import SentenceTransformer
        from config.settings import settings
        model = SentenceTransformer(settings.embedding_model_name)
        self._embed_fn = lambda text: model.encode(text).tolist()
        logger.info("Embedding model loaded")

    def run(self, raw_data_id: int, text: str, platform: str):
        """Run full analysis on a single cleaned intel item.

        Steps:
        1. Classify intent
        2. Extract entities
        3. Save to MySQL
        4. Sync to Neo4j knowledge graph
        5. Embed and store in Milvus
        """
        # --- Classify ---
        cls_result = _classifier.classify(text)
        is_high = 1 if cls_result["intent_label"] in ("诈骗", "引流") else 0
        _mysql().insert_analysis({
            "raw_data_id": raw_data_id,
            "intent_label": cls_result["intent_label"],
            "sub_label": cls_result["sub_label"],
            "confidence": cls_result["confidence"],
            "classification_method": cls_result["method"].value,
            "is_high_risk": is_high,
        })
        logger.info(f"[{raw_data_id}] Classified: {cls_result['intent_label']}/{cls_result['sub_label']} "
                    f"conf={cls_result['confidence']:.2f} via {cls_result['method'].value}")

        # --- Extract entities ---
        self.load_embedding_model()
        entities = self.entity_extractor.extract(
            text,
            embed_fn=self._embed_fn,
            intent_label=cls_result["intent_label"],
        )
        saved_entities = []
        for ent in entities:
            _mysql().insert_entity({
                "raw_data_id": raw_data_id,
                "entity_type": ent["entity_type"].value,
                "entity_value": ent["entity_value"],
                "extraction_method": ent["extraction_method"].value,
                "context": ent.get("context", ""),
                "metadata": json_dumps_safe(ent.get("metadata", {})),
            })
            saved_entities.append(ent)
        logger.info(f"[{raw_data_id}] Extracted {len(entities)} entities")

        # --- Sync to Neo4j ---
        self._sync_neo4j(raw_data_id, platform, text, saved_entities)

        # --- Embed & store in Milvus ---
        try:
            vec = self._embed_fn(text)
            import hashlib
            text_hash = hashlib.md5(text.encode()).hexdigest()
            _milvus().insert_intel(raw_data_id, text_hash, vec)
        except Exception as exc:
            logger.warning(f"Milvus insert failed: {exc}")

        return cls_result, entities

    def _sync_neo4j(self, raw_data_id: int, platform: str, text: str, entities: list[dict]):
        """Push entities and relationships to Neo4j."""
        try:
            _neo4j().upsert_intel(raw_data_id, platform, text[:200])
            for ent in entities:
                _neo4j().upsert_entity(
                    ent["entity_type"].value,
                    ent["entity_value"],
                )
                _neo4j().link_entity_to_intel(
                    ent["entity_type"].value,
                    ent["entity_value"],
                    raw_data_id,
                )
            # Create co-occurrence edges for entities in the same intel
            for i in range(len(entities)):
                for j in range(i + 1, len(entities)):
                    _neo4j().link_co_occurrence(
                        entities[i]["entity_type"].value,
                        entities[i]["entity_value"],
                        entities[j]["entity_type"].value,
                        entities[j]["entity_value"],
                        raw_data_id,
                    )
        except Exception as exc:
            logger.error(f"Neo4j sync failed: {exc}")


def json_dumps_safe(obj) -> str:
    import json
    def default(o):
        if hasattr(o, "value"):
            return o.value
        return str(o)
    return json.dumps(obj, ensure_ascii=False, default=default)


# Singleton
engine = AnalysisEngine()
