"""Graph Agent — Neo4j graph expansion and gang detection.

According to PROJECT_PLAN.md Step 10:
    "Not just looking at this single intel,
     but seeing if it connects to historical data."
"""

from loguru import logger


class GraphAgent:
    """Query Neo4j for entity relationships, expand connections, detect gangs."""

    def __init__(self):
        self._neo4j = None

    @property
    def neo4j(self):
        if self._neo4j is None:
            from storage.neo4j_store import neo4j
            self._neo4j = neo4j
        return self._neo4j

    # ------------------------------------------------------------------
    # Entity neighborhood expansion
    # ------------------------------------------------------------------

    def expand_entity(self, entity_type: str, entity_value: str,
                      depth: int = 2) -> dict:
        """Expand around an entity to find related intel, accounts, contacts.

        Returns:
            {
                "entity": {"type", "value"},
                "related_intel": [intel_ids],
                "related_accounts": [{"type", "value"}],
                "related_contacts": [{"type", "value"}],
                "related_links": [{"type", "value"}],
                "paths": [{"from", "to", "hops"}],
            }
        """
        try:
            result = self.neo4j.find_entity_neighborhood(
                entity_type, entity_value, depth
            )
            return self._format_expansion(entity_type, entity_value, result)
        except Exception as exc:
            logger.error(f"Graph expansion failed for {entity_type}:{entity_value}: {exc}")
            return {"entity": {"type": entity_type, "value": entity_value},
                    "error": str(exc)}

    @staticmethod
    def _format_expansion(entity_type: str, entity_value: str,
                          raw: list[dict]) -> dict:
        """Format raw Neo4j result into structured expansion data."""
        related_intel = set()
        related_accounts = set()
        related_contacts = set()
        related_links = set()
        related_tools = set()

        for record in raw:
            node = record.get("related", {})
            labels = node.get("labels", []) if isinstance(node, dict) else []
            # Handle Neo4j node dict format
            node_data = node if isinstance(node, dict) else {}

            if "Intel" in str(labels):
                rid = node_data.get("raw_id", "")
                if rid:
                    related_intel.add(str(rid))
            elif "Account" in str(labels):
                related_accounts.add((
                    node_data.get("type", ""),
                    node_data.get("value", ""),
                ))
            elif "Contact" in str(labels):
                related_contacts.add((
                    node_data.get("type", ""),
                    node_data.get("value", ""),
                ))
            elif "Link" in str(labels):
                related_links.add((
                    node_data.get("type", ""),
                    node_data.get("value", ""),
                ))
            elif "Tool" in str(labels):
                related_tools.add((
                    node_data.get("type", ""),
                    node_data.get("value", ""),
                ))

        return {
            "entity": {"type": entity_type, "value": entity_value},
            "related_intel": sorted(related_intel),
            "related_accounts": [{"type": t, "value": v} for t, v in related_accounts],
            "related_contacts": [{"type": t, "value": v} for t, v in related_contacts],
            "related_links": [{"type": t, "value": v} for t, v in related_links],
            "related_tools": [{"type": t, "value": v} for t, v in related_tools],
            "total_related": len(related_intel) + len(related_accounts) +
                             len(related_contacts) + len(related_links) + len(related_tools),
        }

    # ------------------------------------------------------------------
    # Gang detection
    # ------------------------------------------------------------------

    def detect_gangs(self) -> list[dict]:
        """Discover accounts sharing the same contact → potential gangs."""
        try:
            return self.neo4j.discover_gangs()
        except Exception as exc:
            logger.error(f"Gang detection failed: {exc}")
            return []

    def get_gang_members(self, min_shared: int = 2) -> list[dict]:
        """Return groups of accounts linked by shared contacts."""
        try:
            return self.neo4j.get_gang_members(min_shared)
        except Exception as exc:
            logger.error(f"Get gang members failed: {exc}")
            return []

    # ------------------------------------------------------------------
    # Batch: expand all entities from one intel
    # ------------------------------------------------------------------

    def expand_all_entities(self, entities: list[dict]) -> dict:
        """Expand each entity and aggregate results for gang clustering.

        Returns:
            {
                "is_gang_related": bool,
                "case_id": str,
                "cluster_id": str,
                "related_entities_count": int,
                "shared_contacts": [str],
                "expansions": [entity_expansion_results],
            }
        """
        expansions = []
        all_related = set()
        all_contacts = set()

        for ent in entities:
            etype = ent.get("entity_type", "")
            etype_str = etype.value if hasattr(etype, "value") else str(etype)
            evalue = ent.get("entity_value", "")

            # Only expand contacts and accounts (not features, slang)
            if etype_str in ("wechat", "qq", "phone", "url", "domain",
                             "bank_card", "alipay", "tool"):
                expansion = self.expand_entity(etype_str, evalue, depth=2)
                expansions.append(expansion)
                for c in expansion.get("related_contacts", []):
                    all_contacts.add(f"{c['type']}:{c['value']}")
                for a in expansion.get("related_accounts", []):
                    all_related.add(f"{a['type']}:{a['value']}")

        is_gang = len(all_related) >= 2
        cluster_id = ""
        case_id = ""

        if is_gang:
            # Generate cluster/case IDs
            import hashlib
            import datetime
            sorted_entities = sorted(all_related)
            cluster_hash = hashlib.md5(
                "|".join(sorted_entities).encode()
            ).hexdigest()[:12]
            cluster_id = f"CLUSTER_{cluster_hash}"
            today = datetime.datetime.now().strftime("%Y%m%d")
            case_id = f"CASE_{today}_{cluster_hash[:8]}"

        return {
            "is_gang_related": is_gang,
            "case_id": case_id,
            "cluster_id": cluster_id,
            "related_entities_count": len(all_related),
            "shared_contacts": list(all_contacts),
            "expansions": expansions,
        }


# ---------------------------------------------------------------------------
# Singleton
# ---------------------------------------------------------------------------

graph_agent = GraphAgent()
