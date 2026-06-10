"""
PersonaEngine — 人物钓鱼主编排器。

工作流程:
  1. 加载 Persona Profile
  2. 初始化对话状态
  3. 循环:
     a. 安全检查（退出条件 + 对方消息审查）
     b. LLM 生成人物回复
     c. 外出安全审查
     d. 模拟卖家回复（Phase 1: LLM模拟 / Phase 2: 真实平台交互）
     e. 记录对话轮次
  4. 对话结束 → LLM 结构化情报提取
  5. 产出 PersonaIntelItem

Phase 1（当前）: 对话双方均为 LLM 模拟，用于测试人物效果和安全护栏。
Phase 2（后续）: 连接真实平台（闲鱼私聊/QQ群），替代卖家模拟器。
"""

from loguru import logger
from persona.conversation import ConversationState, ConversationStatus
from persona.llm_driver import PersonaLLMDriver
from persona.safety import SafetyGuard
from persona.registry import load_persona
from persona.models import PersonaIntelItem


class PersonaEngine:
    """人物钓鱼对话主编排器。"""

    def __init__(self):
        self.llm = PersonaLLMDriver()

    def run_conversation(
        self,
        persona_name: str,
        target_platform: str,
        target_uid: str,
        target_username: str,
        target_context: str,
        initial_message: str = None,
        profile_override: dict = None,
        turn_callback: callable = None,
    ) -> PersonaIntelItem:
        """执行一次完整的钓鱼对话。

        Args:
            persona_name: 人物名称（如 "ecommerce_buyer"）
            target_platform: 目标平台
            target_uid: 目标UID
            target_username: 目标昵称
            target_context: 目标商品/卖家描述
            initial_message: 可选的初始消息（不提供则LLM生成）
            profile_override: 可选的人物设定覆盖 dict
            turn_callback: 可选回调，每轮对话后调用 callback(state) 用于实时展示

        Returns:
            PersonaIntelItem: 对话结果 + 提取情报
        """
        profile = load_persona(persona_name)
        # 合并自定义覆盖
        if profile_override:
            for section in ["identity", "conversation_style", "safety", "intelligence_goals"]:
                if section in profile_override and profile_override[section]:
                    if isinstance(profile_override[section], dict):
                        profile.setdefault(section, {}).update(profile_override[section])
                    elif isinstance(profile_override[section], list):
                        if profile_override[section]:
                            profile[section] = profile_override[section]
        state = ConversationState(
            persona_name=persona_name,
            target_platform=target_platform,
            target_uid=target_uid,
            target_username=target_username,
            target_context=target_context,
            status=ConversationStatus.ACTIVE,
        )

        profile_safety = profile.get("safety", {})

        logger.info(
            f"[{persona_name}] 开始与 {target_username} 的对话 "
            f"(平台={target_platform})"
        )

        # ── 第1步: 生成开场消息 ──────────────────────────────────────
        if initial_message:
            first_msg = initial_message
        else:
            first_msg = self.llm.generate_response(profile, [], target_context)

        # 外出安全检查
        check = SafetyGuard.check_outgoing(first_msg)
        if not check["safe"]:
            logger.warning(f"开场消息未通过安全检查: {check['reason']}")
            first_msg = SafetyGuard.safe_fallback_message()

        state.add_turn("persona", first_msg)
        logger.debug(f"  [人物]: {first_msg[:80]}...")
        if turn_callback:
            turn_callback(state)

        # ── 第2步: 对话循环 ──────────────────────────────────────
        seller_history = []  # [{"role": "user", "content": ...}] for LLM context

        for turn_num in range(1, profile_safety.get("max_turns", 10)):
            # 2a. 模拟卖家回复
            # Phase 1: LLM 模拟。Phase 2: 替换为真实平台交互。
            seller_msg = self._simulate_seller(
                profile, state, target_context,
            )

            # 2b. 对方消息安全检查
            check = SafetyGuard.check_incoming(seller_msg)
            if not check["safe"]:
                state.safety_flags.extend(check["flags"])
                state.status = ConversationStatus.SAFETY_ABORT
                logger.warning(f"安全检查触发: {check['reason']}")
                # 记录但不回复
                state.add_turn("seller", seller_msg)
                break

            state.add_turn("seller", seller_msg)
            seller_history.append({"role": "user", "content": seller_msg})
            logger.debug(f"  [卖家]: {seller_msg[:80]}...")
            if turn_callback:
                turn_callback(state)

            # 2c. 检查退出条件
            should_exit, reason = SafetyGuard.should_exit(
                turn_num, profile_safety, seller_msg,
            )
            if should_exit:
                state.status = (
                    ConversationStatus.COMPLETED
                    if reason == "max_turns_reached"
                    else ConversationStatus.SAFETY_ABORT
                )
                logger.info(f"对话退出: {reason}")
                break

            # 2d. LLM 生成人物回复
            history = [
                {"role": "user", "content": state.turns[i]["content"]}
                if state.turns[i]["role"] == "seller"
                else {"role": "assistant", "content": state.turns[i]["content"]}
                for i in range(len(state.turns))
            ]
            persona_response = self.llm.generate_response(
                profile, history, target_context,
            )

            # 2e. 外出安全检查
            check = SafetyGuard.check_outgoing(persona_response)
            if not check["safe"]:
                logger.warning(
                    f"人物回复未通过安全检查，替换为兜底消息: {check['reason']}"
                )
                persona_response = SafetyGuard.safe_fallback_message()

            state.add_turn("persona", persona_response)
            logger.debug(f"  [人物]: {persona_response[:80]}...")
            if turn_callback:
                turn_callback(state)

        # 标记结束
        if state.status == ConversationStatus.ACTIVE:
            state.status = ConversationStatus.COMPLETED

        return self._finalize(state, profile)

    def run_conversation_stream(
        self,
        persona_name: str,
        target_platform: str,
        target_uid: str,
        target_username: str,
        target_context: str,
        initial_message: str = None,
        profile_override: dict = None,
    ):
        """流式对话生成器 — 每轮对话后 yield state，供 UI 实时展示。

        Usage:
            for state in engine.run_conversation_stream(...):
                # 渲染 state.turns 到 UI
                st.rerun()  # 每次 yield 后刷新页面
        """
        profile = load_persona(persona_name)
        if profile_override:
            for section in ["identity", "conversation_style", "safety", "intelligence_goals"]:
                if section in profile_override and profile_override[section]:
                    if isinstance(profile_override[section], dict):
                        profile.setdefault(section, {}).update(profile_override[section])
                    elif isinstance(profile_override[section], list) and profile_override[section]:
                        profile[section] = profile_override[section]

        state = ConversationState(
            persona_name=persona_name,
            target_platform=target_platform,
            target_uid=target_uid,
            target_username=target_username,
            target_context=target_context,
            status=ConversationStatus.ACTIVE,
        )

        profile_safety = profile.get("safety", {})

        # 开场消息
        if initial_message:
            first_msg = initial_message
        else:
            first_msg = self.llm.generate_response(profile, [], target_context)
        check = SafetyGuard.check_outgoing(first_msg)
        if not check["safe"]:
            first_msg = SafetyGuard.safe_fallback_message()
        state.add_turn("persona", first_msg)
        yield state

        # 对话循环
        seller_history = []
        for turn_num in range(1, profile_safety.get("max_turns", 10)):
            seller_msg = self._simulate_seller(profile, state, target_context)
            check = SafetyGuard.check_incoming(seller_msg)
            if not check["safe"]:
                state.safety_flags.extend(check["flags"])
                state.status = ConversationStatus.SAFETY_ABORT
                state.add_turn("seller", seller_msg)
                yield state
                break

            state.add_turn("seller", seller_msg)
            seller_history.append({"role": "user", "content": seller_msg})
            yield state

            should_exit, reason = SafetyGuard.should_exit(turn_num, profile_safety, seller_msg)
            if should_exit:
                state.status = (
                    ConversationStatus.COMPLETED if reason == "max_turns_reached"
                    else ConversationStatus.SAFETY_ABORT
                )
                break

            history = [
                {"role": "user", "content": state.turns[i]["content"]}
                if state.turns[i]["role"] == "seller"
                else {"role": "assistant", "content": state.turns[i]["content"]}
                for i in range(len(state.turns))
            ]
            persona_response = self.llm.generate_response(profile, history, target_context)
            check = SafetyGuard.check_outgoing(persona_response)
            if not check["safe"]:
                persona_response = SafetyGuard.safe_fallback_message()
            state.add_turn("persona", persona_response)
            yield state

        if state.status == ConversationStatus.ACTIVE:
            state.status = ConversationStatus.COMPLETED
        # 最后 yield: 包含最终 intel
        final = self._finalize(state, profile)
        yield (state, final)

    def _simulate_seller(
        self, profile: dict, state: ConversationState, target_context: str,
    ) -> str:
        """模拟卖家回复（Phase 1: LLM仿真）。

        在 Phase 2 中，此方法将被实际的平台交互（闲鱼私聊API/QQ群@回复）替代。

        当前使用 LLM 以真实灰产卖家身份生成回复，用于测试人物对话能力。
        """
        # 构建卖家视角的上下文
        persona_turns = [t for t in state.turns if t["role"] == "persona"]
        last_msg = persona_turns[-1]["content"] if persona_turns else ""

        seller_system = (
            f"你是一个在{state.target_platform}上做灰黑产生意的卖家。\n"
            f"你的商品/服务：{target_context}\n\n"
            "请以卖家的身份回复对方。保持真实感，像真人对话一样。\n"
            "不要特意伪装或使用过于客气的语气，就像正常交易聊天。\n"
            "只输出你的回复文本，不要有任何解释或角色标注。"
        )

        try:
            import openai
            from config.settings import settings
            api_key = getattr(settings, "llm_api_key", "")
            api_base = getattr(settings, "llm_api_base", "https://api.deepseek.com/v1")
            model = getattr(settings, "llm_model", "deepseek-chat")

            if api_key and api_key != "your_api_key_here":
                client = openai.OpenAI(api_key=api_key, base_url=api_base)
                messages = [{"role": "system", "content": seller_system}]
                for t in state.turns:
                    role = "user" if t["role"] == "persona" else "assistant"
                    messages.append({"role": role, "content": t["content"]})

                response = client.chat.completions.create(
                    model=model,
                    messages=messages,
                    max_tokens=200,
                    temperature=0.9,
                    timeout=30,
                )
                return response.choices[0].message.content.strip()
        except Exception as exc:
            logger.debug(f"卖家模拟LLM失败: {exc}")

        # 兜底: 简单模板回复
        return self._seller_template_fallback(last_msg)

    @staticmethod
    def _seller_template_fallback(last_buyer_msg: str) -> str:
        """卖家模拟的模板兜底。"""
        if "价格" in last_buyer_msg or "多少钱" in last_buyer_msg:
            return "看量，1000粉50块，10000粉400块，量大可以优惠。"
        elif "安全" in last_buyer_msg or "封号" in last_buyer_msg:
            return "放心，都是真实账号操作，不会被封的。我们做了两年了。"
        elif "付款" in last_buyer_msg or "怎么交易" in last_buyer_msg:
            return "微信或者支付宝都可以，先付一半，做完付尾款。"
        elif "流程" in last_buyer_msg or "怎么做" in last_buyer_msg:
            return "你给我链接，我们这边安排人做，一般24小时内完成。"
        else:
            return "你想了解哪方面？价格还是安全性？都可以问我。"

    # ── 对话后处理 ──────────────────────────────────────────────────────

    def _finalize(
        self, state: ConversationState, profile: dict,
    ) -> PersonaIntelItem:
        """对话结束后：总结 + 提取情报 + 生成 PersonaIntelItem。"""
        logger.info(
            f"[{state.persona_name}] 对话结束: "
            f"状态={state.status.value}, 轮次={len(state.turns)}, "
            f"安全标记={len(state.safety_flags)}"
        )

        # LLM 总结
        summary = self.llm.summarize_conversation(state.turns)

        # 结构化情报提取
        extracted = self.llm.extract_intel(state.turns)

        return PersonaIntelItem(
            persona_name=state.persona_name,
            target_platform=state.target_platform,
            conversation_id=state.conversation_id,
            target_uid=state.target_uid,
            target_username=state.target_username,
            conversation_summary=summary,
            extracted_info=extracted,
            raw_messages=state.turns,
            safety_flags=state.safety_flags,
        )
