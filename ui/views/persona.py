"""钓鱼人物对话模拟展示界面 — 答辩演示用。

功能:
  1. 加载 YAML 人物配置，支持字段级自定义编辑
  2. 从情报池已有作者快速选择目标
  3. 对话实时逐轮展示（通过 turn_callback）
  4. 完成后自动提取结构化情报
"""

from __future__ import annotations

import sys
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path

import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from ui.components import page_header
import ui.theme as T

BJT = timezone(timedelta(hours=8))

PLATFORM_LABELS = {
    "xianyu": "闲鱼", "qq_group": "QQ群", "weibo": "微博",
    "zhihu": "知乎", "tieba": "贴吧", "xiaohongshu": "小红书", "douyin": "抖音",
}

CONTEXT_PRESETS = {
    "刷单服务": "闲鱼上卖淘宝刷单服务的卖家，标价 5元/单，描述说「真实买家、不封号」",
    "账号解封": "QQ群里发广告说能解封微信/QQ账号的，声称「内部渠道、不成功退款」",
    "涨粉买粉": "微博/抖音上卖粉丝的，号称「真人活粉、不掉粉、24小时交付」",
    "接码平台": "发帖提供接码验证服务的，说「全平台接码、稳定不掉线」",
    "数据买卖": "出售个人信息的，声称「一手数据、精准客户、按量收费」",
    "游戏黑产": "游戏代练/外挂/刷道具的，声称「稳定不封、全网最低」",
    "自定义": "",
}


def _load_persona_detail(key: str) -> dict:
    try:
        from persona.registry import load_persona
        return load_persona(key)
    except Exception:
        return {}


def _load_recent_targets(platform: str, limit: int = 20) -> list[dict]:
    """从情报池加载指定平台的最近目标。"""
    try:
        from storage.mysql_store import mysql
        with mysql.cursor() as c:
            c.execute(
                """SELECT DISTINCT author_id, author_name, content_raw
                   FROM ods_raw_intel
                   WHERE source_platform=%s AND author_name IS NOT NULL AND author_name != ''
                     AND author_name NOT IN ('Q群管家','QQ安全中心','群助手','系统消息')
                     AND raw_status IN ('CLEANED','ANALYZED')
                   ORDER BY id DESC LIMIT %s""",
                (platform, limit),
            )
            return [
                {"uid": r["author_id"] or "", "name": r["author_name"] or "",
                 "snippet": (r["content_raw"] or "")[:80]}
                for r in c.fetchall()
            ]
    except Exception:
        return []


# ── UI 组件 ─────────────────────────────────────────────────────────────────

def _persona_profile_card(profile: dict):
    if not profile:
        return
    identity = profile.get("identity", {})
    style = profile.get("conversation_style", {})
    safety = profile.get("safety", {})
    goals = profile.get("intelligence_goals", [])

    with st.expander(f"📋 {profile.get('display_name', '')} · 完整设定", expanded=False):
        st.markdown("**🎭 身份设定**")
        for label, key in [("角色", "role"), ("经验", "experience_level"),
                            ("动机", "motivation"), ("知识", "knowledge_level"), ("预算", "budget")]:
            val = identity.get(key, "")
            if val:
                st.caption(f"{label}: {val}")

        st.markdown("**💬 对话风格**")
        for label, key in [("语气", "tone"), ("语言", "language"),
                            ("提问模式", "questioning_pattern"), ("典型开场", "typical_opening")]:
            val = style.get(key, "")
            if val:
                st.caption(f"{label}: {val}")

        st.markdown("**🛡️ 安全护栏**")
        st.caption(f"最大轮次: {safety.get('max_turns', '-')}")
        for cond in safety.get("exit_conditions", []):
            st.caption(f"⚠ {cond}")

        st.markdown("**🎯 情报目标**")
        st.caption(" ".join(goals) if goals else "默认")


def _chat_bubble(role: str, content: str, timestamp: str = ""):
    is_persona = role == "persona"
    avatar = "🕵️" if is_persona else "🎯"
    label = "AI 人物" if is_persona else "目标对象"
    align = "flex-start" if is_persona else "flex-end"
    bg = T.ACCENT if is_persona else "#E8ECF0"
    color = "#FFFFFF" if is_persona else T.INK

    st.markdown(
        f"""
        <div style='display:flex;justify-content:{align};margin:6px 0'>
          <div style='max-width:78%;background:{bg};color:{color};border-radius:12px;
                      padding:8px 14px;font-size:0.9rem;line-height:1.5'>
            <div style='font-size:0.7rem;opacity:0.65;margin-bottom:3px'>
              {avatar} {label}{f" · {timestamp}" if timestamp else ""}
            </div>
            {content.replace(chr(10), '<br>')}
          </div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def _intel_card(intel: dict, summary: str = ""):
    if summary:
        st.info(f"📝 {summary}")

    filled = [
        ("📦 提供服务", intel.get("services_offered", "")),
        ("💰 定价信息", intel.get("pricing", "")),
        ("💳 支付方式", intel.get("payment_methods", "")),
        ("📞 联系方式", intel.get("contact_channels", "")),
        ("🏭 经营规模", intel.get("operational_scale", "")),
        ("🔧 工具栈", intel.get("tool_stack", "")),
        ("🔗 上游供应", intel.get("upstream_suppliers", "")),
    ]
    filled = [(l, v) for l, v in filled if v]
    if filled:
        cols = st.columns(2)
        for i, (label, value) in enumerate(filled):
            with cols[i % 2]:
                st.markdown(
                    f"""<div class='bagi-panel-tight' style='margin-bottom:4px'>
                      <div style='font-size:0.7rem;color:{T.MUTED}'>{label}</div>
                      <div style='font-size:0.85rem'>{value}</div></div>""",
                    unsafe_allow_html=True,
                )

    risks = intel.get("risk_indicators", [])
    if risks:
        tags = " ".join(
            f"<span style='background:{T.RED}15;color:{T.RED};padding:2px 8px;"
            f"border-radius:4px;font-size:0.75rem;margin:2px'>{r}</span>"
            for r in risks
        )
        st.markdown(f"<div style='margin-top:8px'>{tags}</div>", unsafe_allow_html=True)


# ── 主页面 ──────────────────────────────────────────────────────────────────

def show():
    page_header("钓鱼引擎", "🎣 人物对话模拟",
                "YAML 人物配置 → 选择目标 → AI 自动钓鱼对话 → 结构化情报提取")

    # 初始化 session state
    for key, default in [
        ("persona_msgs", []), ("persona_done", False), ("persona_running", False),
        ("persona_intel", None), ("persona_safety", []), ("persona_summary", ""),
    ]:
        if key not in st.session_state:
            st.session_state[key] = default

    # ── 左右 1:1.8 ──
    left, right = st.columns([1, 1.8])

    with left:
        st.markdown("### ⚙️ 对话配置")

        # Step 1: 人物
        st.markdown("**Step 1 · 选择 AI 人物**")
        try:
            from persona.registry import list_personas
            personas = list_personas()
        except Exception:
            personas = ["ecommerce_buyer", "brusher_seeker", "account_unban"]

        persona_labels = {
            "ecommerce_buyer": "🛒 电商卖家小张 — 找涨粉/刷单",
            "brusher_seeker": "🎓 大学生小李 — 找刷单兼职",
            "account_unban": "📱 自媒体王姐 — 找账号解封",
            "__custom__": "✏️ 自定义角色...",
        }
        persona_key = st.selectbox(
            "人物", options=personas + ["__custom__"],
            format_func=lambda k: persona_labels.get(k, k),
            label_visibility="collapsed",
        )

        if persona_key == "__custom__":
            profile = {"identity": {}, "conversation_style": {},
                       "safety": {"max_turns": 10}, "intelligence_goals": []}
        else:
            profile = _load_persona_detail(persona_key)
        _persona_profile_card(profile)

        # 角色编辑器
        idn = profile.get("identity", {}) or {}
        sty = profile.get("conversation_style", {}) or {}
        saf = profile.get("safety", {}) or {}

        with st.expander("✏️ 编辑角色设定", expanded=(persona_key == "__custom__")):
            st.caption("修改后仅本次对话生效，不保存文件")
            ec1, ec2 = st.columns(2)
            with ec1:
                edit_role = st.text_input("身份角色", value=idn.get("role", ""), placeholder="例: 刚开淘宝店的个体户")
                edit_exp = st.selectbox("经验水平", ["beginner", "intermediate", "expert"],
                                        index=0 if not idn.get("experience_level") else
                                        ["beginner", "intermediate", "expert"].index(str(idn.get("experience_level", "beginner"))))
                edit_motivation = st.text_input("动机/目标", value=idn.get("motivation", ""), placeholder="例: 想快速提高店铺数据")
            with ec2:
                edit_knowledge = st.text_input("领域知识", value=idn.get("knowledge_level", ""), placeholder="例: 听说过但不了解")
                edit_budget = st.text_input("预算范围", value=idn.get("budget", ""), placeholder="例: 500-2000元")

            st.markdown("**对话风格**")
            sc1, sc2 = st.columns(2)
            with sc1:
                edit_tone = st.text_input("语气", value=sty.get("tone", ""), placeholder="例: 谨慎、好奇")
                edit_qpattern = st.text_input("提问模式", value=sty.get("questioning_pattern", ""), placeholder="例: 先问价 → 再问安全")
            with sc2:
                edit_lang = st.text_input("语言风格", value=sty.get("language", ""), placeholder="例: 简体中文口语")
                edit_opening = st.text_area("典型开场白", value=sty.get("typical_opening", ""),
                                            height=68, placeholder="例: 你好，看你说能涨粉？")

            st.markdown("**安全护栏**")
            edit_max_turns = st.slider("最大轮次", 3, 30, value=saf.get("max_turns", 10))
            exits_default = saf.get("exit_conditions", [])
            edit_exits = st.text_area("退出条件（一行一条）",
                                      value="\n".join(exits_default) if isinstance(exits_default, list) else "",
                                      height=80, placeholder="对方要求先付款 → '我考虑下'")

            goal_opts = ["service_pricing", "service_process", "payment_methods",
                         "contact_channels", "operational_scale", "tool_stack",
                         "guarantee_policy", "recruitment_process", "task_types",
                         "payment_structure", "team_structure", "risk_indicators"]
            goal_labels = {"service_pricing": "服务定价", "service_process": "操作流程",
                           "payment_methods": "收款方式", "contact_channels": "联系渠道",
                           "operational_scale": "经营规模", "tool_stack": "工具栈",
                           "guarantee_policy": "售后保障", "recruitment_process": "招人流程",
                           "task_types": "任务类型", "payment_structure": "报酬结构",
                           "team_structure": "团队组织", "risk_indicators": "风险指标"}
            edit_goals = st.multiselect("情报采集目标", goal_opts,
                                        default=[g for g in profile.get("intelligence_goals", []) if g in goal_opts],
                                        format_func=lambda g: goal_labels.get(g, g))

            custom_profile = {
                "identity": {"role": edit_role, "experience_level": edit_exp,
                             "motivation": edit_motivation, "knowledge_level": edit_knowledge,
                             "budget": edit_budget},
                "conversation_style": {"tone": edit_tone, "language": edit_lang,
                                       "questioning_pattern": edit_qpattern,
                                       "typical_opening": edit_opening},
                "safety": {"max_turns": edit_max_turns,
                           "exit_conditions": [e.strip() for e in edit_exits.split("\n") if e.strip()]},
                "intelligence_goals": edit_goals,
            }

        st.markdown("---")

        # Step 2: 目标
        st.markdown("**Step 2 · 设置目标对象**")
        target_platform = st.selectbox("目标平台", list(PLATFORM_LABELS.keys()),
                                       format_func=lambda p: PLATFORM_LABELS[p])

        # 从情报池加载目标（始终展示下拉）
        recent = _load_recent_targets(target_platform)
        if recent:
            target_opts = ["（手动输入）"] + [
                f"{t['name']} | {t['snippet'][:45]}"
                for t in recent[:15]
            ]
            picked = st.selectbox("💡 快速选择已有目标（可选）", target_opts, key="quick_target")
            if picked != "（手动输入）":
                idx = target_opts.index(picked) - 1
                sel = recent[idx]
                default_uid = sel["uid"]
                default_name = sel["name"]
                default_ctx = sel["snippet"]
            else:
                default_uid = ""
                default_name = ""
                default_ctx = ""
        else:
            default_uid = ""
            default_name = ""
            default_ctx = ""

        target_uid = st.text_input("目标 UID", value=default_uid, placeholder="对方用户ID")
        target_username = st.text_input("目标昵称", value=default_name, placeholder="对方昵称")

        preset_key = st.selectbox("场景预设", list(CONTEXT_PRESETS.keys()))
        if preset_key == "自定义":
            ctx_val = default_ctx
        else:
            ctx_val = CONTEXT_PRESETS[preset_key]
        target_context = st.text_area("目标描述", value=ctx_val, height=80,
                                      placeholder="描述对方的商品/服务/背景...",
                                      help="描述越详细，AI 生成的对话越有针对性")

        # Step 3: 开场
        st.markdown("**Step 3 · 开场消息（可选）**")
        typical = profile.get("conversation_style", {}).get("typical_opening", "") if profile else ""
        if typical:
            st.caption(f"💡 预设开场: _{typical}_")
        initial_msg = st.text_area("自定义开场", height=68, label_visibility="collapsed",
                                   placeholder="留空则 AI 自动生成")

        st.markdown("---")
        col_a, col_b = st.columns(2)
        with col_a:
            start_btn = st.button("🚀 开始对话", use_container_width=True, type="primary",
                                  disabled=st.session_state.persona_running)
        with col_b:
            if st.button("🔄 重置", use_container_width=True):
                for k in list(st.session_state.keys()):
                    if k.startswith("persona_"):
                        del st.session_state[k]
                st.rerun()

    # ═══════════ 右侧：对话展示 ═══════════
    with right:
        st.markdown("### 💬 对话记录")

        # 运行中显示 spinner
        if st.session_state.persona_running:
            st.info("🔄 对话进行中...")

        # 对话区域 — 加高
        chat_h = 600
        with st.container(height=chat_h):
            if not st.session_state.persona_msgs:
                st.markdown(
                    f"""<div style='text-align:center;color:{T.MUTED};padding:120px 0 20px'>
                    <div style='font-size:2.5rem;margin-bottom:12px'>🎣</div>
                    <div>配置左侧参数后点击「开始对话」</div>
                    <div style='font-size:0.75rem;opacity:0.6;margin-top:6px'>
                      AI 将扮演选定人物主动发起对话<br>实时逐轮展示，全程安全检查
                    </div></div>""",
                    unsafe_allow_html=True,
                )
            for msg in st.session_state.persona_msgs:
                _chat_bubble(msg["role"], msg["content"], msg.get("timestamp", ""))

        # 完成后展示情报
        if st.session_state.persona_done and st.session_state.persona_intel:
            st.markdown("---")
            st.markdown("### 📊 提取情报")
            _intel_card(st.session_state.persona_intel, st.session_state.persona_summary)

            flags = st.session_state.persona_safety
            if flags:
                st.markdown("#### 🛡️ 安全检查")
                for f in flags:
                    st.warning(f"⚠️ {f}")
            else:
                st.success("✅ 安全检查全部通过")

    # ═══════════ 动作：流式实时对话 ═══════════
    if start_btn:
        if not target_context.strip():
            st.error("请填写目标描述")
            st.stop()

        # 清空并启动
        st.session_state.persona_msgs = []
        st.session_state.persona_done = False
        st.session_state.persona_intel = None
        st.session_state.persona_safety = []
        st.session_state.persona_summary = ""
        st.session_state.persona_running = True

        has_override = (persona_key == "__custom__") or any(
            custom_profile.get(s) for s in ["identity", "conversation_style", "safety", "intelligence_goals"]
            if custom_profile.get(s)
        )
        override = custom_profile if has_override else None
        engine_persona = persona_key if persona_key != "__custom__" else "ecommerce_buyer"

        try:
            from persona.engine import PersonaEngine
            engine = PersonaEngine()
            gen = engine.run_conversation_stream(
                persona_name=engine_persona,
                target_platform=target_platform,
                target_uid=target_uid.strip() or "unknown",
                target_username=target_username.strip() or "未知用户",
                target_context=target_context.strip(),
                initial_message=initial_msg.strip() or None,
                profile_override=override,
            )
            st.session_state.persona_gen = gen
            st.rerun()

        except Exception as e:
            st.session_state.persona_running = False
            st.error(f"启动失败: {e}")

    # ── 自动推进生成器 ──
    if st.session_state.persona_running and "persona_gen" in st.session_state:
        gen = st.session_state.persona_gen
        if gen is not None:
            try:
                item = next(gen)
                # 判断是否为最后一个 yield：(state, final_intel)
                if isinstance(item, tuple) and len(item) == 2:
                    state, final = item
                    is_last = True
                else:
                    state = item
                    is_last = False

                # 更新消息
                msgs = []
                for turn in state.turns:
                    ts = turn.get("timestamp", "")
                    if ts:
                        try:
                            ts = datetime.fromisoformat(ts).strftime("%H:%M:%S")
                        except Exception:
                            pass
                    msgs.append({
                        "role": turn.get("role", "seller"),
                        "content": turn.get("content", ""),
                        "timestamp": ts,
                    })
                st.session_state.persona_msgs = msgs

                if is_last:
                    st.session_state.persona_gen = None
                    st.session_state.persona_intel = final.extracted_info
                    st.session_state.persona_safety = final.safety_flags
                    st.session_state.persona_summary = final.conversation_summary
                    st.session_state.persona_done = True
                    st.session_state.persona_running = False

                st.rerun()
            except StopIteration:
                st.session_state.persona_gen = None
                st.session_state.persona_done = True
                st.session_state.persona_running = False
                st.rerun()
