"""Neo4j knowledge graph layer for entity relationship discovery."""
from neo4j import GraphDatabase
from loguru import logger
from config.settings import settings


class Neo4jStore:
    """Manages entity knowledge graph in Neo4j."""

    def __init__(self):
        self.driver = GraphDatabase.driver(
            settings.neo4j_uri,
            auth=(settings.neo4j_user, settings.neo4j_password),
        )

    def close(self):
        self.driver.close()

    # ------------------------------------------------------------------
    # Init
    # ------------------------------------------------------------------

    def init_constraints(self):
        queries = [
            "CREATE CONSTRAINT IF NOT EXISTS FOR (e:Entity) REQUIRE e.uuid IS UNIQUE",
            "CREATE CONSTRAINT IF NOT EXISTS FOR (i:Intel) REQUIRE i.raw_id IS UNIQUE",
            "CREATE INDEX IF NOT EXISTS FOR (e:Entity) ON (e.type)",
            "CREATE INDEX IF NOT EXISTS FOR (e:Entity) ON (e.value)",
        ]
        with self.driver.session() as sess:
            for q in queries:
                try:
                    sess.run(q)
                except Exception as ex:
                    logger.warning(f"Neo4j constraint: {ex}")
        logger.info("Neo4j constraints initialized")

    # ------------------------------------------------------------------
    # Node creation / merge
    # ------------------------------------------------------------------

    def upsert_entity(self, entity_type: str, value: str, first_seen: str = None,
                      source_count: int = 1):
        """Merge an entity node. Each entity has a deterministic uuid = type:value."""
        uuid = f"{entity_type}:{value}"
        with self.driver.session() as sess:
            sess.run("""
                MERGE (e:Entity {uuid: $uuid})
                SET e.type = $type,
                    e.value = $value,
                    e.first_seen = COALESCE(e.first_seen, $first_seen),
                    e.source_count = COALESCE(e.source_count, 0) + $source_count
            """, uuid=uuid, type=entity_type, value=value,
               first_seen=first_seen, source_count=source_count)

    def upsert_intel(self, raw_data_id: int, platform: str, content_preview: str,
                     collected_at: str = None):
        with self.driver.session() as sess:
            sess.run("""
                MERGE (i:Intel {raw_id: $raw_id})
                SET i.platform = $platform,
                    i.content_preview = $content_preview,
                    i.collected_at = $collected_at
            """, raw_id=raw_data_id, platform=platform,
               content_preview=content_preview[:200], collected_at=collected_at)

    # ------------------------------------------------------------------
    # Relationships
    # ------------------------------------------------------------------

    def link_entity_to_intel(self, entity_type: str, value: str, raw_data_id: int):
        """Create [:EXTRACTED_FROM] edge."""
        uuid = f"{entity_type}:{value}"
        with self.driver.session() as sess:
            sess.run("""
                MATCH (e:Entity {uuid: $uuid})
                MATCH (i:Intel {raw_id: $raw_id})
                MERGE (e)-[:EXTRACTED_FROM]->(i)
            """, uuid=uuid, raw_id=raw_data_id)

    def link_co_occurrence(self, type_a: str, val_a: str, type_b: str, val_b: str,
                           raw_data_id: int):
        """Create [:CO_OCCURS] edge between two entities found in the same intel."""
        uuid_a = f"{type_a}:{val_a}"
        uuid_b = f"{type_b}:{val_b}"
        with self.driver.session() as sess:
            sess.run("""
                MATCH (a:Entity {uuid: $uuid_a})
                MATCH (b:Entity {uuid: $uuid_b})
                MERGE (a)-[:CO_OCCURS {raw_id: $raw_id}]->(b)
            """, uuid_a=uuid_a, uuid_b=uuid_b, raw_id=raw_data_id)

    # ------------------------------------------------------------------
    # Discovery queries (used in dashboard)
    # ------------------------------------------------------------------

    def find_entity_neighborhood(self, entity_type: str, value: str, depth: int = 2):
        """Return the subgraph around an entity up to `depth` hops."""
        uuid = f"{entity_type}:{value}"
        with self.driver.session() as sess:
            result = sess.run(f"""
                MATCH (e:Entity {{uuid: $uuid}})-[r*1..{depth}]-(related)
                RETURN e, r, related LIMIT 50
            """, uuid=uuid)
            return [{"nodes": r["e"], "rels": r["r"], "related": r["related"]}
                    for r in result]

    def find_shared_entity_gangs(self, min_shared: int = 3):
        """Find entities that share at least `min_shared` other entities (potential gangs)."""
        with self.driver.session() as sess:
            result = sess.run("""
                MATCH (a:Entity)-[:CO_OCCURS]->(shared)<-[:CO_OCCURS]-(b:Entity)
                WHERE a.uuid < b.uuid
                WITH a, b, COUNT(shared) AS shared_count
                WHERE shared_count >= $min_shared
                RETURN a, b, shared_count
                ORDER BY shared_count DESC LIMIT 50
            """, min_shared=min_shared)
            return [dict(r) for r in result]

    def shortest_path(self, type_a: str, val_a: str, type_b: str, val_b: str):
        """Find shortest path between two entities."""
        uuid_a = f"{type_a}:{val_a}"
        uuid_b = f"{type_b}:{val_b}"
        with self.driver.session() as sess:
            result = sess.run("""
                MATCH path = shortestPath(
                    (a:Entity {uuid: $uuid_a})-[*..6]-(b:Entity {uuid: $uuid_b})
                )
                RETURN path
            """, uuid_a=uuid_a, uuid_b=uuid_b)
            rec = result.single()
            return rec["path"] if rec else None


neo4j = Neo4jStore()
