"""Persona 模块 — AI人物钓鱼式情报收集系统。

通过构建AI驱动的虚拟人物（Persona），在灰黑产活跃平台上
以"想参与灰产"的姿态与卖家互动，钓取灰产情报。

安全原则:
  - 只观察、记录、分析，不参与实际交易
  - 所有消息经过 SafetyGuard 安全检查
  - Phase 1: LLM模拟测试（双方均为AI），不连接真实平台
  - Phase 2: 连接真实平台进行被动式情报收集

Usage:
    python main.py persona list           # 列出可用人物
    python main.py persona run --persona ecommerce_buyer --target "..."
"""

from persona.models import PersonaIntelItem
from persona.engine import PersonaEngine
from persona.safety import SafetyGuard
from persona.registry import PERSONA_MAP, load_persona, list_personas
from persona.collector import PersonaCollector

__all__ = [
    "PersonaIntelItem",
    "PersonaEngine",
    "SafetyGuard",
    "PersonaCollector",
    "PERSONA_MAP",
    "load_persona",
    "list_personas",
]
