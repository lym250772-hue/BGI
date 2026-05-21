"""Milvus vector store for semantic similarity search (slang variants, similar intel)."""
from pymilvus import connections, Collection, CollectionSchema, FieldSchema, DataType, utility
from loguru import logger
from config.settings import settings


class MilvusStore:
    """Manages embedding collections for slang and intel semantic search."""

    def __init__(self):
        connections.connect(
            alias="default",
            host=settings.milvus_host,
            port=settings.milvus_port,
        )

    # ------------------------------------------------------------------
    # Init collections
    # ------------------------------------------------------------------

    def init_collections(self):
        self._init_slang_collection()
        self._init_intel_collection()
        logger.info("Milvus collections initialized")

    def _init_slang_collection(self):
        name = "slang_embeddings"
        if utility.has_collection(name):
            self.slang_col = Collection(name)
            return
        fields = [
            FieldSchema(name="id", dtype=DataType.INT64, is_primary=True, auto_id=True),
            FieldSchema(name="slang", dtype=DataType.VARCHAR, max_length=128),
            FieldSchema(name="meaning", dtype=DataType.VARCHAR, max_length=512),
            FieldSchema(name="category", dtype=DataType.VARCHAR, max_length=64),
            FieldSchema(name="embedding", dtype=DataType.FLOAT_VECTOR, dim=settings.milvus_dim),
        ]
        schema = CollectionSchema(fields, description="Slang dictionary embeddings")
        self.slang_col = Collection(name, schema)
        self.slang_col.create_index(
            field_name="embedding",
            index_params={"metric_type": "COSINE", "index_type": "IVF_FLAT", "params": {"nlist": 128}},
        )

    def _init_intel_collection(self):
        name = "intel_embeddings"
        if utility.has_collection(name):
            self.intel_col = Collection(name)
            return
        fields = [
            FieldSchema(name="id", dtype=DataType.INT64, is_primary=True, auto_id=True),
            FieldSchema(name="raw_data_id", dtype=DataType.INT64),
            FieldSchema(name="text_hash", dtype=DataType.VARCHAR, max_length=64),
            FieldSchema(name="embedding", dtype=DataType.FLOAT_VECTOR, dim=settings.milvus_dim),
        ]
        schema = CollectionSchema(fields, description="Intel text embeddings")
        self.intel_col = Collection(name, schema)
        self.intel_col.create_index(
            field_name="embedding",
            index_params={"metric_type": "COSINE", "index_type": "IVF_FLAT", "params": {"nlist": 128}},
        )

    # ------------------------------------------------------------------
    # Slang operations
    # ------------------------------------------------------------------

    def insert_slang(self, slang: str, meaning: str, embedding: list[float], category: str = ""):
        self.slang_col.insert([[slang], [meaning], [category], [embedding]])

    def search_similar_slang(self, embedding: list[float], top_k: int = 5):
        self.slang_col.load()
        results = self.slang_col.search(
            data=[embedding],
            anns_field="embedding",
            param={"metric_type": "COSINE", "params": {"nprobe": 10}},
            limit=top_k,
            output_fields=["slang", "meaning", "category"],
        )
        hits = []
        for hit in results[0]:
            hits.append({
                "slang": hit.entity.get("slang"),
                "meaning": hit.entity.get("meaning"),
                "category": hit.entity.get("category"),
                "score": hit.distance,
            })
        return hits

    # ------------------------------------------------------------------
    # Intel operations
    # ------------------------------------------------------------------

    def insert_intel(self, raw_data_id: int, text_hash: str, embedding: list[float]):
        self.intel_col.insert([[raw_data_id], [text_hash], [embedding]])

    def search_similar_intel(self, embedding: list[float], top_k: int = 10):
        self.intel_col.load()
        results = self.intel_col.search(
            data=[embedding],
            anns_field="embedding",
            param={"metric_type": "COSINE", "params": {"nprobe": 10}},
            limit=top_k,
            output_fields=["raw_data_id"],
        )
        return [
            {"raw_data_id": hit.entity.get("raw_data_id"), "score": hit.distance}
            for hit in results[0]
        ]

    # ------------------------------------------------------------------
    # Bulk
    # ------------------------------------------------------------------

    def insert_slang_batch(self, items: list[tuple[str, str, list[float], str]]):
        """items: list of (slang, meaning, embedding, category)."""
        if not items:
            return
        slangs, meanings, cats, embs = [], [], [], []
        for s, m, e, c in items:
            slangs.append(s)
            meanings.append(m)
            embs.append(e)
            cats.append(c)
        self.slang_col.insert([slangs, meanings, cats, embs])

    def flush(self):
        self.slang_col.flush()
        self.intel_col.flush()


milvus = MilvusStore()
