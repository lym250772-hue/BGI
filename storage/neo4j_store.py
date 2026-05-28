"""Neo4j knowledge graph layer for entity relationship discovery.

Refined schema (v0.4):
  Nodes:  Intel, Account, Tool, Contact, Link
  Edges:  MENTIONS, PROMOTES, USES_CONTACT, CO_OCCURS

Gang detection via shared-contact pattern:
  (Account A)-[:USES_CONTACT]->(Contact X)<-[:USES_CONTACT]-(Account B)
  → (Account A)-[:CO_OCCURS]-(Account B)
"""

from neo4j import GraphDatabase
from loguru import logger
from config.settings import settings

# Entity type → refined node label mapping
_TYPE_TO_LABEL = {
    "wechat":    "Account",
    "qq":        "Account",
    "alipay":    "Account",
    "phone":     "Contact",
    "email":     "Contact",
    "url":       "Link",
    "domain":    "Link",
    "ip":        "Link",
    "bank_card": "Contact",
    "tool":      "Tool",
    "slang":     "Contact",
}

# Entity type → relationship type mapping
_TYPE_TO_REL = {
    "wechat":    "MENTIONS",
    "qq":        "MENTIONS",
    "alipay":    "MENTIONS",
    "phone":     "MENTIONS",
    "email":     "MENTIONS",
    "url":       "PROMOTES",
    "domain":    "PROMOTES",
    "ip":        "PROMOTES",
    "bank_card": "MENTIONS",
    "tool":      "PROMOTES",
    "slang":     "MENTIONS",
}


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
            # Legacy Entity constraints (backward compat)
            "CREATE CONSTRAINT IF NOT EXISTS FOR (e:Entity) REQUIRE e.uuid IS UNIQUE",
            "CREATE CONSTRAINT IF NOT EXISTS FOR (i:Intel) REQUIRE i.raw_id IS UNIQUE",
            "CREATE INDEX IF NOT EXISTS FOR (e:Entity) ON (e.type)",
            "CREATE INDEX IF NOT EXISTS FOR (e:Entity) ON (e.value)",
            # Refined schema constraints
            "CREATE CONSTRAINT IF NOT EXISTS FOR (a:Account) REQUIRE a.value IS UNIQUE",
            "CREATE CONSTRAINT IF NOT EXISTS FOR (t:Tool) REQUIRE t.value IS UNIQUE",
            "CREATE CONSTRAINT IF NOT EXISTS FOR (c:Contact) REQUIRE c.value IS UNIQUE",
            "CREATE CONSTRAINT IF NOT EXISTS FOR (l:Link) REQUIRE l.value IS UNIQUE",
            # Indexes for refined labels
            "CREATE INDEX IF NOT EXISTS FOR (a:Account) ON (a.type)",
            "CREATE INDEX IF NOT EXISTS FOR (c:Contact) ON (c.type)",
            "CREATE INDEX IF NOT EXISTS FOR (l:Link) ON (l.type)",
        ]
        with self.driver.session() as sess:
            for q in queries:
                try:
                    sess.run(q)
                except Exception as ex:
                    logger.warning(f"Neo4j constraint: {ex}")
        logger.info("Neo4j constraints initialized (legacy + refined schema)")

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

    # ──────────────────────────────────────────────────────────────────────
    # Refined schema methods (v0.4) — concrete node labels + relationships
    # ──────────────────────────────────────────────────────────────────────

    def _resolve_label(self, entity_type: str) -> str:
        return _TYPE_TO_LABEL.get(entity_type, "Contact")

    def _resolve_relationship(self, entity_type: str) -> str:
        return _TYPE_TO_REL.get(entity_type, "MENTIONS")

    def upsert_entity_refined(self, entity_type: str, value: str):
        """Merge entity as a refined node label (Account/Tool/Contact/Link)."""
        label = self._resolve_label(entity_type)
        with self.driver.session() as sess:
            sess.run(
                f"""
                MERGE (e:{label} {{value: $value}})
                SET e.type = $type, e.uuid = $uuid
                """,
                value=value, type=entity_type,
                uuid=f"{entity_type}:{value}",
            )
            # Also maintain legacy Entity node for backward compat
            sess.run(
                """
                MERGE (e:Entity {uuid: $uuid})
                SET e.type = $type, e.value = $value
                """,
                uuid=f"{entity_type}:{value}",
                type=entity_type, value=value,
            )

    def link_entity_to_intel_refined(self, entity_type: str, value: str,
                                     raw_data_id: int):
        """Create typed relationship (MENTIONS/PROMOTES) from Intel to entity."""
        label = self._resolve_label(entity_type)
        rel = self._resolve_relationship(entity_type)
        with self.driver.session() as sess:
            sess.run(
                f"""
                MATCH (i:Intel {{raw_id: $raw_id}})
                MATCH (e:{label} {{value: $value}})
                MERGE (i)-[:{rel}]->(e)
                """,
                raw_id=raw_data_id, value=value,
            )
            # Also maintain legacy EXTRACTED_FROM for backward compat
            sess.run(
                """
                MATCH (i:Intel {raw_id: $raw_id})
                MATCH (e:Entity {uuid: $uuid})
                MERGE (e)-[:EXTRACTED_FROM]->(i)
                """,
                raw_id=raw_data_id,
                uuid=f"{entity_type}:{value}",
            )

    def link_co_occurrence_refined(self, type_a: str, val_a: str,
                                   type_b: str, val_b: str, raw_data_id: int):
        """Create CO_OCCURS edge between co-mentioned entities."""
        label_a = self._resolve_label(type_a)
        label_b = self._resolve_label(type_b)
        with self.driver.session() as sess:
            sess.run(
                f"""
                MATCH (a:{label_a} {{value: $val_a}})
                MATCH (b:{label_b} {{value: $val_b}})
                MERGE (a)-[:CO_OCCURS {{raw_id: $raw_id}}]->(b)
                """,
                val_a=val_a, val_b=val_b, raw_id=raw_data_id,
            )

    def discover_gangs(self):
        """Find Accounts sharing the same Contact → create CO_OCCURS edges.

        This is the core gang-detection query: when two different Accounts
        use the same Contact (phone/email/bank_card), they are likely
        operated by the same group.
        """
        with self.driver.session() as sess:
            result = sess.run("""
                MATCH (c:Contact)
                MATCH (a1:Account)-[:MENTIONS]->()<-[:MENTIONS]-(i:Intel)
                MATCH (i)-[:MENTIONS]->(c)
                MATCH (a2:Account)-[:MENTIONS]->()<-[:MENTIONS]-(i2:Intel)
                MATCH (i2)-[:MENTIONS]->(c)
                WHERE a1.value < a2.value
                WITH a1, a2, c, COUNT(DISTINCT i) + COUNT(DISTINCT i2) AS shared
                MERGE (a1)-[:CO_OCCURS {reason: 'SHARED_CONTACT', contact: c.value}]->(a2)
                RETURN a1.value, a2.value, c.value, shared
                LIMIT 100
            """)
            return [dict(r) for r in result]

    def get_gang_members(self, min_shared: int = 2) -> list[dict]:
        """Return groups of Accounts linked by shared Contacts (potential gangs)."""
        with self.driver.session() as sess:
            result = sess.run(
                """
                MATCH (a1:Account)-[r:CO_OCCURS]->(a2:Account)
                WHERE r.reason = 'SHARED_CONTACT'
                RETURN a1.value AS account_a, a2.value AS account_b,
                       r.contact AS shared_contact
                LIMIT 50
                """
            )
            return [dict(r) for r in result]

    def get_refined_graph(self, search: str = "", limit: int = 50) -> tuple:
        """Return (nodes, edges) for pyvis visualization with refined labels."""
        nodes, edges = [], []
        seen = set()

        with self.driver.session() as sess:
            if search:
                result = sess.run(
                    """
                    MATCH (i:Intel)-[r]-(e)
                    WHERE e.value CONTAINS $q
                      AND (type(r) IN ['MENTIONS', 'PROMOTES', 'EXTRACTED_FROM'])
                    RETURN i, r, e, labels(e) AS elabels
                    LIMIT $limit
                    """,
                    q=search, limit=limit,
                )
            else:
                result = sess.run(
                    """
                    MATCH (i:Intel)-[r]-(e)
                    WHERE type(r) IN ['MENTIONS', 'PROMOTES', 'EXTRACTED_FROM']
                    RETURN i, r, e, labels(e) AS elabels
                    LIMIT $limit
                    """,
                    limit=limit,
                )

            for rec in result:
                i = rec["i"]
                e = rec["e"]
                r = rec["r"]
                elabels = rec["elabels"]

                iid = str(i.get("raw_id", ""))
                eid = e.get("value", "")

                if iid not in seen:
                    nodes.append({
                        "id": iid,
                        "label": (i.get("text") or i.get("content_preview", ""))[:25],
                        "group": "intel",
                    })
                    seen.add(iid)

                if eid not in seen:
                    # Use refined label for coloring
                    if "Account" in elabels:
                        group = "account"
                    elif "Tool" in elabels:
                        group = "tool"
                    elif "Link" in elabels:
                        group = "link"
                    elif "Contact" in elabels:
                        group = "contact"
                    else:
                        group = e.get("type", "entity")

                    nodes.append({
                        "id": eid,
                        "label": f"{e.get('type', '')}:{eid}",
                        "group": group,
                    })
                    seen.add(eid)

                edges.append({
                    "from": iid,
                    "to": eid,
                    "label": r.type,
                })

        return nodes, edges


neo4j = Neo4jStore()
