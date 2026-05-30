"""Chinese display labels for database and model fields used in the UI."""

FIELD_LABELS = {
    "raw_id": "情报ID",
    "clean_text": "研判文本",
    "risk_label": "风险大类",
    "risk_sub_label": "风险细分",
    "risk_score": "风险分",
    "risk_level": "风险等级",
    "classification_method": "判定方式",
    "entity_type": "线索类型",
    "entity_value": "线索值",
    "extraction_method": "抽取方式",
    "confidence": "置信度",
    "context": "上下文",
    "term": "黑话",
    "meaning": "释义",
    "suggested_meaning": "建议释义",
    "evidence": "证据片段",
    "reason": "发现原因",
    "source": "来源",
    "status": "状态",
}

ENTITY_TYPE_LABELS = {
    "phone": "手机号",
    "wechat": "微信号",
    "qq": "QQ号",
    "telegram": "Telegram账号",
    "email": "邮箱",
    "url": "链接",
    "domain": "域名",
    "ip": "IP地址",
    "bank_card": "银行卡",
    "alipay": "支付宝",
    "slang": "黑话",
    "tool": "工具/脚本",
    "crypto_wallet": "加密钱包",
    "feature": "风险特征",
}

EXTRACTION_METHOD_LABELS = {
    "regex": "规则识别",
    "dict": "词典命中",
    "embedding": "向量相似",
    "llm": "大模型发现",
    "degraded": "降级规则",
}

CLASSIFICATION_METHOD_LABELS = {
    "keyword": "规则命中",
    "roberta": "小模型判定",
    "llm": "大模型研判",
    "degraded": "降级判定",
}

RISK_LEVEL_LABELS = {
    "critical": "严重",
    "high": "高危",
    "normal": "中风险",
    "medium": "中风险",
    "low": "低风险",
}

SLANG_STATUS_LABELS = {
    "active": "正式词典",
    "candidate": "待审核",
    "rejected": "已忽略",
}


def field_label(name: str) -> str:
    return FIELD_LABELS.get(name, name)


def entity_type_label(value: str) -> str:
    return ENTITY_TYPE_LABELS.get(str(value or ""), str(value or ""))


def extraction_method_label(value: str) -> str:
    return EXTRACTION_METHOD_LABELS.get(str(value or ""), str(value or ""))


def classification_method_label(value: str) -> str:
    return CLASSIFICATION_METHOD_LABELS.get(str(value or ""), str(value or ""))


def risk_level_label(value: str) -> str:
    return RISK_LEVEL_LABELS.get(str(value or ""), str(value or ""))


def slang_status_label(value: str) -> str:
    return SLANG_STATUS_LABELS.get(str(value or ""), str(value or ""))
