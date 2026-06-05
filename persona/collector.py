"""PersonaCollector — 将 PersonaEngine 适配为 BaseCollector 接口。

使人物钓鱼结果可以走统一的 collect → clean → analyze 流水线。
"""

from collectors.base import BaseCollector, IntelItem
from loguru import logger


class PersonaCollector(BaseCollector):
    """人物钓鱼采集器 — 按 BaseCollector 接口封装 PersonaEngine。

    Usage:
        collector = PersonaCollector(
            persona_name="ecommerce_buyer",
            targets=[{"platform": "xianyu", "uid": "123", "username": "张三",
                       "context": "提供抖音涨粉服务"}],
        )
        for item in collector.collect():
            save_to_db(item)
    """

    def __init__(self, persona_name: str, targets: list[dict]):
        """
        Args:
            persona_name: 人物名称
            targets: 目标列表 [{"platform", "uid", "username", "context"}, ...]
        """
        self.persona_name = persona_name
        self.targets = targets

    def collect(self):
        """执行所有目标的钓鱼对话。"""
        from persona.engine import PersonaEngine
        engine = PersonaEngine()

        for target in self.targets:
            logger.info(
                f"Persona [{self.persona_name}] → "
                f"{target.get('username', 'unknown')} "
                f"({target.get('platform', 'unknown')})"
            )

            result = engine.run_conversation(
                persona_name=self.persona_name,
                target_platform=target.get("platform", ""),
                target_uid=target.get("uid", ""),
                target_username=target.get("username", ""),
                target_context=target.get("context", ""),
            )

            yield self._to_intel(result)

    @staticmethod
    def _to_intel(pitem) -> IntelItem:
        """将 PersonaIntelItem 转换为统一 IntelItem 格式。"""
        import json as _json

        return IntelItem(
            platform="persona",
            content_raw=pitem.conversation_summary,
            author_uid=pitem.target_uid,
            author_username=pitem.target_username,
            group_id=pitem.persona_name,  # 用group_id存persona名称
            content_type="conversation",
            source_url=f"persona://{pitem.conversation_id}",
            metadata={
                "persona_name": pitem.persona_name,
                "target_platform": pitem.target_platform,
                "conversation_id": pitem.conversation_id,
                "extracted_info": pitem.extracted_info,
                "safety_flags": pitem.safety_flags,
                "turn_count": len(pitem.raw_messages),
                "raw_messages": pitem.raw_messages,
            },
        )
