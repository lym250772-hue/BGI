"""
Persona LLM 驱动 — 使用 DeepSeek API 生成人物对话。

核心设计:
  - 每次生成只返回人物话语，不返回解释
  - 系统提示词由 Persona Profile 构建
  - 完整对话历史作为上下文传入
  - 外出内容安全检查在 engine 层进行（不在此处）

安全原则: LLM 只生成文本，不决定行动。所有行动决策由 SafetyGuard 控制。
"""

from loguru import logger
from config.settings import settings


SYSTEM_PROMPT_TEMPLATE = """你是一个AI角色扮演系统。你正在模拟一个真实用户的身份与灰黑产卖家对话。

== 角色设定 ==
{persona_description}

== 对话风格 ==
{conversation_style}

== 安全约束（绝对必须遵守） ==
{safety_rules}

== 当前对话目标 ==
你需要从对方那里了解：
{intelligence_goals}

== 规则 ==
1. 保持角色一致，不要跳出角色，不要暴露你是AI
2. 每次只回复一至三句话，不要长篇大论
3. 不要主动提供任何真实个人信息（姓名、电话、地址、身份证号等）
4. 不要同意任何支付或交易行为——始终停留在"了解情况"阶段
5. 如果对方要求你付款、提供身份信息、或转到加密聊天，委婉地表示需要再考虑
6. 只输出你的回复文本，不要输出任何解释、标注、角色说明或对话前缀（如"小张："）
7. 使用口语化的简体中文回复"""


class PersonaLLMDriver:
    """基于 LLM 的人物对话引擎。

    使用项目的 DeepSeek API 配置，跟 analyzer 共享同一套 LLM 配置。
    如果 LLM API 不可用，自动降级到模板回复模式。
    """

    def __init__(self):
        self.provider = getattr(settings, "llm_provider", "deepseek")
        self.model = getattr(settings, "llm_model", "deepseek-chat")
        self.api_key = getattr(settings, "llm_api_key", "")
        self.api_base = getattr(settings, "llm_api_base",
                                "https://api.deepseek.com/v1")
        self._llm_available = bool(self.api_key and self.api_key != "your_api_key_here")

    def build_system_prompt(self, profile: dict) -> str:
        """从 Persona Profile 构建系统提示词。

        Args:
            profile: Persona Profile dict（来自 YAML）

        Returns:
            格式化的系统提示词
        """
        identity = profile.get("identity", {})
        persona_desc_lines = []
        for k, v in identity.items():
            label = {
                "role": "身份", "experience_level": "经验水平",
                "motivation": "动机", "budget": "预算",
            }.get(k, k)
            persona_desc_lines.append(f"- {label}: {v}")

        conv_style = profile.get("conversation_style", {})
        style_text = (
            f"语气: {conv_style.get('tone', '自然口语')}\n"
            f"问询模式: {conv_style.get('questioning_pattern', '先问价格，再问安全性，最后问流程')}\n"
            f"典型开场: {conv_style.get('typical_opening', '你好，想了解一下你们的服务')}"
        )

        safety = profile.get("safety", {})
        prohibited = safety.get("prohibited_actions", [])
        exit_conds = safety.get("exit_conditions", [])
        safety_text = "\n".join(
            [f"禁止: {a}" for a in prohibited]
            + [f"退出条件: {c}" for c in exit_conds]
        )

        goals = profile.get("intelligence_goals", [])
        goals_text = "\n".join(f"- {g}" for g in goals)

        return SYSTEM_PROMPT_TEMPLATE.format(
            persona_description="\n".join(persona_desc_lines),
            conversation_style=style_text,
            safety_rules=safety_text,
            intelligence_goals=goals_text,
        )

    def generate_response(
        self,
        profile: dict,
        history: list[dict],
        target_context: str,
    ) -> str:
        """生成下一条人物回复。

        Args:
            profile: Persona Profile dict
            history: 对话历史 [{"role": "user"/"assistant", "content": "..."}]
            target_context: 目标上下文（商品描述等）

        Returns:
            生成的回复文本
        """
        if not self._llm_available:
            return self._template_fallback(profile, len(history))

        try:
            system_prompt = self.build_system_prompt(profile)

            # 构建消息列表
            messages = [{"role": "system", "content": system_prompt}]

            # 首次对话：加入目标上下文
            if not history:
                messages.append({
                    "role": "user",
                    "content": f"对方是灰黑产卖家，其商品/简介：\n「{target_context}」\n\n请以角色的身份给对方发第一条消息。记住：只输出你的回复文本。",
                })
            else:
                messages.extend(history)

            # 调用 LLM
            import openai
            client = openai.OpenAI(
                api_key=self.api_key,
                base_url=self.api_base,
            )
            response = client.chat.completions.create(
                model=self.model,
                messages=messages,
                max_tokens=200,
                temperature=0.8,
                timeout=30,
            )
            text = response.choices[0].message.content.strip()

            # 清理常见的输出前缀
            for prefix in ["小张：", "买家：", "我：", "回复：", "人物："]:
                if text.startswith(prefix):
                    text = text[len(prefix):].strip()

            return text

        except Exception as exc:
            logger.warning(f"LLM 调用失败，降级为模板: {exc}")
            return self._template_fallback(profile, len(history))

    def summarize_conversation(self, messages: list[dict]) -> str:
        """用 LLM 总结对话内容。

        Args:
            messages: 对话消息列表

        Returns:
            对话摘要
        """
        if not self._llm_available or len(messages) < 2:
            return "对话内容较少，无法生成摘要"

        try:
            import openai
            dialogue = "\n".join(
                f"[{m.get('role', '?')}]: {m.get('content', '')}"
                for m in messages
            )
            prompt = (
                "你是黑灰产情报分析师。请用一段话总结以下对话：\n"
                f"{dialogue}\n\n"
                "总结应包含：卖家提供什么服务、如何定价、有什么风险信号。"
            )
            client = openai.OpenAI(api_key=self.api_key, base_url=self.api_base)
            response = client.chat.completions.create(
                model=self.model,
                messages=[{"role": "user", "content": prompt}],
                max_tokens=300,
                temperature=0.5,
                timeout=30,
            )
            return response.choices[0].message.content.strip()
        except Exception as exc:
            logger.warning(f"对话总结失败: {exc}")
            return "（LLM总结不可用）"

    def extract_intel(self, messages: list[dict]) -> dict:
        """从对话中提取结构化情报。

        Args:
            messages: 对话消息列表

        Returns:
            {"services_offered": str, "pricing": str, ...}
        """
        if not self._llm_available or len(messages) < 2:
            return {}

        try:
            import openai
            dialogue = "\n".join(
                f"[{m.get('role', '?')}]: {m.get('content', '')}"
                for m in messages
            )
            prompt = (
                "从以下与灰黑产卖家的对话中提取结构化情报。请只返回JSON格式，不要其他内容：\n\n"
                f"{dialogue}\n\n"
                '{\n'
                '  "services_offered": "提供的服务类型",\n'
                '  "pricing": "定价信息",\n'
                '  "payment_methods": "收款方式",\n'
                '  "contact_channels": "其他联系方式",\n'
                '  "operational_details": "运营细节（规模/团队/工具链）",\n'
                '  "risk_indicators": ["风险信号1", "风险信号2"]\n'
                '}\n\n'
                '没有的信息填"未知"。'
            )
            client = openai.OpenAI(api_key=self.api_key, base_url=self.api_base)
            response = client.chat.completions.create(
                model=self.model,
                messages=[{"role": "user", "content": prompt}],
                max_tokens=400,
                temperature=0.3,
                timeout=30,
            )
            text = response.choices[0].message.content.strip()
            # Try to extract JSON
            import json
            import re
            match = re.search(r'\{.*\}', text, re.DOTALL)
            if match:
                return json.loads(match.group())
            return {}
        except Exception as exc:
            logger.warning(f"情报提取失败: {exc}")
            return {}

    def _template_fallback(self, profile: dict, history_len: int) -> str:
        """LLM不可用时的模板回复兜底。"""
        style = profile.get("conversation_style", {})
        if history_len == 0:
            return style.get("typical_opening", "你好，想了解一下你们的服务")

        # 根据轮次返回预定义模板
        templates = [
            "这个多少钱？安全吗？",
            "会不会被封号？能保证存活多久？",
            "你们怎么收款？支持担保交易吗？",
            "你们有多少人在做这个？做了多久了？",
            "能看下你们的案例吗？有没有客户反馈？",
            "哪些平台可以做？效果怎么样？",
            "我从哪里能找到你们？除了这里还有其他联系渠道吗？",
            "我再看看，有什么问题再问你",
        ]
        idx = min(history_len // 2, len(templates) - 1)
        return templates[idx]
