"""多轮对话状态管理。

对话生命周期:
  init → active → completed | exited_early | safety_abort
"""

import uuid
from enum import Enum
from datetime import datetime
from dataclasses import dataclass, field


class ConversationStatus(Enum):
    INIT = "init"
    ACTIVE = "active"
    COMPLETED = "completed"         # 正常结束
    EXITED_EARLY = "exited_early"   # 达到轮次上限
    SAFETY_ABORT = "safety_abort"   # 安全触发中止


@dataclass
class ConversationState:
    """一条人物钓鱼对话的完整状态。"""

    conversation_id: str = field(
        default_factory=lambda: str(uuid.uuid4())[:12]
    )
    persona_name: str = ""          # 人物名称
    target_platform: str = ""       # 对话发生的平台（xianyu/qq_group等）
    target_uid: str = ""            # 目标UID
    target_username: str = ""       # 目标昵称
    target_context: str = ""        # 目标上下文（商品描述/卖家简介）
    status: ConversationStatus = ConversationStatus.INIT
    started_at: datetime = field(default_factory=datetime.utcnow)
    ended_at: datetime = None
    turns: list[dict] = field(default_factory=list)
    """每条消息格式: {"role": "persona"/"seller", "content": str, "timestamp": str}"""
    safety_flags: list[str] = field(default_factory=list)

    def add_turn(self, role: str, content: str) -> None:
        """添加一轮对话。"""
        self.turns.append({
            "role": role,
            "content": content,
            "timestamp": datetime.utcnow().isoformat(),
        })

    @property
    def turn_count(self) -> int:
        return len(self.turns)

    @property
    def is_active(self) -> bool:
        return self.status == ConversationStatus.ACTIVE
