"""Agent Orchestrator — state-machine-based analysis pipeline coordinator.

According to PROJECT_PLAN.md:
    "Not unleashing LLM freely, but calling tools according to a state diagram."

Pipeline: Clean → Classify → Evidence → Entities → Slang → Graph → Report
"""

from loguru import logger


class AgentOrchestrator:
    """Coordinate the full analysis pipeline with degradation support."""

    def __init__(self, engine):
        self.engine = engine

    def analyze(self, raw_data_id: int, text: str, platform: str,
                enable_graph_expand: bool = True,
                enable_report: bool = True,
                enable_llm: bool = True) -> dict:
        """Run the full state-machine pipeline and return an AnalyzeResponse.

        Returns a dict matching the Java<->Python contract in PROJECT_PLAN.md
        Section 8.1: POST /internal/v1/agent/analyze response format.
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
            "training_sample": {},
        }

        # --- Step 1: Classify ---
        try:
            cls_result = self.engine._classify_with_degradation(text)
        except Exception as exc:
            logger.error(f"Classification failed: {exc}")
            return response

        response["risk_label"] = (
            cls_result["intent_label"].value
            if hasattr(cls_result["intent_label"], "value")
            else str(cls_result["intent_label"])
        )
        response["risk_sub_label"] = cls_result.get("sub_label", "")

        # --- Step 2: Extract entities ---
        self.engine.load_embedding_model()
        try:
            entities = self.engine._extract_with_degradation(
                text, cls_result["intent_label"]
            )
        except Exception as exc:
            logger.error(f"Entity extraction failed: {exc}")
            entities = []

        # --- Step 3: Extract evidence spans ---
        try:
            from analyzer.evidence_extractor import evidence_extractor
            evidence = evidence_extractor.extract(
                text=text,
                risk_label=response["risk_label"],
                entities=entities,
                risk_sub_label=response["risk_sub_label"],
                enable_llm=enable_llm,
            )
            response["evidence_spans"] = evidence
        except Exception as exc:
            logger.error(f"Evidence extraction failed: {exc}")
            evidence = []

        # --- Step 4: Detect slang terms ---
        slang_terms = []
        for ent in entities:
            etype = ent.get("entity_type", "")
            etype_str = etype.value if hasattr(etype, "value") else str(etype)
            if etype_str == "slang":
                slang_terms.append({
                    "term": ent.get("entity_value", ""),
                    "meaning": ent.get("context", ""),
                    "risk_category": response["risk_label"],
                    "source": ent.get("extraction_method", "dict"),
                })
        response["slang_terms"] = slang_terms

        # --- Step 5: Graph expansion ---
        graph_result = {}
        if enable_graph_expand and entities:
            try:
                from agents.graph_agent import graph_agent
                graph_result = graph_agent.expand_all_entities(entities)
            except Exception as exc:
                logger.error(f"Graph expansion failed: {exc}")
        response["graph_result"] = graph_result

        # --- Step 6: Risk score ---
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
            logger.error(f"Risk scoring failed: {exc}")

        # --- Step 7: Report ---
        if enable_report:
            try:
                from agents.report_agent import report_agent
                facts = {
                    "raw_id": raw_data_id,
                    "platform": platform,
                    "text": text,
                    "risk": {
                        "label": response["risk_label"],
                        "sub_label": response["risk_sub_label"],
                        "score": response["risk_score"],
                        "level": response["risk_level"],
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
                        }
                        for e in entities
                    ],
                    "slang_terms": slang_terms,
                    "graph": graph_result,
                }
                report = report_agent.generate_rule_based(facts)
                response["agent_summary"] = report.get("conclusion", "")
                response["disposal_advice"] = report.get("disposal_advice", [])
                response["training_sample"] = report.get("training_sample", {})
            except Exception as exc:
                logger.error(f"Report generation failed: {exc}")

        # --- Step 8: Persist to all stores ---
        try:
            self.engine._persist_results(
                raw_data_id, platform, text, cls_result, entities, evidence,
                graph_result, response,
            )
        except Exception as exc:
            logger.error(f"Persistence failed: {exc}")

        return response


# Singleton (initialized after engine is created)
orchestrator: AgentOrchestrator = None


def get_orchestrator(engine=None) -> AgentOrchestrator:
    global orchestrator
    if orchestrator is None and engine is not None:
        orchestrator = AgentOrchestrator(engine)
    return orchestrator
