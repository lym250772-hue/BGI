"""Evidence span extraction — find and explain WHY the system made its classification.

According to PROJECT_PLAN.md Step 7:
    "All Agent conclusions MUST carry evidence spans.
     Conclusions without evidence cannot be shown as high-confidence."

Three-channel extraction:
    1. Rule-based: match risk-type-specific keyword patterns in text
    2. Entity-context: extract surrounding sentence for each extracted entity
    3. LLM: explain why each span is suspicious (only when L1+L2 alone aren't enough)
"""

import re
import json
from loguru import logger

from config.settings import settings


# ---------------------------------------------------------------------------
# Risk-type → suspicious-pattern mapping
# ---------------------------------------------------------------------------

RISK_PATTERNS: dict[str, list[tuple[str, str, str]]] = {
    "直播违规": [
        ("无人直播", "直播违规", "使用自动化/录播/数字人进行非真实直播"),
        ("数字人.{0,5}(直播|带货)", "直播违规", "使用AI数字人代替真人直播带货"),
        ("(录播|挂播|循环).{0,3}直播", "直播违规", "以录播视频冒充实时直播"),
        ("(挂机|矩阵).{0,3}(直播|号)", "直播违规", "批量操控账号进行无人直播"),
        ("AI.{0,3}(直播|数字人)", "直播违规", "AI技术用于生成虚假直播内容"),
    ],
    "诈骗": [
        ("刷单.{0,5}(返利|返现|佣金)", "诈骗", "以刷单返利为名骗取钱财"),
        ("(日赚|日结|时薪).{0,5}\d{2,4}", "诈骗", "高薪兼职诱饵，常见刷单诈骗前置手段"),
        ("(无抵押|秒批|黑户).{0,3}贷", "诈骗", "虚假贷款广告，骗取手续费或个人信息"),
        ("(恭喜|中奖).{0,5}(领取|填写)", "诈骗", "虚假中奖通知，诱导填写个人信息"),
        ("(保证金|押金|解冻费).{0,5}(缴纳|交)", "诈骗", "以各种费用名义骗取钱财"),
        ("(征信|洗白|修复).{0,5}(信用|征信)", "诈骗", "征信修复骗局，收取服务费后失联"),
    ],
    "引流": [
        ("加.{0,3}(微信|QQ|薇信|V信|wx)", "引流", "引导用户添加站外联系方式"),
        ("(私信|主页|简介).{0,5}(有|看|联系)", "引流", "引导用户查看主页或私信，规避平台审核"),
        ("(菠菜|博彩|百家乐|真人视讯|棋牌)", "引流", "引导至赌博平台"),
        ("(色流|约炮|裸聊|招嫖|成人)", "引流", "色情内容引流"),
        ("(进群|加群|私域).{0,5}\d{5,}", "引流", "引导加入QQ群/微信群进行二次转化"),
    ],
    "作弊": [
        ("(刷.{0,2}(播放|点赞|粉丝|评论|销量))", "作弊", "通过虚假操作提升数据指标"),
        ("(薅羊毛|撸货|套券|新人券)", "作弊", "利用平台规则漏洞获取不当利益"),
        ("(外挂|辅助|脚本|透视|自瞄|科技)", "作弊", "使用作弊软件获取不正当优势"),
        ("(自动化|全自动|批量).{0,3}(操作|下单|抢)", "作弊", "自动化工具进行批量操作"),
    ],
    "账号黑产": [
        ("(出|卖|售|收).{0,4}(号|账号|白号|老号)", "账号黑产", "账号买卖行为"),
        ("(接码|猫池|打码|验证码.{0,3}(接|收))", "账号黑产", "使用接码平台绕过实名验证"),
        ("(撞库|扫号|洗号|盗号|脱库)", "账号黑产", "通过技术手段获取他人账号"),
        ("(实名|过人脸|过认证).{0,5}(服务|技术)", "账号黑产", "提供虚假实名认证服务"),
        ("(批量注册|日出).{0,4}(号|千号|万号)", "账号黑产", "批量注册平台账号"),
    ],
    "工具交易": [
        ("(出售|购买|交易).{0,4}(数据|名单|信息|料子)", "工具交易", "交易个人隐私数据"),
        ("(接码平台|发卡平台|卡密|黑卡)", "工具交易", "提供黑产基础设施服务"),
        ("(代理IP|IP代理|IP池|代理池)", "工具交易", "提供IP代理服务用于规避风控"),
        ("(云手机|群控|一机.{0,2}控)", "工具交易", "提供群控设备或云手机服务"),
        ("(脚本|插件|工具包).{0,4}(下载|出售|购买)", "工具交易", "交易黑产自动化工具"),
    ],
    "内容违规": [
        ("(裸|黄片|AV|色情|福利姬|约炮|招嫖)", "内容违规", "发布色情低俗内容"),
        ("(枪支|毒品|假币|伪基站)", "内容违规", "发布违法危险物品信息"),
        ("(谣言|造谣|假新闻)", "内容违规", "传播虚假信息"),
    ],
}

# All risk patterns flattened for quick scanning
_ALL_PATTERNS: list[tuple[re.Pattern, str, str]] = []
for _label, _patterns in RISK_PATTERNS.items():
    for _pat, _risk_point, _reason in _patterns:
        _ALL_PATTERNS.append((re.compile(_pat), _risk_point, _reason))


# ---------------------------------------------------------------------------
# Entity-type → risk dimension mapping
# ---------------------------------------------------------------------------

ENTITY_RISK_MAP = {
    "wechat": "站外导流",
    "qq": "站外导流",
    "phone": "联系方式暴露",
    "url": "外链分发",
    "domain": "外链分发",
    "ip": "基础设施暴露",
    "bank_card": "资金链路",
    "alipay": "资金链路",
    "tool": "工具交易",
    "slang": "黑话风险",
    "feature": "风险特征",
}


class EvidenceExtractor:
    """Extract evidence spans from text to justify classification decisions."""

    # ------------------------------------------------------------------
    # Channel 1: Rule-based keyword matching
    # ------------------------------------------------------------------

    def extract_by_rules(self, text: str, risk_label: str = "") -> list[dict]:
        """Find risk-indicating spans using keyword patterns for the given risk label."""
        evidence = []
        patterns = RISK_PATTERNS.get(risk_label, [])
        if not patterns:
            # Fall back to all patterns if specific risk label not found
            patterns_list = _ALL_PATTERNS
        else:
            patterns_list = [(re.compile(p), rp, rs) for p, rp, rs in patterns]

        seen_positions = set()
        for pattern, risk_point, reason in patterns_list:
            for match in pattern.finditer(text):
                span = match.group(0)
                start, end = match.start(), match.end()
                # Avoid overlapping matches
                if any(start <= p[1] and end >= p[0] for p in seen_positions):
                    continue
                seen_positions.add((start, end))
                evidence.append({
                    "text": span,
                    "start": start,
                    "end": end,
                    "risk_point": risk_point,
                    "reason": reason,
                    "confidence": 0.92,
                    "method": "rule",
                })

        return evidence

    # ------------------------------------------------------------------
    # Channel 2: Entity-context spans
    # ------------------------------------------------------------------

    def extract_entity_context(self, text: str, entities: list[dict]) -> list[dict]:
        """For each extracted entity, capture its surrounding context as evidence."""
        evidence = []
        seen_spans = set()

        for ent in entities:
            etype = ent.get("entity_type", "")
            # Get entity_type as string
            etype_str = etype.value if hasattr(etype, "value") else str(etype)
            evalue = ent.get("entity_value", "")
            context = ent.get("context", "")

            risk_point = ENTITY_RISK_MAP.get(etype_str, "实体线索")

            if not evalue:
                continue

            # If we have a context snippet, use it
            if context:
                span_text = context
                # Verify the entity value IS in the context
                if evalue not in span_text:
                    span_text = f"...{evalue}..."
            else:
                # Extract sentence containing the entity
                idx = text.find(evalue)
                if idx == -1:
                    continue
                left = max(0, idx - 30)
                right = min(len(text), idx + len(evalue) + 30)
                span_text = text[left:right]

            span_key = (span_text[:40], risk_point)
            if span_key in seen_spans:
                continue
            seen_spans.add(span_key)

            evidence.append({
                "text": span_text.strip(),
                "start": max(0, text.find(evalue)) if evalue in text else -1,
                "end": text.find(evalue) + len(evalue) if evalue in text else -1,
                "risk_point": risk_point,
                "reason": f"提取到{etype_str}实体: {evalue}",
                "confidence": 0.90,
                "method": "entity_context",
            })

        return evidence

    # ------------------------------------------------------------------
    # Channel 3: LLM explanation (for ambiguous spans)
    # ------------------------------------------------------------------

    def explain_with_llm(self, text: str, risk_label: str,
                         spans: list[dict]) -> list[dict]:
        """Use LLM to explain WHY specific text spans indicate risk.

        Only called for spans marked as 'llm_candidate' or when rule confidence < 0.7.
        """
        if not spans:
            return spans

        # Filter to spans that need explanation
        candidates = [s for s in spans if s.get("confidence", 1.0) < 0.70]
        if not candidates:
            return spans

        prompt = f"""你是黑灰产情报分析专家。

情报文本：{text[:2000]}
风险分类：{risk_label}

以下是从文本中定位到的可疑片段，请为每个片段解释为什么它与"{risk_label}"相关：

{json.dumps([{{"text": s["text"], "risk_point": s.get("risk_point", "")}} for s in candidates], ensure_ascii=False, indent=2)}

请仅返回JSON数组，每个元素包含 text（与输入一致）、reason（一句话解释）、confidence（0.0~1.0）：
[{{"text": "...", "reason": "...", "confidence": 0.85}}]"""

        try:
            from openai import OpenAI
            client = OpenAI(api_key=settings.llm_api_key, base_url=settings.llm_api_base)
            resp = client.chat.completions.create(
                model=settings.llm_model,
                messages=[{"role": "user", "content": prompt}],
                temperature=0.1,
                max_tokens=800,
            )
            explanations = json.loads(resp.choices[0].message.content)

            # Map explanations back to original spans
            explain_map = {e["text"]: e for e in explanations if "text" in e}
            for span in spans:
                if span["text"] in explain_map:
                    expl = explain_map[span["text"]]
                    span["reason"] = expl.get("reason", span["reason"])
                    span["confidence"] = expl.get("confidence", span["confidence"])
                    span["method"] = "rule_plus_llm"
            return spans
        except Exception as exc:
            logger.warning(f"LLM evidence explanation failed: {exc}")
            return spans

    # ------------------------------------------------------------------
    # Entry point
    # ------------------------------------------------------------------

    def extract(self, text: str, risk_label: str = "",
                entities: list[dict] = None,
                risk_sub_label: str = "",
                enable_llm: bool = True) -> list[dict]:
        """Extract all evidence spans justifying the classification.

        Args:
            text: Cleaned intelligence text
            risk_label: Primary risk label (诈骗/引流/作弊/...)
            entities: Already-extracted entities from EntityExtractor
            risk_sub_label: Sub-label for finer matching
            enable_llm: Whether to use LLM for explanation (degradation support)

        Returns:
            List of evidence span dicts with text/start/end/risk_point/reason/confidence/method
        """
        entities = entities or []

        # Channel 1: Rule-based keyword matching
        rule_evidence = self.extract_by_rules(text, risk_label)

        # Channel 2: Entity context
        entity_evidence = self.extract_entity_context(text, entities)

        # Merge, deduplicate by text overlap
        all_evidence = self._merge_dedup(rule_evidence + entity_evidence)

        # Channel 3: LLM explanation for low-confidence spans
        if enable_llm:
            try:
                all_evidence = self.explain_with_llm(text, risk_label, all_evidence)
            except Exception:
                pass  # degradation: keep rule-based evidence

        # Validate: every evidence.text MUST be findable in original text
        all_evidence = self._validate(all_evidence, text)

        # Sort by confidence descending
        all_evidence.sort(key=lambda x: x.get("confidence", 0), reverse=True)

        return all_evidence

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _merge_dedup(evidence: list[dict]) -> list[dict]:
        """Merge overlapping evidence spans, keep the one with higher confidence."""
        if not evidence:
            return []
        # Sort by start position
        evidence.sort(key=lambda x: (x.get("start", 0), -(x.get("confidence", 0))))
        merged = []
        for e in evidence:
            # Check overlap with last added
            if merged:
                last = merged[-1]
                if (e.get("start", 0) <= last.get("end", 0) and
                        e.get("end", 0) >= last.get("start", 0)):
                    # Overlapping — keep higher confidence
                    if e.get("confidence", 0) > last.get("confidence", 0):
                        merged[-1] = e
                    continue
            merged.append(e)
        return merged

    @staticmethod
    def _validate(evidence: list[dict], text: str) -> list[dict]:
        """Ensure every evidence.text exists in the original text."""
        valid = []
        for e in evidence:
            span_text = e.get("text", "")
            if span_text and span_text in text:
                valid.append(e)
            elif span_text:
                # Try partial match — check if most of it is in text
                words = span_text.split()
                found = sum(1 for w in words if w in text)
                if found >= max(1, len(words) * 0.6):
                    valid.append(e)
                else:
                    logger.debug(f"Evidence span not found in text: {span_text[:60]}...")
        return valid


# ---------------------------------------------------------------------------
# Singleton
# ---------------------------------------------------------------------------

evidence_extractor = EvidenceExtractor()
