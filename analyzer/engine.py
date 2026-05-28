"""Analysis engine — classify, evidence, entities, score, report, sync.

Full pipeline matching PROJECT_PLAN.md steps 6-12:
    1. Classify (L1→L2→L3 cascade with LLM degradation)
    2. Extract entities (regex→dict→embedding→LLM cascade)
    3. Extract evidence spans (rule + entity-context + LLM explanation)
    4. Multi-factor risk scoring
    5. Generate structured report
    6. Persist to MySQL / Neo4j / Milvus
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
        self._circuit_threshold = 5

    def load_embedding_model(self):
        if self._embed_fn is not None:
            return
        from sentence_transformers import SentenceTransformer
        from config.settings import settings
        model = SentenceTransformer(settings.embedding_model_name)
        self._embed_fn = lambda text: model.encode(text).tolist()
        logger.info("Embedding model loaded")

    # ── Public API ────────────────────────────────────────────────────────

    def run(self, raw_data_id: int, text: str, platform: str,
            enable_graph_expand: bool = True,
            enable_report: bool = True) -> dict:
        """Run full analysis pipeline.

        Returns a dict matching the PROJECT_PLAN.md AnalyzeResponse format.
        """
        response = {
            "raw_id": raw_data_id,
            "clean_text": text,
            "risk_label": "",
            "risk_sub_label": "",
            "risk_score": 0.0,
            "risk_level": "normal",
            "evidence_spans": [],
            "entities": [],
            "slang_terms": [],
            "graph_result": {},
            "agent_summary": "",
            "disposal_advice": [],
        }

        # Step 1: Classify
        cls_result = self._classify_with_degradation(text)
        response["risk_label"] = (
            cls_result["intent_label"].value
            if hasattr(cls_result["intent_label"], "value")
            else str(cls_result["intent_label"])
        )
        response["risk_sub_label"] = cls_result.get("sub_label", "")

        # Step 2: Extract entities
        self.load_embedding_model()
        entities = self._extract_with_degradation(text, cls_result["intent_label"])
        # Deduplicate by (entity_type, entity_value)
        seen_entities = set()
        deduped = []
        for ent in entities:
            etype = ent.get("entity_type", "")
            etype_str = etype.value if hasattr(etype, "value") else str(etype)
            key = (etype_str, ent.get("entity_value", ""))
            if key not in seen_entities:
                seen_entities.add(key)
                deduped.append(ent)
        entities = deduped
        response["entities"] = entities

        # Step 3: Extract evidence spans
        evidence = self._extract_evidence(
            text, response["risk_label"], entities,
            response["risk_sub_label"],
        )
        response["evidence_spans"] = evidence

        # Step 4: Collect slang terms (dedup + lookup meanings from DB)
        slang_terms = []
        seen_slang = set()
        # Build a quick lookup from dim_slang_dict for meanings
        slang_meaning_map = {}
        try:
            for s in _mysql().list_slang("active"):
                slang_meaning_map[s.get("term", "")] = s.get("normalized_meaning", "")
        except Exception:
            pass

        for ent in entities:
            etype = ent.get("entity_type", "")
            etype_str = etype.value if hasattr(etype, "value") else str(etype)
            if etype_str == "slang":
                term = ent.get("entity_value", "")
                if term in seen_slang:
                    continue
                seen_slang.add(term)
                slang_terms.append({
                    "term": term,
                    "meaning": slang_meaning_map.get(term, ent.get("context", "")),
                    "risk_category": response["risk_label"],
                    "source": str(ent.get("extraction_method", "dict")),
                })
        response["slang_terms"] = slang_terms

        # Step 5: Graph expansion
        graph_result = {}
        if enable_graph_expand and entities:
            try:
                from agents.graph_agent import graph_agent
                graph_result = graph_agent.expand_all_entities(entities)
            except Exception as exc:
                logger.warning(f"Graph expansion skipped: {exc}")
        response["graph_result"] = graph_result

        # Step 6: Multi-factor risk score
        try:
            from analyzer.risk_scorer import risk_scorer
            scores = risk_scorer.score(
                classification=cls_result,
                entities=entities,
                graph_result=graph_result,
                slang_terms=slang_terms,
            )
            response["risk_score"] = scores["final_score"]
            response["risk_level"] = scores["risk_level"]
        except Exception as exc:
            logger.warning(f"Risk scoring failed, using base confidence: {exc}")
            response["risk_score"] = float(cls_result.get("confidence", 0.5))
            response["risk_level"] = "high" if response["risk_score"] >= 0.65 else "normal"

        # Step 7: Generate report
        if enable_report:
            try:
                from agents.report_agent import report_agent
                facts = self._build_facts(raw_data_id, platform, text,
                                          cls_result, entities, evidence,
                                          slang_terms, graph_result, response)
                report = report_agent.generate_rule_based(facts)
                response["agent_summary"] = report.get("conclusion", "")
                response["disposal_advice"] = report.get("disposal_advice", [])
            except Exception as exc:
                logger.warning(f"Report generation skipped: {exc}")

        # Step 8: Persist to all stores
        self._persist_all(raw_data_id, platform, text, cls_result,
                         entities, evidence, graph_result, response)

        # Log summary
        logger.info(
            f"[{raw_data_id}] {response['risk_label']}/{response['risk_sub_label']}"
            f" score={response['risk_score']:.2f} level={response['risk_level']}"
            f" entities={len(entities)} evidence={len(evidence)}"
        )

        return response

    # ── Degradation-aware classification ──────────────────────────────────

    def _classify_with_degradation(self, text: str) -> dict:
        if self._circuit_open:
            logger.warning("Circuit breaker OPEN — using L1+L2 fallback")
            result = _classifier.classify(text, skip_llm=True)
            result["method"] = self.DEGRADED_METHOD
            return result

        try:
            classify_fn = _with_retry(
                lambda: _classifier.classify(text, skip_llm=False),
                max_attempts=3, base_delay=2.0,
            )
            result = classify_fn()
            self._llm_failure_count = 0
            return result
        except Exception as exc:
            self._llm_failure_count += 1
            logger.error(
                f"LLM classification failed ({self._llm_failure_count}/"
                f"{self._circuit_threshold}): {exc}"
            )
            if self._llm_failure_count >= self._circuit_threshold:
                self._circuit_open = True
                logger.critical("CIRCUIT BREAKER OPENED")
            result = _classifier.classify(text, skip_llm=True)
            result["method"] = self.DEGRADED_METHOD
            return result

    def _extract_with_degradation(self, text: str, intent_label: str) -> list[dict]:
        try:
            extract_fn = _with_retry(
                lambda: self.entity_extractor.extract(
                    text, embed_fn=self._embed_fn, intent_label=intent_label,
                ),
                max_attempts=2, base_delay=1.5,
            )
            return extract_fn()
        except Exception as exc:
            logger.warning(f"LLM entity extraction failed, using L1+L2: {exc}")
            return self.entity_extractor.extract_l1_l2_only(
                text, embed_fn=self._embed_fn, intent_label=intent_label,
            )

    def _extract_evidence(self, text: str, risk_label: str,
                          entities: list[dict], risk_sub_label: str = "") -> list[dict]:
        """Extract evidence spans with degradation support."""
        try:
            from analyzer.evidence_extractor import evidence_extractor
            return evidence_extractor.extract(
                text=text,
                risk_label=risk_label,
                entities=entities,
                risk_sub_label=risk_sub_label,
                enable_llm=not self._circuit_open,
            )
        except Exception as exc:
            logger.warning(f"Evidence extraction failed, using entity context only: {exc}")
            from analyzer.evidence_extractor import evidence_extractor
            return evidence_extractor.extract_entity_context(text, entities)

    # ── Persistence ───────────────────────────────────────────────────────

    def _persist_all(self, raw_data_id: int, platform: str, text: str,
                     cls_result: dict, entities: list[dict],
                     evidence: list[dict], graph_result: dict,
                     response: dict):
        """Persist analysis results to MySQL, Neo4j, and Milvus."""

        intent_label = response["risk_label"]
        risk_level = response["risk_level"]

        # --- MySQL: dwd_clean_intel (cleaning record) ---
        import hashlib as _hashlib
        simhash_val = _hashlib.md5(text.encode()).hexdigest()[:16]
        content_md5 = _hashlib.md5(text.encode()).hexdigest()
        _mysql().insert_clean_intel(raw_data_id, clean_text=text, simhash=simhash_val)

        # --- MySQL: dwd_intel_analysis ---
        _mysql().insert_analysis({
            "raw_id": raw_data_id,
            "risk_label": intent_label,
            "risk_sub_label": response["risk_sub_label"],
            "risk_score": response["risk_score"],
            "risk_level": risk_level,
            "classification_method": cls_result.get("method", ""),
            "evidence_spans": evidence,
            "analysis_status": "CLASSIFIED",
        })

        # --- MySQL: dwd_entity ---
        for ent in entities:
            etype = ent["entity_type"]
            etype_str = etype.value if hasattr(etype, "value") else str(etype)
            _mysql().insert_entity({
                "raw_id": raw_data_id,
                "entity_type": etype_str,
                "entity_value": ent["entity_value"],
                "extract_method": str(ent.get("extraction_method", "degraded")),
                "context": ent.get("context", ""),
                "confidence": ent.get("confidence", 0.9),
                "start_offset": ent.get("start", -1),
                "end_offset": ent.get("end", -1),
            })

        # --- MySQL: ods_raw_intel status update ---
        _mysql().update_raw_status(raw_data_id, "ANALYZED",
                                   clean_text=text, simhash=simhash_val)

        # --- MySQL: agent_report ---
        if response.get("agent_summary"):
            _mysql().insert_report({
                "raw_id": raw_data_id,
                "case_id": graph_result.get("case_id", ""),
                "report_type": "intel_analysis",
                "title": f"风险研判报告 — {intent_label}",
                "summary": response["agent_summary"],
                "evidence_json": evidence,
                "entities_json": [
                    {
                        "type": (e["entity_type"].value if hasattr(e["entity_type"], "value")
                                 else str(e["entity_type"])),
                        "value": e["entity_value"],
                    }
                    for e in entities
                ],
                "graph_json": graph_result,
                "disposal_advice": response.get("disposal_advice", []),
                "generated_by": "engine",
            })

        # --- MySQL: ads_risk_case (gang-related only) ---
        if graph_result.get("is_gang_related"):
            _mysql().upsert_risk_case(
                case_id=graph_result["case_id"],
                case_name=f"团伙案件 — {graph_result.get('case_id', '')}",
                main_risk_type=intent_label,
                risk_level=risk_level if risk_level in ("high", "critical") else "high",
                summary=response.get("agent_summary", "")[:500],
                key_entities=_json_dumps(
                    [{"type": (e["entity_type"].value if hasattr(e["entity_type"], "value")
                              else str(e["entity_type"])),
                      "value": e["entity_value"]}
                     for e in entities[:20]],
                ),
                related_intel_count=graph_result.get("related_entities_count", 0),
                first_seen=graph_result.get("first_seen"),
                last_seen=graph_result.get("last_seen"),
            )

        # --- Neo4j ---
        self._sync_neo4j(raw_data_id, platform, text, entities)

        # --- Milvus ---
        try:
            if self._embed_fn:
                vec = self._embed_fn(text)
                text_hash = hashlib.md5(text.encode()).hexdigest()
                _milvus().insert_intel(raw_data_id, text_hash, vec)
        except Exception as exc:
            logger.warning(f"Milvus insert failed [{raw_data_id}]: {exc}")

    def _sync_neo4j(self, raw_data_id: int, platform: str, text: str,
                    entities: list[dict]):
        try:
            neo = _neo4j()
            neo.upsert_intel(raw_data_id, platform, text[:200])

            for ent in entities:
                etype = ent["entity_type"]
                etype_str = etype.value if hasattr(etype, "value") else str(etype)
                neo.upsert_entity_refined(etype_str, ent["entity_value"])
                neo.link_entity_to_intel_refined(etype_str, ent["entity_value"], raw_data_id)

            # Co-occurrence for gang detection
            for i in range(len(entities)):
                for j in range(i + 1, len(entities)):
                    et_i = entities[i]["entity_type"]
                    et_j = entities[j]["entity_type"]
                    et_i_str = et_i.value if hasattr(et_i, "value") else str(et_i)
                    et_j_str = et_j.value if hasattr(et_j, "value") else str(et_j)
                    neo.link_co_occurrence_refined(
                        et_i_str, entities[i]["entity_value"],
                        et_j_str, entities[j]["entity_value"],
                        raw_data_id,
                    )
        except Exception as exc:
            logger.error(f"Neo4j sync failed [{raw_data_id}]: {exc}")

    # ── Facts builder for report agent ────────────────────────────────────

    @staticmethod
    def _build_facts(raw_data_id, platform, text, cls_result, entities,
                     evidence, slang_terms, graph_result, response=None) -> dict:
        risk_score = (
            response.get("risk_score", 0) if response
            else cls_result.get("confidence", 0)
        )
        risk_level = (
            response.get("risk_level", "normal") if response
            else cls_result.get("risk_level", "normal")
        )
        return {
            "raw_id": raw_data_id,
            "platform": platform,
            "text": text,
            "risk": {
                "label": (
                    cls_result["intent_label"].value
                    if hasattr(cls_result["intent_label"], "value")
                    else str(cls_result["intent_label"])
                ),
                "sub_label": cls_result.get("sub_label", ""),
                "score": risk_score,
                "level": risk_level,
                "method": cls_result.get("method", ""),
            },
            "evidence": evidence,
            "entities": [
                {
                    "type": (
                        e["entity_type"].value
                        if hasattr(e["entity_type"], "value")
                        else str(e["entity_type"])
                    ),
                    "value": e["entity_value"],
                    "method": str(e.get("extraction_method", "")),
                }
                for e in entities
            ],
            "slang_terms": slang_terms,
            "graph": graph_result,
        }

    # ── Health ────────────────────────────────────────────────────────────

    @property
    def is_degraded(self) -> bool:
        return self._circuit_open

    def reset_circuit(self):
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
