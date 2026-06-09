"""Three-level cascade intent classifier: keyword → RoBERTa → LLM."""
import re
import yaml
from pathlib import Path
from loguru import logger

from schema import IntentLabel, SUBLABEL_MAP, ClassificationMethod
from config.settings import settings

# ── IntentLabel name → enum member mapping for YAML lookup ──
_LABEL_NAME_MAP = {lbl.value: lbl for lbl in IntentLabel}

# Default built-in rules (fallback if YAML is missing or malformed)
_BUILTIN_RULES: list[tuple[re.Pattern, tuple[str, str]]] = [
    # 诈骗
    (re.compile(r"代办.{0,5}(贷款|信用卡|签证)"), ("诈骗", "金融诈骗")),
    (re.compile(r"(无抵押|秒批|黑户).{0,3}贷"), ("诈骗", "金融诈骗")),
    (re.compile(r"(恭喜|中奖).{0,5}(领取|填写)"), ("诈骗", "虚假中奖")),
    # 引流
    (re.compile(r"(加.{0,3}[Qq薇微信]).{0,5}(看|视频|私密|福利)"), ("引流", "色情引流")),
    (re.compile(r"[Qq薇微信]{1,2}.*\d{5,}"), ("引流", "站外导流")),
    (re.compile(r"(菠菜|博彩|百家乐|真人视讯)"), ("引流", "赌博引流")),
    # 作弊
    (re.compile(r"(刷|提升).{0,3}(播放量|点赞|粉丝|销量|评论)"), ("作弊", "刷量刷单")),
    (re.compile(r"(薅羊毛|撸货|套券|新人券)"), ("作弊", "营销套利")),
    (re.compile(r"(外挂|辅助|脚本|透视|自瞄)"), ("作弊", "游戏外挂")),
    # 账号黑产
    (re.compile(r"(出|卖|售|收).{0,4}(号|账号)"), ("账号黑产", "账号买卖")),
    (re.compile(r"(接码|猫池|打码|验证码.{0,3}接收)"), ("账号黑产", "批量注册/养号")),
    (re.compile(r"(撞库|扫号|洗号|盗号)"), ("账号黑产", "撞库盗号")),
    # 内容违规
    (re.compile(r"(裸|黄片|AV|色情|福利姬|约炮)"), ("内容违规", "色情低俗")),
    # 工具交易
    (re.compile(r"(接码平台|发卡平台|卡密|黑卡)"), ("工具交易", "黑卡/接码")),
    (re.compile(r"(出售|购买).{0,4}(数据|名单|信息)"), ("工具交易", "数据买卖")),
    # 支付洗钱
    (re.compile(r"(跑分|代收|通道|四方支付)"), ("支付洗钱", "支付洗钱")),
    # 直播违规
    (re.compile(r"(数字人|无人直播|录播).{0,4}(带货|直播)"), ("直播违规", "数字人欺诈")),
    (re.compile(r"(挂机|挂播|循环).{0,3}直播"), ("直播违规", "无人直播")),
]

_RULES_YAML_PATH = Path(__file__).resolve().parent.parent / "config" / "risk_rules.yaml"


def _build_rules_from_yaml(yaml_data: dict) -> list[tuple[re.Pattern, tuple[str, str]]]:
    """Build compiled regex rules from YAML rule definitions."""
    rules: list[tuple[re.Pattern, tuple[str, str]]] = []
    for category, cfg in yaml_data.items():
        if not isinstance(cfg, dict):
            continue
        # Regex patterns
        for pat in cfg.get("regex", []):
            try:
                rules.append((re.compile(pat), (category, category)))
            except re.error as exc:
                logger.warning(f"Invalid regex in YAML rules [{category}]: {pat} — {exc}")
        # Plain keywords
        for kw in cfg.get("keywords", []):
            esc = re.escape(kw)
            rules.append((re.compile(esc), (category, category)))
        # Variant keywords (拼音/谐音)
        for v in cfg.get("variants", []):
            esc = re.escape(v)
            rules.append((re.compile(esc), (category, category)))
        # Combo rules (all keywords must be present in text)
        for combo in cfg.get("combos", []):
            try:
                lookaheads = "".join(f"(?=.*{re.escape(k)})" for k in combo)
                rules.append((re.compile(f"^{lookaheads}", re.DOTALL), (category, "高危组合")))
            except re.error as exc:
                logger.warning(f"Invalid combo in YAML [{category}]: {combo} — {exc}")
    return rules


def _load_rules() -> list[tuple[re.Pattern, tuple[str, str]]]:
    """Load rules from YAML config, falling back to built-in rules."""
    if not _RULES_YAML_PATH.exists():
        logger.warning(f"YAML rules file not found: {_RULES_YAML_PATH}, using built-in rules")
        return _BUILTIN_RULES
    try:
        with open(_RULES_YAML_PATH, "r", encoding="utf-8") as f:
            yaml_data = yaml.safe_load(f)
        if not yaml_data:
            return _BUILTIN_RULES
        rules = _build_rules_from_yaml(yaml_data)
        if rules:
            logger.info(f"Loaded {len(rules)} classification rules from risk_rules.yaml")
            return rules
        return _BUILTIN_RULES
    except Exception as exc:
        logger.warning(f"Failed to load YAML rules: {exc}, using built-in rules")
        return _BUILTIN_RULES


class IntentClassifier:
    """Classify black/grey-market intel text into risk categories.

    Rules are loaded from config/risk_rules.yaml at init time,
    with built-in Python rules as fallback.
    """

    # ------------------------------------------------------------------
    # L1: Keyword rules — loaded from YAML at init
    # ------------------------------------------------------------------

    def __init__(self):
        self.KEYWORD_RULES: list[tuple[re.Pattern, tuple[str, str]]] = []
        self.reload_rules()
        self._roberta = None

    def reload_rules(self) -> int:
        """Reload classification rules from YAML config. Returns rule count."""
        self.KEYWORD_RULES = _load_rules()
        return len(self.KEYWORD_RULES)

    def classify_keyword(self, text: str) -> tuple[str, str, float] | None:
        """Try to classify by keyword rules. Returns (label, sub_label, confidence) or None."""
        for pattern, (label, sub_label) in self.KEYWORD_RULES:
            if pattern.search(text):
                return label, sub_label, 0.95
        return None

    # ------------------------------------------------------------------
    # L2: RoBERTa model (stub — train before use)
    # ------------------------------------------------------------------

    @property
    def roberta(self):
        if self._roberta is None:
            self._load_roberta()
        return self._roberta

    def _load_roberta(self):
        """Load fine-tuned RoBERTa model. Returns a stub until training is done."""
        from pathlib import Path
        model_path = Path(settings.roberta_model_path) if settings.roberta_model_path else None
        if model_path and model_path.exists():
            try:
                from transformers import AutoModelForSequenceClassification, AutoTokenizer
                tokenizer = AutoTokenizer.from_pretrained(
                    str(model_path),
                    model_max_length=512,
                    truncation_side="right",
                )
                model = AutoModelForSequenceClassification.from_pretrained(str(model_path))
                device = "cpu"
                try:
                    import torch
                    if torch.cuda.is_available():
                        device = "cuda"
                except Exception:
                    device = "cpu"
                try:
                    model.to(device)
                except Exception:
                    device = "cpu"
                    model.to(device)
                model.eval()
                self._roberta = {
                    "model": model,
                    "tokenizer": tokenizer,
                    "device": device,
                }
                logger.info(f"RoBERTa classifier loaded on {device}")
            except Exception as exc:
                logger.warning(f"RoBERTa load failed: {exc}, using stub")
                self._roberta = self._stub_predict
        else:
            logger.info("No RoBERTa model found, using stub (returns None → falls through to LLM)")
            self._roberta = self._stub_predict

    @staticmethod
    def _stub_predict(text: str) -> dict | None:
        """Stub: returns None to let the cascade fall through to LLM."""
        _ = text
        return None

    def classify_roberta(self, text: str) -> tuple[str, str, float] | None:
        """L2 classification via fine-tuned RoBERTa (7 main categories)."""
        loaded = self.roberta
        if loaded is None:
            return None
        if callable(loaded):
            return self._classify_roberta_pipeline(text, loaded)

        try:
            import torch
            model = loaded["model"]
            tokenizer = loaded["tokenizer"]
            device = loaded["device"]
            max_positions = int(getattr(model.config, "max_position_embeddings", 512) or 512)
            tokenizer_max = int(getattr(tokenizer, "model_max_length", 512) or 512)
            max_len = max(8, min(512, max_positions, tokenizer_max))
            encoded = tokenizer(
                text or "",
                return_tensors="pt",
                truncation=True,
                max_length=max_len,
                padding=False,
            )
            encoded = {k: v.to(device) for k, v in encoded.items()}
            with torch.no_grad():
                logits = model(**encoded).logits
                probs = torch.softmax(logits, dim=-1)[0]
                score_tensor, idx_tensor = torch.max(probs, dim=0)
            idx = int(idx_tensor.item())
            score = float(score_tensor.item())
            label = model.config.id2label.get(idx, str(idx))
        except Exception as exc:
            logger.warning(f"RoBERTa classify failed, falling back to next layer: {exc}")
            return None

        if score < settings.classification_confidence_threshold:
            return None
        return label, "", score

    def _classify_roberta_pipeline(self, text: str, pipe) -> tuple[str, str, float] | None:
        """Compatibility path for tests or legacy pipeline instances."""
        try:
            result = pipe(text, truncation=True, max_length=512, padding=False)
        except Exception as exc:
            logger.warning(f"RoBERTa pipeline classify failed, falling back to next layer: {exc}")
            return None
        if result is None:
            return None
        if isinstance(result, list):
            result = result[0]
        label = result.get("label", "")
        score = result.get("score", 0.0)
        if score < settings.classification_confidence_threshold:
            return None
        # label is one of 7 main categories: 诈骗, 引流, 作弊, 账号黑产, 内容违规, 工具交易, 直播违规
        # Sub-label refinement is handled by L1 keyword rules or L3 LLM
        main = label
        sub = ""  # sub_label from keyword mapping if available
        return main, sub, score

    # ------------------------------------------------------------------
    # L3: LLM fallback (~10% coverage)
    # ------------------------------------------------------------------

    def classify_llm(self, text: str) -> tuple[str, str, float]:
        """L3: Call LLM API for final classification."""
        prompt = self._build_llm_prompt(text)
        response = self._call_llm(prompt)
        return self._parse_llm_response(response)

    def _build_llm_prompt(self, text: str) -> str:
        labels = "\n".join(
            f"- {lbl.value}: {', '.join(SUBLABEL_MAP[lbl])}"
            for lbl in IntentLabel
        )
        return f"""你是黑灰产情报分析专家。请将以下文本分类到最匹配的风险类别。

风险类别：
{labels}

文本：{text[:2000]}

请仅返回JSON格式，不要其他内容：
{{"intent_label": "类别", "sub_label": "子类别", "confidence": 0.0~1.0}}"""

    def _call_llm(self, prompt: str) -> str:
        import json
        from openai import OpenAI
        client = OpenAI(
            api_key=settings.llm_api_key,
            base_url=settings.llm_api_base,
        )
        resp = client.chat.completions.create(
            model=settings.llm_model,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.1,
            max_tokens=200,
        )
        return resp.choices[0].message.content

    def _parse_llm_response(self, response: str) -> tuple[str, str, float]:
        import json
        try:
            data = json.loads(response)
            return data["intent_label"], data.get("sub_label", ""), float(data.get("confidence", 0.8))
        except (json.JSONDecodeError, KeyError):
            return IntentLabel.CHEATING, "未分类", 0.5

    # ------------------------------------------------------------------
    # Cascade entry point
    # ------------------------------------------------------------------

    def classify(self, text: str, skip_llm: bool = False, skip_roberta: bool = False) -> dict:
        """Run the full cascade: L1 → L2 → L3.

        When skip_llm=True (degraded mode), skips LLM and returns best
        available result from L1/L2, or a low-confidence default.
        When skip_roberta=True, L2 is skipped as well; this is used by the
        UI "快速筛查" mode to avoid cold-loading the local classifier.

        Returns dict with keys: intent_label, sub_label, confidence, method.
        """
        # L1
        result = self.classify_keyword(text)
        if result:
            label, sub, conf = result
            return {"intent_label": label, "sub_label": sub, "confidence": conf,
                    "method": ClassificationMethod.KEYWORD}

        # L2
        if not skip_roberta:
            result = self.classify_roberta(text)
            if result:
                label, sub, conf = result
                return {"intent_label": label, "sub_label": sub, "confidence": conf,
                        "method": ClassificationMethod.ROBERTA}

        # L3 — skip if circuit breaker is open or explicitly degraded
        if skip_llm:
            return {"intent_label": IntentLabel.CHEATING, "sub_label": "未分类",
                    "confidence": 0.30, "method": "degraded"}

        label, sub, conf = self.classify_llm(text)
        return {"intent_label": label, "sub_label": sub, "confidence": conf,
                "method": ClassificationMethod.LLM}


classifier = IntentClassifier()
