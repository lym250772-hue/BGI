"""State-machine Agent for intel analysis with tool-based decision making.

Replaces the fixed sequential pipeline with a state graph where the Agent
autonomously decides which tools to invoke based on extracted entities and
classification confidence.

State graph:
    classify → extract_entities → decide_tools
                                    ├─ graph_expand   (if expandable entities present)
                                    ├─ slang_normalize (if slang terms detected)
                                    └─ dedup_check     (if classification confidence ≥ threshold)
                                    ↓
                               extract_evidence → risk_score → generate_report → persist
"""

import hashlib
import json
from loguru import logger
from dataclasses import dataclass, field

from schema import Priority


# ── Tool Result ────────────────────────────────────────────────────────────────

@dataclass
class ToolResult:
    success: bool = True
    data: dict = field(default_factory=dict)
    error: str = ""


# ── Tools ─────────────────────────────────────────────────────────────────────

class GraphExpandTool:
    """Expand entities in Neo4j knowledge graph to find related intel and gangs."""

    name = "graph_expand"
    description = "Query Neo4j for related intel, accounts, contacts connected to given entities"

    def run(self, state: dict, enable_graph: bool = True) -> dict:
        entities = state.get("entities", [])
        if not enable_graph or not entities:
            state["graph_result"] = {}
            state["tool_log"].append({"tool": self.name, "decision": "skipped",
                                       "reason": "graph disabled or no entities"})
            return state

        expandable = [e for e in entities if self._is_expandable(e)]
        if not expandable:
            state["graph_result"] = {}
            state["tool_log"].append({"tool": self.name, "decision": "skipped",
                                       "reason": "no expandable entities"})
            return state

        try:
            from agents.graph_agent import graph_agent
            result = graph_agent.expand_all_entities(entities)
            state["graph_result"] = result
            state["tool_log"].append({"tool": self.name, "decision": "run",
                                       "result": f"{result.get('related_entities_count', 0)} related"})
            logger.info(f"[GraphExpand] {len(expandable)} entities expanded, "
                        f"gang={result.get('is_gang_related')}")
        except Exception as exc:
            logger.warning(f"GraphExpand failed: {exc}")
            state["graph_result"] = {}
            state["tool_log"].append({"tool": self.name, "decision": "failed",
                                       "error": str(exc)})

        return state

    @staticmethod
    def _is_expandable(entity: dict) -> bool:
        etype = entity.get("entity_type", "")
        etype_str = etype.value if hasattr(etype, "value") else str(etype)
        return etype_str in ("wechat", "qq", "phone", "url", "domain",
                             "bank_card", "alipay", "tool")


class SlangNormalizeTool:
    """Normalize slang terms using dictionary lookup from MySQL."""

    name = "slang_normalize"
    description = "Look up slang terms in dim_slang_dict to get normalized meanings"

    def run(self, state: dict) -> dict:
        entities = state.get("entities", [])
        slang_entities = [e for e in entities if self._is_slang(e)]
        if not slang_entities:
            state["slang_terms"] = []
            state["tool_log"].append({"tool": self.name, "decision": "skipped",
                                       "reason": "no slang entities"})
            return state

        # Build slang meaning lookup
        slang_meaning_map = {}
        try:
            from storage.mysql_store import mysql as _mysql
            for s in _mysql.list_slang("active"):
                slang_meaning_map[s.get("term", "")] = s.get("normalized_meaning", "")
        except Exception:
            pass

        seen_slang = set()
        slang_terms = []
        risk_label = state.get("risk_label", "")

        for ent in slang_entities:
            etype = ent.get("entity_type", "")
            etype_str = etype.value if hasattr(etype, "value") else str(etype)
            if etype_str != "slang":
                continue
            term = ent.get("entity_value", "")
            if term in seen_slang:
                continue
            seen_slang.add(term)
            slang_terms.append({
                "term": term,
                "meaning": slang_meaning_map.get(term, ent.get("context", "")),
                "risk_category": risk_label,
                "source": str(ent.get("extraction_method", "dict")),
            })

        state["slang_terms"] = slang_terms
        state["tool_log"].append({"tool": self.name, "decision": "run",
                                   "result": f"{len(slang_terms)} terms normalized"})
        return state

    @staticmethod
    def _is_slang(entity: dict) -> bool:
        etype = entity.get("entity_type", "")
        etype_str = etype.value if hasattr(etype, "value") else str(etype)
        return etype_str == "slang"


class DedupCheckTool:
    """Check Milvus vector DB for semantically similar historical intel."""

    name = "dedup_check"
    description = "Query Milvus for near-duplicate intel using embedding similarity"

    def run(self, state: dict) -> dict:
        """Check if similar intel has been analyzed before."""
        text = state.get("clean_text", "")
        classification_conf = state.get("classification_confidence", 0)

        # Only run dedup if classification has reasonable confidence
        if classification_conf < 0.6:
            state["tool_log"].append({"tool": self.name, "decision": "skipped",
                                       "reason": f"low confidence ({classification_conf:.2f})"})
            state["similar_intel_ids"] = []
            return state

        try:
            from storage.milvus_store import milvus
            embed_fn = state.get("_embed_fn")
            if embed_fn:
                vec = embed_fn(text)
                text_hash = hashlib.md5(text.encode()).hexdigest()
                results = milvus.search_similar_intel(vec, top_k=5)
                similar = []
                for r in results:
                    if r.get("score", 1.0) < 0.3:  # cosine distance threshold
                        similar.append(r.get("raw_data_id"))
                state["similar_intel_ids"] = similar
                state["tool_log"].append({"tool": self.name, "decision": "run",
                                           "result": f"{len(similar)} similar found"})
            else:
                state["similar_intel_ids"] = []
                state["tool_log"].append({"tool": self.name, "decision": "skipped",
                                           "reason": "no embedding function"})
        except Exception as exc:
            logger.warning(f"DedupCheck failed: {exc}")
            state["similar_intel_ids"] = []
            state["tool_log"].append({"tool": self.name, "decision": "failed",
                                       "error": str(exc)})

        return state


# ── State Machine Agent ───────────────────────────────────────────────────────

class AnalysisAgent:
    """State-machine Agent for black/grey-market intel analysis.

    Replaces the old sequential pipeline with a state graph where the Agent
    autonomously decides which tools to invoke at each step based on the
    current analysis state (entities found, confidence levels, etc.).

    States:
        classify → extract_entities → decide_tools → extract_evidence
                                                       ↓
                                                  risk_score → generate_report → persist
    """

    DEGRADED_METHOD = "degraded"
    CIRCUIT_THRESHOLD = 5

    def __init__(self):
        self.tools = {
            "graph_expand": GraphExpandTool(),
            "slang_normalize": SlangNormalizeTool(),
            "dedup_check": DedupCheckTool(),
        }
        self._embed_fn = None
        self._llm_failure_count = 0
        self._circuit_open = False

    # ── Public API ────────────────────────────────────────────────────────

    def run(self, raw_data_id: int, text: str, platform: str,
            enable_graph_expand: bool = True,
            enable_report: bool = True,
            enable_llm: bool = True) -> dict:
        """Run full analysis via state machine.

        Returns a dict matching the PROJECT_PLAN.md AnalyzeResponse format.
        """
        state = self._init_state(raw_data_id, text, platform)
        state["enable_graph_expand"] = enable_graph_expand
        state["enable_report"] = enable_report
        state["enable_llm"] = enable_llm

        logger.info(f"[{raw_data_id}] Agent starting analysis, text_len={len(text)}")

        # State transitions — each handler returns the updated state
        state = self._state_classify(state)
        state = self._state_extract_entities(state)
        state = self._state_decide_tools(state)
        state = self._state_extract_evidence(state)
        state = self._state_risk_score(state)
        state = self._state_generate_report(state)
        state = self._state_persist(state)

        logger.info(
            f"[{raw_data_id}] {state['risk_label']}/{state['risk_sub_label']}"
            f" score={state['risk_score']:.2f} level={state['risk_level']}"
            f" entities={len(state['entities'])} evidence={len(state['evidence_spans'])}"
            f" tools={[t['tool'] for t in state['tool_log'] if t.get('decision') == 'run']}"
        )

        return self._build_response(state)

    # ── Streaming API: step-by-step with think-chain ──────────────────────

    def run_stream(self, raw_data_id: int, text: str, platform: str,
                   enable_graph_expand: bool = True,
                   enable_report: bool = True,
                   enable_llm: bool = True):
        """Generator that yields each analysis step with think-chain for UI display.

        Each yield is a dict:
            {step, status, thinking, result_summary, state_snapshot}
        """
        state = self._init_state(raw_data_id, text, platform)
        state["enable_graph_expand"] = enable_graph_expand
        state["enable_report"] = enable_report
        state["enable_llm"] = enable_llm

        # ── Step 1: Classify ──
        yield {
            "step": "classify", "status": "running",
            "thinking": (
                "Agent 启动三级分类级联：\n"
                "① L1 关键词正则匹配（42条规则，覆盖约30%的情报）\n"
                "② L2 RoBERTa 深度学习模型（7大类别，阈值0.7）\n"
                "③ L3 DeepSeek LLM 兜底（处理L1/L2未命中的10%长尾样本）\n"
                f"待分析文本长度：{len(text)} 字符"
            ),
        }
        state = self._state_classify(state)
        method_cn = {"keyword": "L1 关键词规则", "roberta": "L2 RoBERTa模型",
                     "llm": "L3 LLM推理", "degraded": "降级模式(L1+L2)"}
        cls_method = state.get("classification_method", "")
        yield {
            "step": "classify", "status": "done",
            "thinking": (
                f"分类完成，命中方式：{method_cn.get(cls_method, cls_method)}\n"
                f"一级分类：「{state['risk_label']}」"
                + (f"\n二级分类：「{state['risk_sub_label']}」" if state.get("risk_sub_label") else "") +
                f"\n置信度：{state['classification_confidence']:.2f}"
                + (f"\n熔断器状态：{'已熔断(跳过LLM)' if self._circuit_open else '正常'}" if cls_method == "degraded" else "")
            ),
            "result_summary": {
                "风险标签": state["risk_label"],
                "子标签": state.get("risk_sub_label", ""),
                "置信度": f"{state['classification_confidence']:.2f}",
                "分类方法": method_cn.get(cls_method, cls_method),
            },
        }

        # ── Step 2: Extract Entities ──
        yield {
            "step": "extract_entities", "status": "running",
            "thinking": (
                "Agent 启动四级实体抽取级联：\n"
                "① L1 正则提取（手机号/微信号/QQ/URL/银行卡等9种实体）\n"
                "② L2 词典匹配（平台黑话词库）\n"
                "③ L3 向量语义匹配（Milvus 384维嵌入相似度）\n"
                "④ L4 LLM 上下文理解（复杂实体关系抽取）\n"
                "然后按 (entity_type, entity_value) 去重"
            ),
        }
        state = self._state_extract_entities(state)
        entities = state["entities"]
        entity_types = {}
        extraction_methods = set()
        for e in entities:
            et = e.get("entity_type", "")
            et_s = et.value if hasattr(et, "value") else str(et)
            entity_types.setdefault(et_s, 0)
            entity_types[et_s] += 1
            em = e.get("extraction_method", "")
            em_s = em.value if hasattr(em, "value") else str(em)
            extraction_methods.add(em_s)

        llm_skipped = "llm" not in extraction_methods and state.get("classification_confidence", 0) >= 0.8
        skip_msg = (
            "\n\nLLM 实体抽取：已跳过（规则+词典已高置信命中，节省推理成本）"
            if llm_skipped else
            f"\n\nLLM 实体抽取：已调用（提取方法：{' + '.join(sorted(extraction_methods))}）"
        )

        yield {
            "step": "extract_entities", "status": "done",
            "thinking": (
                f"实体抽取完成，共识别 {len(entities)} 个实体\n"
                + "\n".join(f"  · {t}: {c}个" for t, c in sorted(entity_types.items()))
                + (f"\n\n其中 {entity_types.get('slang', 0)} 个黑话术语需要后续归一化"
                   if entity_types.get('slang', 0) else "")
                + skip_msg
            ),
            "result_summary": {
                "实体总数": str(len(entities)),
                "实体类型": ", ".join(f"{t}({c})" for t, c in sorted(entity_types.items())),
            },
        }

        # ── Step 3: Decide Tools ──
        expandable = [e for e in entities if self.tools["graph_expand"]._is_expandable(e)]
        has_slang = any(
            (e.get("entity_type", "").value if hasattr(e.get("entity_type", ""), "value")
             else str(e.get("entity_type", ""))) == "slang"
            for e in entities
        )
        conf = state.get("classification_confidence", 0)

        decisions = []
        if expandable:
            types = set()
            for e in expandable:
                et = e.get("entity_type", "")
                types.add(et.value if hasattr(et, "value") else str(et))
            decisions.append(
                f"✅ 图谱扩线 — 发现 {len(expandable)} 个可扩线实体"
                f"（{', '.join(sorted(types))}），将在 Neo4j 中查询关联"
            )
        else:
            decisions.append("⊘ 图谱扩线 — 无可扩线实体，跳过")
        if has_slang:
            decisions.append("✅ 黑话归一 — 检测到黑话术语，将查询 dim_slang_dict 获取释义")
        else:
            decisions.append("⊘ 黑话归一 — 未检测到黑话，跳过")
        if conf >= 0.6:
            decisions.append(
                f"✅ 相似去重 — 分类置信度 {conf:.2f} ≥ 0.6，"
                "将在 Milvus 中检索历史相似情报"
            )
        else:
            decisions.append(
                f"⊘ 相似去重 — 分类置信度 {conf:.2f} < 0.6，跳过"
                "（低置信度下相似匹配可能不准确）"
            )

        yield {
            "step": "decide_tools", "status": "running",
            "thinking": (
                "Agent 自主决策节点：根据已抽取的实体类型和分类置信度，"
                "决定调用哪些工具。\n\n决策依据：\n"
                f"· 可扩线实体数：{len(expandable)}（类型：wechat/qq/phone/url/domain/bank_card/alipay/tool）\n"
                f"· 黑话实体数：{entity_types.get('slang', 0)}\n"
                f"· 分类置信度：{conf:.2f}"
            ),
        }
        state = self._state_decide_tools(state)
        ran_tools = [t["tool"] for t in state["tool_log"] if t.get("decision") == "run"]

        yield {
            "step": "decide_tools", "status": "done",
            "thinking": "工具调用决策完成。\n\n" + "\n".join(decisions) +
                        "\n\n实际执行：" + ", ".join(ran_tools) if ran_tools else "无工具需要执行",
            "result_summary": {
                "已执行工具": ", ".join(ran_tools) if ran_tools else "无",
                "图谱扩线": "是" if "graph_expand" in ran_tools else "否",
                "黑话归一": "是" if "slang_normalize" in ran_tools else "否",
                "相似去重": "是" if "dedup_check" in ran_tools else "否",
            },
        }

        # ── Step 4: Extract Evidence ──
        yield {
            "step": "extract_evidence", "status": "running",
            "thinking": (
                "Agent 启动三层证据提取：\n"
                "① 规则层 — 基于分类标签匹配预设的风险点正则\n"
                "② 实体上下文层 — 提取每个实体周围的上下文文本\n"
                "③ LLM 解释层 — 让LLM解释为什么这段文本是风险证据\n"
                + ("（熔断器已打开，跳过LLM层）" if self._circuit_open else "")
            ),
        }
        state = self._state_extract_evidence(state)
        evidence = state.get("evidence_spans", [])
        methods = {}
        for ev in evidence:
            m = ev.get("method", "?")
            methods[m] = methods.get(m, 0) + 1
        yield {
            "step": "extract_evidence", "status": "done",
            "thinking": (
                f"证据提取完成，共提取 {len(evidence)} 条证据\n"
                + "\n".join(f"  · {m}: {c}条" for m, c in methods.items())
            ),
            "result_summary": {
                "证据总数": str(len(evidence)),
                "证据来源": ", ".join(f"{m}({c})" for m, c in methods.items()),
            },
        }

        # ── Step 5: Risk Score ──
        yield {
            "step": "risk_score", "status": "running",
            "thinking": (
                "Agent 启动6因子加权风险评分：\n"
                "① 分类置信度（权重 50%）\n"
                "② 联系方式实体加成（权重 15%）\n"
                "③ 外链实体加成（权重 12%）\n"
                "④ 工具实体加成（权重 8%）\n"
                "⑤ 黑话检测加成（权重 10%）\n"
                "⑥ 图谱关联加成（权重 5%）\n"
                "最终分数 = 各因子加权求和，上限1.0"
            ),
        }
        state = self._state_risk_score(state)
        level_cn = {"critical": "严重", "high": "高危", "normal": "普通", "low": "低"}
        yield {
            "step": "risk_score", "status": "done",
            "thinking": (
                f"风险评分完成：{state['risk_score']:.2f}（{level_cn.get(state['risk_level'], state['risk_level'])}）\n"
                f"分类级别 threshold：critical≥0.85, high≥0.65, normal≥0.35, low<0.35"
            ),
            "result_summary": {
                "风险评分": f"{state['risk_score']:.2f}",
                "风险等级": level_cn.get(state['risk_level'], state['risk_level']),
            },
        }

        # ── Step 6: Generate Report ──
        if enable_report:
            yield {
                "step": "generate_report", "status": "running",
                "thinking": (
                    "Agent 基于结构化事实生成研判报告：\n"
                    "· 使用规则模板填充（零LLM成本）\n"
                    "· 报告包含：结论摘要、证据列表、实体汇总、黑话解释、图谱扩线结果、处置建议\n"
                    "· 处置建议分4级优先级：严重/高危/普通/低"
                ),
            }
            state = self._state_generate_report(state)
            advice_count = len(state.get("disposal_advice", []))
            summary_preview = state.get("agent_summary", "")[:120]
            yield {
                "step": "generate_report", "status": "done",
                "thinking": (
                    f"研判报告生成完成\n"
                    f"· 摘要：{summary_preview}...\n"
                    f"· 处置建议：{advice_count} 条"
                ),
                "result_summary": {
                    "处置建议数": str(advice_count),
                },
            }

        # ── Step 7: Persist ──
        yield {
            "step": "persist", "status": "running",
            "thinking": (
                "Agent 将分析结果持久化到三层存储：\n"
                "① MySQL：dwd_clean_intel + dwd_intel_analysis + dwd_entity + agent_report\n"
                "② Neo4j：创建实体节点 + 关系边 + 共现关联\n"
                "③ Milvus：文本向量写入 intel_embeddings 集合"
            ),
        }
        state = self._state_persist(state)
        yield {
            "step": "persist", "status": "done",
            "thinking": (
                f"持久化完成 → raw_id={state['raw_id']}\n"
                f"MySQL: 分析记录 + {len(entities)} 个实体 + 报告\n"
                f"Neo4j: 实体节点 + 关系边 + 共现关联\n"
                f"Milvus: 文本向量已写入"
            ),
        }

        # Build final result
        final_result = self._build_response(state)

        # Final step includes the complete result for the UI
        yield {
            "step": "done",
            "status": "done",
            "thinking": (
                f"研判全流程结束。\n"
                f"最终结论：「{state['risk_label']}」"
                + (f"（{state['risk_sub_label']}）" if state.get('risk_sub_label') else "") +
                f"，风险评分 {state['risk_score']:.2f}（{level_cn.get(state['risk_level'], state['risk_level'])}）\n"
                f"共调用工具：{ran_tools if ran_tools else ['graph_expand', 'slang_normalize', 'dedup_check']}\n"
                f"结果已持久化至 MySQL + Neo4j + Milvus"
            ),
            "result": final_result,
            "final": True,
        }

    # ── State: Init ───────────────────────────────────────────────────────

    def _init_state(self, raw_data_id: int, text: str, platform: str) -> dict:
        return {
            "raw_id": raw_data_id,
            "clean_text": text,
            "platform": platform,
            "risk_label": "",
            "risk_sub_label": "",
            "risk_score": 0.0,
            "risk_level": "normal",
            "classification_confidence": 0.0,
            "classification_method": "",
            "evidence_spans": [],
            "entities": [],
            "slang_terms": [],
            "new_slang_candidates": [],
            "graph_result": {},
            "similar_intel_ids": [],
            "agent_summary": "",
            "disposal_advice": [],
            "tool_log": [],
            "enable_graph_expand": True,
            "enable_report": True,
            "enable_llm": True,
            "_embed_fn": self._embed_fn,
        }

    # ── State: Classify ───────────────────────────────────────────────────

    def _state_classify(self, state: dict) -> dict:
        """L1→L2→L3 cascade with circuit breaker."""
        enable_llm = state.get("enable_llm", True)
        if self._circuit_open or not enable_llm:
            logger.warning("Circuit breaker OPEN — using L1+L2 fallback")
            result = self._run_classify(state["clean_text"], skip_llm=True)
            if self._circuit_open:
                result["method"] = self.DEGRADED_METHOD
        else:
            try:
                result = self._run_classify_with_retry(state["clean_text"])
                self._llm_failure_count = 0
            except Exception as exc:
                self._llm_failure_count += 1
                logger.error(f"LLM classification failed ({self._llm_failure_count}/"
                             f"{self.CIRCUIT_THRESHOLD}): {exc}")
                if self._llm_failure_count >= self.CIRCUIT_THRESHOLD:
                    self._circuit_open = True
                    logger.critical("CIRCUIT BREAKER OPENED")
                result = self._run_classify(state["clean_text"], skip_llm=True)
                result["method"] = self.DEGRADED_METHOD

        label = result["intent_label"]
        state["risk_label"] = label.value if hasattr(label, "value") else str(label)
        state["risk_sub_label"] = result.get("sub_label", "")
        state["classification_confidence"] = float(result.get("confidence", 0.5))
        state["classification_method"] = result.get("method", "")
        return state

    def _run_classify(self, text: str, skip_llm: bool = False) -> dict:
        from analyzer.classifier import classifier as _classifier
        return _classifier.classify(text, skip_llm=skip_llm)

    def _run_classify_with_retry(self, text: str) -> dict:
        if self._tenacity_available():
            import tenacity
            fn = tenacity.retry(
                stop=tenacity.stop_after_attempt(3),
                wait=tenacity.wait_exponential(multiplier=2.0, min=1, max=30),
                retry=tenacity.retry_if_exception_type(Exception),
                reraise=True)(lambda: self._run_classify(text, skip_llm=False))
        else:
            fn = lambda: self._run_classify(text, skip_llm=False)
        return fn()

    # ── State: Extract Entities ───────────────────────────────────────────

    def _state_extract_entities(self, state: dict) -> dict:
        """Extract entities with degradation support."""
        text = state["clean_text"]
        intent_label = state["risk_label"]
        classification_confidence = state.get("classification_confidence", 0.0)

        try:
            from analyzer.entity_extractor import EntityExtractor
            extractor = EntityExtractor()
            pre_entities = []
            pre_entities.extend(extractor.extract_regex(text))
            pre_entities.extend(extractor.extract_dict(text))
            pre_types = set()
            for ent in pre_entities:
                etype = ent.get("entity_type", "")
                pre_types.add(etype.value if hasattr(etype, "value") else str(etype))
            high_value_hit = pre_types & {
                "wechat", "qq", "phone", "url", "domain", "bank_card", "alipay",
                "email", "crypto_wallet", "slang", "tool",
            }
            if classification_confidence >= 0.8 and len(high_value_hit) >= 2:
                entities = pre_entities
                state["tool_log"].append({
                    "tool": "entity_extract",
                    "decision": "fast_path",
                    "reason": "regex/dict high confidence; embedding and LLM skipped",
                })
            else:
                self._load_embedding_model()
                state["_embed_fn"] = self._embed_fn
                enable_llm = state.get("enable_llm", True)
                if self._circuit_open or not enable_llm:
                    entities = extractor.extract_l1_l2_only(
                        text, embed_fn=self._embed_fn, intent_label=intent_label)
                elif self._tenacity_available():
                    import tenacity
                    fn = tenacity.retry(
                        stop=tenacity.stop_after_attempt(2),
                        wait=tenacity.wait_exponential(multiplier=1.5, min=1, max=15),
                        retry=tenacity.retry_if_exception_type(Exception),
                        reraise=True)(lambda: extractor.extract(
                        text, embed_fn=self._embed_fn, intent_label=intent_label,
                        classification_confidence=classification_confidence))
                    entities = fn()
                else:
                    entities = extractor.extract(
                        text, embed_fn=self._embed_fn, intent_label=intent_label,
                        classification_confidence=classification_confidence)
        except Exception as exc:
            logger.warning(f"LLM entity extraction failed, using L1+L2: {exc}")
            from analyzer.entity_extractor import EntityExtractor
            extractor = EntityExtractor()
            entities = extractor.extract_l1_l2_only(
                text, embed_fn=self._embed_fn, intent_label=intent_label)

        # Deduplicate
        seen = set()
        deduped = []
        for ent in entities:
            etype = ent.get("entity_type", "")
            etype_str = etype.value if hasattr(etype, "value") else str(etype)
            key = (etype_str, ent.get("entity_value", ""))
            if key not in seen:
                seen.add(key)
                deduped.append(ent)

        state["entities"] = deduped
        state["new_slang_candidates"] = self._detect_new_slang_candidates(state, deduped)
        return state

    # ── State: Decide Tools (Autonomous Decision Node) ────────────────────

    def _state_decide_tools(self, state: dict) -> dict:
        """Autonomously decide which tools to run based on extracted entities.

        Decision rules:
        1. GraphExpand — if expandable entities (wechat, qq, phone, url, etc.) are found
        2. SlangNormalize — if slang entities are detected
        3. DedupCheck — if classification confidence ≥ 0.6
        """
        entities = state.get("entities", [])
        enable_graph = state.get("enable_graph_expand", True)

        # Tool 1: Graph Expand
        state = self.tools["graph_expand"].run(state, enable_graph=enable_graph)

        # Tool 2: Slang Normalize
        state = self.tools["slang_normalize"].run(state)

        # Tool 3: Dedup Check
        state["_embed_fn"] = self._embed_fn
        state = self.tools["dedup_check"].run(state)

        return state

    # ── State: Extract Evidence ───────────────────────────────────────────

    def _state_extract_evidence(self, state: dict) -> dict:
        text = state["clean_text"]
        risk_label = state["risk_label"]
        risk_sub_label = state.get("risk_sub_label", "")
        entities = state["entities"]

        try:
            from analyzer.evidence_extractor import evidence_extractor
            evidence = evidence_extractor.extract(
                text=text,
                risk_label=risk_label,
                entities=entities,
                risk_sub_label=risk_sub_label,
                enable_llm=state.get("enable_llm", True) and not self._circuit_open)
        except Exception as exc:
            logger.warning(f"Evidence extraction failed, using entity context: {exc}")
            from analyzer.evidence_extractor import evidence_extractor
            evidence = evidence_extractor.extract_entity_context(text, entities)

        state["evidence_spans"] = evidence
        return state

    @staticmethod
    def _detect_new_slang_candidates(state: dict, entities: list[dict]) -> list[dict]:
        """Find slang-like terms discovered by embedding/LLM that are not active dict terms."""
        known_terms = set()
        try:
            from storage.mysql_store import mysql as _mysql
            known_terms = {row.get("term") for row in _mysql.list_slang("active") if row.get("term")}
        except Exception as exc:
            logger.debug(f"Active slang lookup skipped: {exc}")

        text = state.get("clean_text", "")
        risk_label = state.get("risk_label", "")
        candidates = []
        seen = set()
        for ent in entities:
            etype = ent.get("entity_type", "")
            etype_str = etype.value if hasattr(etype, "value") else str(etype)
            if etype_str != "slang":
                continue
            term = (ent.get("entity_value") or "").strip()
            if not term or term in known_terms or term in seen:
                continue
            if len(term) < 2 or len(term) > 16:
                continue

            method = ent.get("extraction_method", "")
            method_str = method.value if hasattr(method, "value") else str(method)
            metadata = ent.get("metadata") or {}
            if method_str == "dict":
                continue
            if method_str not in {"embedding", "llm"} and not metadata.get("is_new_slang_candidate"):
                continue

            evidence = ent.get("context") or ""
            if not evidence:
                idx = text.find(term)
                evidence = text[max(0, idx - 24): idx + len(term) + 24] if idx >= 0 else text[:120]
            meaning = (
                metadata.get("candidate_meaning")
                or metadata.get("meaning")
                or ent.get("normalized_value")
                or ent.get("context")
                or "待人工确认"
            )
            reason = metadata.get("candidate_reason")
            if not reason:
                reason = "命中向量相似黑话" if method_str == "embedding" else "LLM从上下文中识别出的疑似黑话"

            candidates.append({
                "term": term,
                "suggested_meaning": meaning,
                "risk_category": risk_label,
                "confidence": float(ent.get("confidence") or metadata.get("similarity") or 0.6),
                "evidence": evidence,
                "reason": reason,
                "source": f"{method_str}_candidate",
                "raw_id": state.get("raw_id"),
            })
            seen.add(term)
        return candidates

    # ── State: Risk Score ─────────────────────────────────────────────────

    def _state_risk_score(self, state: dict) -> dict:
        try:
            from analyzer.risk_scorer import risk_scorer
            cls_result = {
                "intent_label": state["risk_label"],
                "sub_label": state["risk_sub_label"],
                "confidence": state["classification_confidence"],
                "method": state["classification_method"],
            }
            scores = risk_scorer.score(
                classification=cls_result,
                entities=state["entities"],
                graph_result=state["graph_result"],
                slang_terms=state["slang_terms"])
            state["risk_score"] = scores["final_score"]
            state["risk_level"] = scores["risk_level"]
        except Exception as exc:
            logger.warning(f"Risk scoring failed: {exc}")
            state["risk_score"] = float(state.get("classification_confidence", 0.5))
            state["risk_level"] = "high" if state["risk_score"] >= 0.65 else "normal"

        return state

    # ── State: Generate Report ────────────────────────────────────────────

    def _state_generate_report(self, state: dict) -> dict:
        if not state.get("enable_report", True):
            return state

        try:
            from agents.report_agent import report_agent
            facts = self._build_facts(state)
            report = report_agent.generate_rule_based(facts)
            state["agent_summary"] = report.get("conclusion", "")
            state["disposal_advice"] = report.get("disposal_advice", [])
        except Exception as exc:
            logger.warning(f"Report generation skipped: {exc}")

        return state

    # ── State: Persist ────────────────────────────────────────────────────

    def _state_persist(self, state: dict) -> dict:
        raw_id = state["raw_id"]
        platform = state["platform"]
        text = state["clean_text"]
        entities = state["entities"]
        evidence = state["evidence_spans"]
        graph_result = state["graph_result"]

        intent_label = state["risk_label"]
        risk_level = state["risk_level"]

        def _mysql():
            from storage.mysql_store import mysql as m
            return m

        # MySQL: clean intel
        simhash_val = hashlib.md5(text.encode()).hexdigest()[:16]
        _mysql().insert_clean_intel(raw_id, clean_text=text, simhash=simhash_val)

        # MySQL: analysis
        analysis_id = _mysql().insert_analysis({
            "raw_id": raw_id,
            "risk_label": intent_label,
            "risk_sub_label": state["risk_sub_label"],
            "risk_score": state["risk_score"],
            "risk_level": risk_level,
            "classification_method": state["classification_method"],
            "evidence_spans": evidence,
            "analysis_status": "CLASSIFIED",
        })
        state["analysis_id"] = analysis_id

        # MySQL: entities
        _mysql().delete_entities_for_raw(raw_id)
        for ent in entities:
            etype = ent["entity_type"]
            etype_str = etype.value if hasattr(etype, "value") else str(etype)
            _mysql().insert_entity({
                "raw_id": raw_id,
                "entity_type": etype_str,
                "entity_value": ent["entity_value"],
                "extract_method": str(ent.get("extraction_method", "degraded")),
                "context": ent.get("context", ""),
                "confidence": ent.get("confidence", 0.9),
                "start_offset": ent.get("start", -1),
                "end_offset": ent.get("end", -1),
            })

        # MySQL: model-discovered slang candidates for HITL review.
        for candidate in state.get("new_slang_candidates", []):
            try:
                _mysql().upsert_slang_candidate(candidate)
            except Exception as exc:
                logger.warning(
                    f"Slang candidate persist failed [{raw_id}:{candidate.get('term')}]: {exc}"
                )

        # MySQL: raw status
        _mysql().update_raw_status(raw_id, "ANALYZED", clean_text=text, simhash=simhash_val)

        # MySQL: report
        if state.get("agent_summary"):
            _mysql().insert_report({
                "raw_id": raw_id,
                "case_id": graph_result.get("case_id", ""),
                "report_type": "intel_analysis",
                "title": f"风险研判报告 — {intent_label}",
                "summary": state["agent_summary"],
                "evidence_json": evidence,
                "entities_json": [
                    {"type": (e["entity_type"].value if hasattr(e["entity_type"], "value")
                              else str(e["entity_type"])),
                     "value": e["entity_value"]}
                    for e in entities
                ],
                "graph_json": graph_result,
                "disposal_advice": state.get("disposal_advice", []),
                "generated_by": "agent_state_machine",
            })

        # MySQL: risk case (gang only)
        if graph_result.get("is_gang_related"):
            _mysql().upsert_risk_case(
                case_id=graph_result["case_id"],
                case_name=f"团伙案件 — {graph_result.get('case_id', '')}",
                main_risk_type=intent_label,
                risk_level=risk_level if risk_level in ("high", "critical") else "high",
                summary=state.get("agent_summary", "")[:500],
                key_entities=json.dumps(
                    [{"type": (e["entity_type"].value if hasattr(e["entity_type"], "value")
                              else str(e["entity_type"])),
                      "value": e["entity_value"]}
                     for e in entities[:20]],
                    ensure_ascii=False),
                related_intel_count=graph_result.get("related_entities_count", 0),
                first_seen=graph_result.get("first_seen"),
                last_seen=graph_result.get("last_seen"))

        # Neo4j
        self._sync_neo4j(raw_id, platform, text, entities)

        # Milvus
        try:
            if self._embed_fn:
                vec = self._embed_fn(text)
                text_hash = hashlib.md5(text.encode()).hexdigest()
                from storage.milvus_store import milvus
                milvus.insert_intel(raw_id, text_hash, vec)
        except Exception as exc:
            logger.warning(f"Milvus insert failed [{raw_id}]: {exc}")

        # Doris OLAP
        try:
            from config.settings import settings
            if not settings.doris_enabled:
                state.setdefault("tool_log", []).append({
                    "tool": "doris_sync",
                    "decision": "skipped",
                    "reason": "Doris disabled",
                })
                return state
            from storage.doris_store import doris
            collect_time = None
            source_url = ""
            author_id = ""
            source_channel = ""
            from storage.mysql_store import mysql as _m
            with _m.cursor() as c:
                c.execute(
                    "SELECT collect_time, source_url, author_id, source_channel FROM ods_raw_intel WHERE id=%s",
                    (raw_id))
                row = c.fetchone()
                if row:
                    collect_time = row.get("collect_time")
                    source_url = row.get("source_url") or ""
                    author_id = row.get("author_id") or ""
                    source_channel = row.get("source_channel") or ""
            doris.insert_analysis({
                "raw_id": raw_id,
                "platform": platform,
                "source_url": source_url,
                "author_id": author_id,
                "source_channel": source_channel,
                "collect_time": collect_time,
                "risk_label": intent_label,
                "risk_sub_label": state["risk_sub_label"],
                "risk_score": state["risk_score"],
                "risk_level": risk_level,
                "classification_method": state["classification_method"],
                "entities": entities,
                "slang_terms": state.get("slang_terms", []),
                "evidence_spans": evidence,
                "graph_result": graph_result,
                "is_gang_related": graph_result.get("is_gang_related"),
                "disposal_advice": state.get("disposal_advice", []),
                "agent_summary": state.get("agent_summary", ""),
                "clean_text": text,
            })
        except Exception as exc:
            logger.warning(f"Doris insert failed [{raw_id}]: {exc}")

        return state

    # ── Build Facts for Report ────────────────────────────────────────────

    @staticmethod
    def _build_facts(state: dict) -> dict:
        return {
            "raw_id": state["raw_id"],
            "platform": state["platform"],
            "text": state["clean_text"],
            "risk": {
                "label": state["risk_label"],
                "sub_label": state["risk_sub_label"],
                "score": state["risk_score"],
                "level": state["risk_level"],
                "method": state["classification_method"],
            },
            "evidence": state["evidence_spans"],
            "entities": [
                {
                    "type": (e["entity_type"].value if hasattr(e["entity_type"], "value")
                             else str(e["entity_type"])),
                    "value": e["entity_value"],
                    "method": str(e.get("extraction_method", "")),
                }
                for e in state["entities"]
            ],
            "slang_terms": state["slang_terms"],
            "new_slang_candidates": state.get("new_slang_candidates", []),
            "graph": state["graph_result"],
        }

    # ── Build Response ────────────────────────────────────────────────────

    @staticmethod
    def _build_response(state: dict) -> dict:
        return {
            "raw_id": state["raw_id"],
            "clean_text": state["clean_text"],
            "risk_label": state["risk_label"],
            "risk_sub_label": state["risk_sub_label"],
            "risk_score": state["risk_score"],
            "risk_level": state["risk_level"],
            "evidence_spans": state["evidence_spans"],
            "entities": state["entities"],
            "slang_terms": state["slang_terms"],
            "new_slang_candidates": state.get("new_slang_candidates", []),
            "graph_result": state["graph_result"],
            "agent_summary": state["agent_summary"],
            "disposal_advice": state["disposal_advice"],
            "tool_log": state["tool_log"],
            "analysis_id": state.get("analysis_id"),
        }

    # ── Neo4j Sync ────────────────────────────────────────────────────────

    @staticmethod
    def _sync_neo4j(raw_data_id: int, platform: str, text: str, entities: list[dict]):
        try:
            from storage.neo4j_store import neo4j as neo
            neo.upsert_intel(raw_data_id, platform, text[:200])

            for ent in entities:
                etype = ent["entity_type"]
                etype_str = etype.value if hasattr(etype, "value") else str(etype)
                neo.upsert_entity_refined(etype_str, ent["entity_value"])
                neo.link_entity_to_intel_refined(etype_str, ent["entity_value"], raw_data_id)

            for i in range(len(entities)):
                for j in range(i + 1, len(entities)):
                    et_i = entities[i]["entity_type"]
                    et_j = entities[j]["entity_type"]
                    et_i_str = et_i.value if hasattr(et_i, "value") else str(et_i)
                    et_j_str = et_j.value if hasattr(et_j, "value") else str(et_j)
                    neo.link_co_occurrence_refined(
                        et_i_str, entities[i]["entity_value"],
                        et_j_str, entities[j]["entity_value"],
                        raw_data_id)
        except Exception as exc:
            logger.error(f"Neo4j sync failed [{raw_data_id}]: {exc}")

    # ── Helpers ───────────────────────────────────────────────────────────

    def _load_embedding_model(self):
        if self._embed_fn is not None:
            return
        from sentence_transformers import SentenceTransformer
        from config.settings import settings
        model = SentenceTransformer(settings.embedding_model_name)
        self._embed_fn = lambda text: model.encode(text).tolist()
        logger.info("Embedding model loaded")

    @staticmethod
    def _tenacity_available() -> bool:
        try:
            import tenacity
            return True
        except ImportError:
            return False

    # ── Health ────────────────────────────────────────────────────────────

    @property
    def is_degraded(self) -> bool:
        return self._circuit_open

    def reset_circuit(self):
        self._circuit_open = False
        self._llm_failure_count = 0
        logger.info("Circuit breaker reset")


# Singleton
agent = AnalysisAgent()
