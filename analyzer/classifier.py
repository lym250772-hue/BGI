"""Three-level cascade intent classifier: keyword → RoBERTa → LLM."""
import re
from loguru import logger

from schema import IntentLabel, SUBLABEL_MAP, ClassificationMethod
from config.settings import settings


class IntentClassifier:
    """Classify black/grey-market intel text into 7 risk categories."""

    # ------------------------------------------------------------------
    # L1: Keyword rules (~30% coverage)
    # ------------------------------------------------------------------

    # (keyword_pattern, (intent_label, sub_label))
    KEYWORD_RULES: list[tuple[re.Pattern, tuple[str, str]]] = [
        # 诈骗
        (re.compile(r"代办.{0,5}(贷款|信用卡|签证)"), (IntentLabel.FRAUD, "金融诈骗")),
        (re.compile(r"(无抵押|秒批|黑户).{0,3}贷"), (IntentLabel.FRAUD, "金融诈骗")),
        (re.compile(r"(恭喜|中奖).{0,5}(领取|填写)"), (IntentLabel.FRAUD, "虚假中奖")),
        # 引流
        (re.compile(r"(加.{0,3}[Qq薇微信]).{0,5}(看|视频|私密|福利)"), (IntentLabel.TRAFFIC_DRIVEN, "色情引流")),
        (re.compile(r"[Qq薇微信]{1,2}.*\d{5,}"), (IntentLabel.TRAFFIC_DRIVEN, "站外导流")),
        (re.compile(r"(菠菜|博彩|百家乐|真人视讯)"), (IntentLabel.TRAFFIC_DRIVEN, "赌博引流")),
        # 作弊
        (re.compile(r"(刷|提升).{0,3}(播放量|点赞|粉丝|销量|评论)"), (IntentLabel.CHEATING, "刷量刷单")),
        (re.compile(r"(薅羊毛|撸货|套券|新人券)"), (IntentLabel.CHEATING, "营销套利")),
        (re.compile(r"(外挂|辅助|脚本|透视|自瞄)"), (IntentLabel.CHEATING, "游戏外挂")),
        # 账号黑产
        (re.compile(r"(出|卖|售|收).{0,4}(号|账号)"), (IntentLabel.ACCOUNT_BLACK, "账号买卖")),
        (re.compile(r"(接码|猫池|打码|验证码.{0,3}接收)"), (IntentLabel.ACCOUNT_BLACK, "批量注册/养号")),
        (re.compile(r"(撞库|扫号|洗号|盗号)"), (IntentLabel.ACCOUNT_BLACK, "撞库盗号")),
        # 内容违规
        (re.compile(r"(裸|黄片|AV|色情|福利姬|约炮)"), (IntentLabel.CONTENT_VIOLATION, "色情低俗")),
        # 工具交易
        (re.compile(r"(接码平台|发卡平台|卡密|黑卡)"), (IntentLabel.TOOL_TRADE, "黑卡/接码")),
        (re.compile(r"(出售|购买).{0,4}(数据|名单|信息)"), (IntentLabel.TOOL_TRADE, "数据买卖")),
        # 直播违规
        (re.compile(r"(数字人|无人直播|录播).{0,4}(带货|直播)"), (IntentLabel.LIVE_VIOLATION, "数字人欺诈")),
        (re.compile(r"(挂机|挂播|循环).{0,3}直播"), (IntentLabel.LIVE_VIOLATION, "无人直播")),
    ]

    def classify_keyword(self, text: str) -> tuple[str, str, float] | None:
        """Try to classify by keyword rules. Returns (label, sub_label, confidence) or None."""
        for pattern, (label, sub_label) in self.KEYWORD_RULES:
            if pattern.search(text):
                return label, sub_label, 0.95
        return None

    # ------------------------------------------------------------------
    # L2: RoBERTa model (stub — train before use)
    # ------------------------------------------------------------------

    def __init__(self):
        self._roberta = None

    @property
    def roberta(self):
        if self._roberta is None:
            self._load_roberta()
        return self._roberta

    def _load_roberta(self):
        """Load fine-tuned RoBERTa model. Returns a stub until training is done."""
        model_path = settings.roberta_model_path
        if model_path and model_path.exists():
            try:
                from transformers import pipeline
                self._roberta = pipeline("text-classification", model=str(model_path))
                logger.info("RoBERTa classifier loaded")
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
        """L2 classification via fine-tuned RoBERTa."""
        result = self.roberta(text)
        if result is None:
            return None
        # result is a list[dict] from transformers pipeline
        if isinstance(result, list):
            result = result[0]
        label = result.get("label", "")
        score = result.get("score", 0.0)
        if score < settings.classification_confidence_threshold:
            return None
        # label format: "LABEL_SUBLABEL" e.g. "作弊_刷量刷单"
        if "_" in label:
            main, sub = label.split("_", 1)
        else:
            main, sub = label, ""
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

    def classify(self, text: str) -> dict:
        """Run the full cascade: L1 → L2 → L3.

        Returns dict with keys: intent_label, sub_label, confidence, method.
        """
        # L1
        result = self.classify_keyword(text)
        if result:
            label, sub, conf = result
            return {"intent_label": label, "sub_label": sub, "confidence": conf,
                    "method": ClassificationMethod.KEYWORD}

        # L2
        result = self.classify_roberta(text)
        if result:
            label, sub, conf = result
            return {"intent_label": label, "sub_label": sub, "confidence": conf,
                    "method": ClassificationMethod.ROBERTA}

        # L3
        label, sub, conf = self.classify_llm(text)
        return {"intent_label": label, "sub_label": sub, "confidence": conf,
                "method": ClassificationMethod.LLM}


classifier = IntentClassifier()
