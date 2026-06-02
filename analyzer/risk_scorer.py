"""Multi-factor risk scoring — beyond simple classification confidence.

According to PROJECT_PLAN.md:
    Scoring factors:
    1. Classification confidence (base)
    2. Contact entity bonus (wechat/qq/phone present)
    3. URL/link bonus (external links present)
    4. Tool/script bonus (tool names detected)
    5. High-risk slang bonus
    6. Graph association bonus (historical connections found)
"""

from schema import IntentLabel


# Risk-level thresholds
RISK_THRESHOLDS = {
    "critical": 0.85,
    "high": 0.65,
    "normal": 0.35,
    "low": 0.0,
}

# High-risk intent labels that always get a base bonus
HIGH_RISK_LABELS = {"诈骗", "账号黑产"}

# Entity types that carry extra risk
CONTACT_ENTITY_TYPES = {"wechat", "qq", "phone", "telegram"}
LINK_ENTITY_TYPES = {"url", "domain", "ip"}
TOOL_ENTITY_TYPES = {"tool"}
FINANCIAL_ENTITY_TYPES = {"bank_card", "alipay"}


class RiskScorer:
    """Calculate multi-factor risk score for an intelligence item."""

    # Weight configuration (v0.8: added metadata_signals)
    WEIGHTS = {
        "classification_confidence": 0.45,   # base: how confident is the classifier?
        "contact_entity": 0.14,              # has contact info?
        "link_entity": 0.11,                 # has external links?
        "tool_entity": 0.07,                 # mentions tools/scripts?
        "high_risk_slang": 0.09,             # contains high-risk slang terms?
        "graph_association": 0.04,           # connected to historical entities?
        "metadata_signals": 0.10,            # (v0.8) metadata signals (hashtags, engagement)
    }

    def score(self, classification: dict, entities: list[dict],
              graph_result: dict = None,
              slang_terms: list[dict] = None,
              metadata_signals: dict = None) -> dict:
        """Calculate final risk score from multiple factors.

        Args:
            classification: {intent_label, sub_label, confidence, method}
            entities: list of extracted entity dicts
            graph_result: {is_gang_related, related_entities_count, ...} or None
            slang_terms: list of detected slang terms or None
            metadata_signals: {confidence_boost, signals, ...} or None (v0.8)

        Returns:
            {base_score, contact_bonus, link_bonus, tool_bonus, slang_bonus,
             graph_bonus, metadata_bonus, final_score, risk_level, factors_explanation}
        """
        graph_result = graph_result or {}
        slang_terms = slang_terms or []
        metadata_signals = metadata_signals or {}

        # --- Factor 1: Classification confidence (base) ---
        classification_conf = float(classification.get("confidence", 0.5))
        intent_label = classification.get("intent_label", "")
        intent_str = intent_label.value if hasattr(intent_label, "value") else str(intent_label)

        # Boost base for inherently high-risk categories
        if intent_str in HIGH_RISK_LABELS:
            classification_conf = min(1.0, classification_conf * 1.1)

        base_score = round(classification_conf * self.WEIGHTS["classification_confidence"], 4)
        factors = [f"分类置信度: {classification_conf:.2f}"]

        # --- Factor 2: Contact entity bonus ---
        contact_count = sum(
            1 for e in entities
            if (e.get("entity_type", "").value if hasattr(e.get("entity_type", ""), "value")
                else str(e.get("entity_type", ""))) in CONTACT_ENTITY_TYPES
        )
        contact_bonus = round(
            min(1.0, contact_count * 0.3) * self.WEIGHTS["contact_entity"], 4
        )
        if contact_count:
            factors.append(f"联系方式实体: +{contact_bonus:.2f} ({contact_count}个)")

        # --- Factor 3: Link/URL bonus ---
        link_count = sum(
            1 for e in entities
            if (e.get("entity_type", "").value if hasattr(e.get("entity_type", ""), "value")
                else str(e.get("entity_type", ""))) in LINK_ENTITY_TYPES
        )
        link_bonus = round(
            min(1.0, link_count * 0.35) * self.WEIGHTS["link_entity"], 4
        )
        if link_count:
            factors.append(f"外链实体: +{link_bonus:.2f} ({link_count}个)")

        # --- Factor 4: Tool entity bonus ---
        tool_count = sum(
            1 for e in entities
            if (e.get("entity_type", "").value if hasattr(e.get("entity_type", ""), "value")
                else str(e.get("entity_type", ""))) in TOOL_ENTITY_TYPES
        )
        tool_bonus = round(
            min(1.0, tool_count * 0.5) * self.WEIGHTS["tool_entity"], 4
        )
        if tool_count:
            factors.append(f"工具实体: +{tool_bonus:.2f} ({tool_count}个)")

        # --- Factor 5: High-risk slang bonus ---
        slang_count = len(slang_terms)
        slang_bonus = round(
            min(1.0, slang_count * 0.25) * self.WEIGHTS["high_risk_slang"], 4
        )
        if slang_count:
            factors.append(f"黑话检测: +{slang_bonus:.2f} ({slang_count}个)")

        # --- Factor 6: Graph association bonus ---
        graph_bonus = 0.0
        if graph_result.get("is_gang_related"):
            related_count = graph_result.get("related_entities_count", 0)
            graph_bonus = round(
                min(1.0, related_count * 0.2) * self.WEIGHTS["graph_association"], 4
            )
            factors.append(f"图谱关联: +{graph_bonus:.2f} ({related_count}个关联实体)")

        # --- Factor 7: Metadata signals bonus (v0.8) ---
        metadata_bonus = 0.0
        meta_boost = metadata_signals.get("confidence_boost", 0.0)
        meta_signal_count = len(metadata_signals.get("signals", []))
        if meta_boost > 0:
            metadata_bonus = round(meta_boost * self.WEIGHTS["metadata_signals"], 4)
            factors.append(f"Metadata信号: +{metadata_bonus:.2f} ({meta_signal_count}个信号)")

        # --- Final score ---
        final_score = round(
            base_score + contact_bonus + link_bonus + tool_bonus +
            slang_bonus + graph_bonus + metadata_bonus, 4
        )
        final_score = min(1.0, final_score)

        # --- Risk level ---
        if final_score >= RISK_THRESHOLDS["critical"]:
            risk_level = "critical"
        elif final_score >= RISK_THRESHOLDS["high"]:
            risk_level = "high"
        elif final_score >= RISK_THRESHOLDS["normal"]:
            risk_level = "normal"
        else:
            risk_level = "low"

        return {
            "base_score": base_score,
            "contact_bonus": contact_bonus,
            "link_bonus": link_bonus,
            "tool_bonus": tool_bonus,
            "slang_bonus": slang_bonus,
            "graph_bonus": graph_bonus,
            "metadata_bonus": metadata_bonus,
            "final_score": final_score,
            "risk_level": risk_level,
            "factors": factors,
        }


# ---------------------------------------------------------------------------
# Singleton
# ---------------------------------------------------------------------------

risk_scorer = RiskScorer()
