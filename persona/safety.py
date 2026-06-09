"""
安全检查护栏 — Persona 对话的法律合规核心模块。

每一条消息进出都经过安全检查，确保：
  1. 不参与实际交易（不付款、不转账）
  2. 不透露真实身份信息
  3. 不鼓励或协助违法行为
  4. 不传播非法内容

原则: 被动收集 only — 观察、记录、分析，不参与。
"""

import re
from loguru import logger


class SafetyGuard:
    """多层安全检查：进入检查 + 外出检查 + 退出条件判断。

    所有检查方法都是 @classmethod，无需实例化。
    """

    # ═══════════════════════════════════════════════════════════════════════
    # 退出触发词（对方消息包含这些词 → 立即退出）
    # ═══════════════════════════════════════════════════════════════════════

    EXIT_TRIGGER_WORDS = [
        "先付款", "先转钱", "先打钱", "定金", "保证金",
        "诚意金", "押金", "预付",
        "发身份证", "实名认证", "人脸识别", "手持身份证",
        "加微信私聊", "加QQ私聊", "加我微信", "加我QQ",
        "下载APP", "下载app", "安装软件",
        "裸聊", "招嫖", "枪支", "毒品", "违禁品"]

    # ═══════════════════════════════════════════════════════════════════════
    # 禁止请求模式（正则匹配对方消息中的高风险请求）
    # ═══════════════════════════════════════════════════════════════════════

    PROHIBITED_REQUEST_PATTERNS = [
        r"(先|立即|马上|现在|立刻).*(付款|转账|支付|打款|汇款|发红包)",
        r"(提供|发送|上传|发|给|看看|看一下).*(身份证|护照|手持|照片|视频认证|自拍)",
        r"(身份证|护照).*(发|给|提供|上传|看一下)",
        r"(下载|安装).*(APP|软件|客户端|插件|程序)",
        r"(加|添加|私聊|联系|转).*(微信|WeChat|QQ|QQ群|telegram|蝙蝠|Signal|Skype)",
        r"(给|发|提供|说|告诉).*(手机号|电话号码|验证码|密码|账号密码)",
        r"(线下|见面|当面).*(交易|交货|碰头)"]

    # ═══════════════════════════════════════════════════════════════════════
    # 外出禁止模式（Persona 回复中绝对不能出现的内容）
    # ═══════════════════════════════════════════════════════════════════════

    PROHIBITED_OUTPUT_PATTERNS = [
        r"(我同意|我接受|好的.*付款|好的.*转账|好的.*打钱|可以.*付款)",
        r"(我的.*身份证号?是|我的手机号是|我住在|我的真实姓名)",
        r"(我的.*密码是|我的.*验证码是|我的.*账号是)",
        r"(我帮你|我给你们|我来做|我可以做|我参与)",
        r"(我先付|我先转|我先打|给你转|给你打钱)"]

    # ═══════════════════════════════════════════════════════════════════════
    # 检查方法
    # ═══════════════════════════════════════════════════════════════════════

    @classmethod
    def check_incoming(cls, seller_message: str) -> dict:
        """检查对方（卖家）消息是否有风险。

        Args:
            seller_message: 卖家发来的消息内容

        Returns:
            {"safe": bool, "risk_level": "low"|"medium"|"high"|"exit",
             "reason": str, "flags": list[str]}
        """
        flags = []

        # 检查触发词
        for word in cls.EXIT_TRIGGER_WORDS:
            if word in seller_message:
                flags.append(f"exit_trigger:{word}")

        # 检查禁止模式
        for pattern in cls.PROHIBITED_REQUEST_PATTERNS:
            if re.search(pattern, seller_message):
                flags.append(f"prohibited_pattern")

        if flags:
            return {
                "safe": False,
                "risk_level": "exit",
                "reason": f"检测到 {len(flags)} 个安全触发: {', '.join(flags[:3])}",
                "flags": flags,
            }

        return {"safe": True, "risk_level": "low", "reason": "", "flags": []}

    @classmethod
    def check_outgoing(cls, persona_response: str) -> dict:
        """检查 Persona 生成的回复是否安全。

        Args:
            persona_response: LLM 生成的人物回复

        Returns:
            {"safe": bool, "reason": str}
        """
        for pattern in cls.PROHIBITED_OUTPUT_PATTERNS:
            if re.search(pattern, persona_response):
                return {
                    "safe": False,
                    "reason": f"外出禁止模式匹配",
                }

        return {"safe": True, "reason": ""}

    @classmethod
    def should_exit(
        cls,
        turn_count: int,
        profile_safety: dict = None,
        seller_message: str = "") -> tuple:
        """判断是否应该退出对话。

        Args:
            turn_count: 当前轮次
            profile_safety: 人物Profile中的safety配置
            seller_message: 对方上一条消息（用于检查触发词）

        Returns:
            (should_exit: bool, reason: str)
        """
        profile_safety = profile_safety or {}
        max_turns = profile_safety.get("max_turns", 10)

        if turn_count >= max_turns:
            return True, "max_turns_reached"

        if seller_message:
            check = cls.check_incoming(seller_message)
            if check["risk_level"] == "exit":
                return True, check["reason"]

        return False, ""

    @classmethod
    def safe_fallback_message(cls) -> str:
        """当外出检查失败时使用的安全兜底消息。"""
        return "我再考虑考虑吧，谢谢。"

    @classmethod
    def safe_exit_message(cls, reason: str = "") -> str:
        """当需要安全退出时使用的消息。"""
        if "付款" in reason or "转账" in reason:
            return "不好意思，我现在不方便付款，回头再说吧。"
        elif "身份" in reason or "验证" in reason:
            return "我再考虑考虑吧，谢谢。"
        else:
            return "好的，我了解一下，有需要再联系你。"
