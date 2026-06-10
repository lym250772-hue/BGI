"""Chinese display labels for database and model fields used in the UI."""

FIELD_LABELS = {
    "id": "ID",
    "raw_id": "情报ID",
    "clean_text": "研判文本",
    "content_raw": "原始内容",
    "source_platform": "来源平台",
    "source_channel": "频道/群组",
    "author_name": "作者",
    "collect_time": "接收时间",
    "raw_status": "处理状态",
    "risk_label": "风险大类",
    "risk_sub_label": "风险细分",
    "risk_score": "风险分",
    "risk_level": "风险等级",
    "classification_method": "判定方式",
    "entity_type": "线索类型",
    "entity_value": "线索值",
    "extraction_method": "抽取方式",
    "extract_method": "抽取方式",
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
    "regex": "规则命中",
    "roberta": "小模型判定",
    "nlp": "小模型判定",
    "llm": "大模型研判",
    "degraded": "快速初筛",
    "manual": "人工修正",
    "unknown": "未知",
}

RISK_LEVEL_LABELS = {
    "critical": "严重",
    "high": "高危",
    "normal": "中风险",
    "medium": "中风险",
    "low": "低风险",
    "": "未判定",
}

SLANG_STATUS_LABELS = {
    "active": "正式词典",
    "candidate": "待审核",
    "rejected": "已忽略",
}

RAW_STATUS_LABELS = {
    "RAW_COLLECTED": "待清洗",
    "CLEANED": "已清洗待研判",
    "ANALYZING": "研判中",
    "ANALYZED": "已研判",
    "FAILED": "研判失败",
    "DISCARDED": "已丢弃",
    "SCREENED": "待复核/待升级",
    "pending": "待执行",
    "running": "执行中",
    "success": "已完成",
    "failed": "失败",
}

CLEANING_STATUS_LABELS = {
    "CLEANED": "通过",
    "SIMILAR": "相似保留",
    "MEDIA_ONLY": "媒体内容保留",
    "DISCARDED": "已丢弃",
    "UNKNOWN": "未知",
    "": "-",
}

SCREEN_DECISION_LABELS = {
    "LOW_RISK_ARCHIVED": "低风险归档",
    "NEED_STANDARD_ANALYSIS": "建议标准研判",
    "NEED_GRAPH_ANALYSIS": "建议扩线研判",
    "SCREENED_REVIEW": "待人工复核",
    "CONFIRMED_RISK": "风险确认",
    "CLEANING_DISCARDED": "清洗丢弃",
    "": "-",
}

JOB_STEP_LABELS = {
    "init": "任务初始化",
    "classify": "风险分类",
    "extract_entities": "实体抽取",
    "decide_tools": "路径决策",
    "extract_evidence": "证据提取",
    "risk_score": "风险评分",
    "generate_report": "摘要生成",
    "persist": "多库写入",
    "done": "已完成",
    "error": "执行失败",
    "": "-",
}

JOB_STATUS_LABELS = {
    "pending": "排队中",
    "running": "执行中",
    "success": "已完成",
    "failed": "失败",
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


def raw_status_label(value: str) -> str:
    return RAW_STATUS_LABELS.get(str(value or ""), str(value or "-"))


def intel_status_label(raw_status: str, screen_decision: str = "") -> str:
    """Business-facing status label for intelligence rows."""
    status = str(raw_status or "")
    decision = str(screen_decision or "")
    if status == "SCREENED":
        if decision == "SCREENED_REVIEW":
            return "待人工复核"
        if decision == "NEED_STANDARD_ANALYSIS":
            return "待标准研判"
        if decision == "NEED_GRAPH_ANALYSIS":
            return "待扩线研判"
        return "待复核/待升级"
    return raw_status_label(status)


def cleaning_status_label(value: str) -> str:
    return CLEANING_STATUS_LABELS.get(str(value or ""), str(value or "-"))


def job_status_label(value: str) -> str:
    return JOB_STATUS_LABELS.get(str(value or ""), str(value or "-"))


def screen_decision_label(value: str) -> str:
    return SCREEN_DECISION_LABELS.get(str(value or ""), str(value or "-"))


def job_step_label(value: str) -> str:
    text = str(value or "")
    if text.startswith("done") and "auto_escalated" in text:
        return "初筛完成，已自动追加二轮研判"
    return JOB_STEP_LABELS.get(text, text or "-")
