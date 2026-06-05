"""Report Agent — generate structured intelligence reports from facts.

According to PROJECT_PLAN.md Step 12:
    "The Agent should not compose freely. It can only generate reports
     based on structured facts. Facts come from Doris/MySQL/Neo4j."

Two modes:
    1. Rule-based (zero LLM): template-fill from structured facts
    2. LLM-enhanced: use LLM to polish language while grounding in facts
"""

import json
from datetime import datetime
from loguru import logger

from config.settings import settings


class ReportAgent:
    """Generate intelligence analysis reports grounded in structured facts."""

    # ------------------------------------------------------------------
    # Rule-based report generation (zero LLM, always works)
    # ------------------------------------------------------------------

    def generate_rule_based(self, facts: dict) -> dict:
        """Fill a report template from structured facts. Zero LLM cost.

        Args:
            facts: {
                "raw_id": int,
                "platform": str,
                "text": str,
                "collected_at": str,
                "author_username": str,
                "group_id": str,
                "risk": {"label", "sub_label", "score", "level", "method"},
                "evidence": [{"text", "risk_point", "reason", "confidence"}],
                "entities": [{"type", "value", "method"}],
                "slang_terms": [{"term", "meaning", "risk_category"}],
                "graph": {"case_id", "cluster_id", "is_gang_related",
                          "related_entities_count", "shared_contacts"},
            }

        Returns:
            Report dict with sections: conclusion, evidence, entities, slang,
            graph_expansion, disposal_advice, training_sample
        """
        risk = facts.get("risk", {})
        evidence = facts.get("evidence", [])
        entities = facts.get("entities", [])
        slang_terms = facts.get("slang_terms", [])
        graph = facts.get("graph", {})

        risk_label = risk.get("label", "未分类")
        risk_sub = risk.get("sub_label", "")
        risk_score = risk.get("score", 0)
        risk_level = risk.get("level", "normal")

        # --- 1. Conclusion ---
        level_cn = {"high": "高危", "critical": "严重", "normal": "普通", "low": "低"}
        conclusion = (
            f"该情报经系统研判，判定为「{risk_label}」类黑灰产信息"
        )
        if risk_sub:
            conclusion += f"（{risk_sub}）"
        conclusion += (
            f"，风险等级为 {level_cn.get(risk_level, risk_level)}"
            f"（评分 {risk_score:.2f}）。"
        )

        # --- 2. Evidence ---
        evidence_items = []
        for ev in evidence[:5]:  # top 5
            evidence_items.append({
                "fragment": ev.get("text", ""),
                "risk_dimension": ev.get("risk_point", ""),
                "explanation": ev.get("reason", ""),
                "confidence": ev.get("confidence", 0),
            })

        # --- 3. Entities ---
        entity_groups = {}
        for ent in entities:
            etype = ent.get("type", "")
            etype_str = etype.value if hasattr(etype, "value") else str(etype)
            evalue = ent.get("value", "")
            entity_groups.setdefault(etype_str, []).append(evalue)

        entity_summary = [
            {"type": t, "values": list(dict.fromkeys(vs))}  # dedup
            for t, vs in entity_groups.items()
        ]

        # --- 4. Slang normalization ---
        slang_items = []
        for sl in slang_terms[:10]:
            slang_items.append({
                "term": sl.get("term", ""),
                "meaning": sl.get("meaning", ""),
                "risk_category": sl.get("risk_category", ""),
                "source": sl.get("source", "dict"),
            })

        # --- 5. Graph expansion ---
        graph_section = {}
        if graph.get("is_gang_related"):
            graph_section = {
                "gang_detected": True,
                "case_id": graph.get("case_id", ""),
                "cluster_id": graph.get("cluster_id", ""),
                "related_entities_count": graph.get("related_entities_count", 0),
                "shared_contacts": graph.get("shared_contacts", []),
                "summary": (
                    f"该情报涉及实体与 {graph.get('related_entities_count', 0)} 个历史实体"
                    f"存在关联，已归入案件 {graph.get('case_id', 'N/A')}"
                ),
            }
        else:
            graph_section = {
                "gang_detected": False,
                "summary": "未发现与历史情报的直接关联。该情报涉及的实体均为首次出现。",
            }

        # --- 6. Disposal advice ---
        advice = self._generate_advice(
            risk_label, risk_sub, entities, evidence, graph
        )

        # --- 7. Training sample ---
        training_sample = self._build_training_sample(facts)

        # --- Assemble ---
        report = {
            "report_type": "intel_analysis",
            "generated_at": datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),
            "generated_by": "report_agent_rule",
            "title": f"风险研判报告 — {risk_label}",
            "conclusion": conclusion,
            "risk": {
                "label": risk_label,
                "sub_label": risk_sub,
                "score": risk_score,
                "level": risk_level,
            },
            "evidence": evidence_items,
            "entities": entity_summary,
            "slang_terms": slang_items,
            "graph_expansion": graph_section,
            "disposal_advice": advice,
            "training_sample": training_sample,
        }

        return report

    # ------------------------------------------------------------------
    # LLM-enhanced report (polishes language, grounded in facts)
    # ------------------------------------------------------------------

    def generate_with_llm(self, facts: dict) -> dict:
        """Use LLM to polish the report language while staying grounded in facts.

        Falls back to rule-based on any LLM failure.
        """
        # First generate rule-based as fact base
        base = self.generate_rule_based(facts)

        prompt = f"""你是黑灰产情报分析专家。请基于以下结构化事实，生成一份专业的风险研判报告。

## 事实数据
{json.dumps(base, ensure_ascii=False, indent=2)}

## 要求
1. 使用专业但清晰的中文
2. 每个结论必须引用事实数据中的具体证据
3. 处置建议要具体可操作
4. 不要编造事实数据中不存在的内容
5. 仅返回JSON格式报告，与输入的JSON结构一致，但conclusion和disposal_advice可以优化措辞

请返回："""

        try:
            from openai import OpenAI
            client = OpenAI(api_key=settings.llm_api_key, base_url=settings.llm_api_base)
            resp = client.chat.completions.create(
                model=settings.llm_model,
                messages=[{"role": "user", "content": prompt}],
                temperature=0.2,
                max_tokens=1500)
            enhanced = json.loads(resp.choices[0].message.content)
            enhanced["generated_by"] = "report_agent_llm"
            enhanced["generated_at"] = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
            return enhanced
        except Exception as exc:
            logger.warning(f"LLM report enhancement failed, using rule-based: {exc}")
            return base

    # ------------------------------------------------------------------
    # Advice generation
    # ------------------------------------------------------------------

    @staticmethod
    def _generate_advice(risk_label, risk_sub, entities, evidence, graph) -> list[dict]:
        """Generate actionable disposal recommendations."""
        advice = []
        seen_entity_advice = set()  # dedup entity-specific advice

        # Per-risk-type generic advice
        risk_advice_map = {
            "直播违规": [
                {"action": "关键词监控", "detail": f"将相关关键词加入直播平台风险词库", "priority": "high"},
                {"action": "账号监控", "detail": "对涉及账号进行持续行为监控", "priority": "high"}],
            "诈骗": [
                {"action": "诈骗模型更新", "detail": "将该样本加入诈骗识别模型训练集", "priority": "high"},
                {"action": "资金链路追踪", "detail": "对涉及银行账号/支付账号进行关联排查", "priority": "critical"}],
            "引流": [
                {"action": "渠道封堵", "detail": "对引流微信/QQ号进行标记和举报", "priority": "high"},
                {"action": "域名监控", "detail": "将引流域名加入黑名单", "priority": "medium"}],
            "作弊": [
                {"action": "行为特征入库", "detail": "提取作弊行为特征，更新风控规则", "priority": "high"},
                {"action": "设备指纹", "detail": "关联作弊工具的设备指纹信息", "priority": "medium"}],
            "账号黑产": [
                {"action": "批量账号识别", "detail": "对同批次注册账号进行回溯排查", "priority": "critical"},
                {"action": "实名验证加强", "detail": "针对可疑注册模式加强实名验证", "priority": "high"}],
            "工具交易": [
                {"action": "工具溯源", "detail": "对交易工具进行技术分析和特征提取", "priority": "high"},
                {"action": "卖家追踪", "detail": "通过支付信息追踪工具卖家", "priority": "medium"}],
            "内容违规": [
                {"action": "内容清除", "detail": "对违规内容进行下架处理", "priority": "high"},
                {"action": "发布者处置", "detail": "对发布者账号进行警告或封禁", "priority": "medium"}],
        }

        default_advice = [
            {"action": "持续监控", "detail": "将该情报涉及的实体加入监控清单", "priority": "medium"},
            {"action": "样本积累", "detail": "将该情报作为训练样本积累", "priority": "low"}]

        advice.extend(risk_advice_map.get(risk_label, default_advice))

        # Entity-specific advice
        for ent in entities:
            etype = ent.get("type", "")
            etype_str = etype.value if hasattr(etype, "value") else str(etype)
            evalue = ent.get("value", "")
            advice_key = (etype_str, evalue)
            if advice_key in seen_entity_advice:
                continue
            seen_entity_advice.add(advice_key)
            if etype_str == "wechat":
                advice.append({
                    "action": f"微信号标记: {evalue}",
                    "detail": "将微信号加入高风险账号库，查询历史关联",
                    "priority": "high",
                })
            elif etype_str == "url":
                advice.append({
                    "action": f"URL黑名单: {evalue[:60]}",
                    "detail": "将链接加入URL风险库，阻断访问",
                    "priority": "critical",
                })

        # Graph-based advice
        if graph.get("is_gang_related"):
            advice.append({
                "action": "团伙扩线",
                "detail": f"该实体已关联案件 {graph.get('case_id', '')}，建议对案件中所有实体进行扩线排查",
                "priority": "critical",
            })

        return advice

    # ------------------------------------------------------------------
    # Training sample builder
    # ------------------------------------------------------------------

    @staticmethod
    def _build_training_sample(facts: dict) -> dict:
        """Build a training sample from the analysis for future model fine-tuning."""
        risk = facts.get("risk", {})
        return {
            "text": facts.get("text", ""),
            "label": f"{risk.get('label', '')}_{risk.get('sub_label', '')}",
            "risk_label": risk.get("label", ""),
            "risk_sub_label": risk.get("sub_label", ""),
            "entities": [
                {"type": e.get("type", ""), "value": e.get("value", "")}
                for e in facts.get("entities", [])[:20]
            ],
            "evidence_count": len(facts.get("evidence", [])),
            "has_contact_entity": any(
                e.get("type") in ("wechat", "qq", "phone")
                for e in facts.get("entities", [])
            ),
            "has_url": any(
                e.get("type") == "url"
                for e in facts.get("entities", [])
            ),
            "source": "bgi_analysis",
            "created_at": datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),
        }


# ---------------------------------------------------------------------------
# Singleton
# ---------------------------------------------------------------------------

report_agent = ReportAgent()
