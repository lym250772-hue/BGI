"""Persona 模块数据模型。"""

from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class PersonaIntelItem:
    """通过人物钓鱼收集的情报条目。

    与 IntelItem 不同，PersonaIntelItem 包含对话上下文和结构化提取信息。
    通过 PersonaCollector._to_intel() 转换为统一 IntelItem 入库。
    """

    persona_name: str = ""          # 使用的人物名称
    target_platform: str = ""       # 对话发生的平台
    conversation_id: str = ""       # 对话UUID
    target_uid: str = ""            # 目标卖家UID
    target_username: str = ""       # 目标卖家昵称
    conversation_summary: str = ""  # LLM 对话摘要
    extracted_info: dict = field(default_factory=dict)
    """结构化提取情报:
    {
        "services_offered": str,
        "pricing": str,
        "payment_methods": str,
        "contact_channels": str,
        "operational_scale": str,
        "tool_stack": str,
        "upstream_suppliers": str,
        "risk_indicators": list[str],
    }
    """
    raw_messages: list[dict] = field(default_factory=list)
    collected_at: datetime = field(default_factory=datetime.utcnow)
    safety_flags: list[str] = field(default_factory=list)
