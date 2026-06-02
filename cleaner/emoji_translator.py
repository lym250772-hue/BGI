"""
Emoji 语义翻译器 — 将 emoji 翻译为灰黑产语境下的中文含义。

设计原则:
  - 静态词典优先（零 API 开销，覆盖 90% 灰黑产 emoji 使用场景）
  - 全面 Unicode 覆盖（修复 BaseSpider.contains_emoji() 缺失的 8 个 Unicode block）
  - 惰性单例模式（与 MediaProcessor / RiskScorer 一致）

灰黑产 emoji 使用特征:
  - 替代敏感词:  🛰=微信, 💰=赚钱/刷单, 📱=手机, 🔞=色情
  - 规避检测:    "加🛰️ xxx" 替代 "加微信 xxx"
  - 增强信号:    "💯靠谱" "🔥爆款" 暗示高转化率
  - 平台特有:    小红书常用🉑(可以/接单), 抖音常用#️⃣(话题引流)

用法:
    from cleaner.emoji_translator import emoji_translator

    text = emoji_translator.translate("🛰💰📱 刷单兼职日赚500")
    # → "[🛰:微信] [💰:赚钱] [📱:手机] 刷单兼职日赚500"

    emojis = emoji_translator.extract_emojis("加🛰️ xxx")
    # → [{"char": "🛰", "meaning": "微信", "position": 1, "category": "contact"}]
"""

from __future__ import annotations

import re
from typing import Any

# ═══════════════════════════════════════════════════════════════════════════════
# 全面 Unicode Emoji 正则（覆盖所有已知 emoji Unicode block）
# ═══════════════════════════════════════════════════════════════════════════════

# 比 BaseSpider.contains_emoji() 更全面的 Unicode 覆盖
_EMOJI_PATTERN = re.compile(
    "["
    "\U0001F600-\U0001F64F"   # Emoticons (😀-🙏)
    "\U0001F300-\U0001F5FF"   # Misc Symbols & Pictographs (🌀-🗿)
    "\U0001F680-\U0001F6FF"   # Transport & Map (🚀-🛿)
    "\U0001F1E0-\U0001F1FF"   # Regional Indicators (🇦-🇿)
    "\U00002600-\U000027BF"   # Misc Symbols (☀-➿)
    "\U0001F900-\U0001F9FF"   # Supplemental Symbols & Pictographs (🤀-🧿)
    "\U0001FA00-\U0001FA6F"   # Chess Symbols (🨀-🩯)
    "\U0001FA70-\U0001FAFF"   # Symbols Extended-A (🩰-🫿)
    "\U0001F780-\U0001F7FF"   # Geometric Shapes Extended (🞀-🟿)
    "\U0001F3FB-\U0001F3FF"   # Skin Tone Modifiers (🏻-🏿)
    "\U0000200D"              # ZWJ (Zero Width Joiner)
    "\U0000FE0F"              # Variation Selector-16 (emoji presentation)
    "\U000020E3"              # Combining Enclosing Keycap
    "\U000000A9"              # © Copyright
    "\U000000AE"              # ® Registered
    "\U00002122"              # ™ Trade Mark
    "\U00002139"              # ℹ Information
    "\U00002328-\U0000232B"   # ⌨-⌫ Keyboard symbols
    "\U000023CF"              # ⏏ Eject
    "\U000023E9-\U000023F3"   # ⏩-⏳ Time
    "\U000023F8-\U000023FA"   # ⏸-⏺ Media controls
    "\U000024C2"              # Ⓜ Circled M
    "\U000025AA-\U000025AB"   # ▪-▫ Square
    "\U000025B6"              # ▶ Play
    "\U000025C0"              # ◀ Reverse
    "\U000025FB-\U000025FE"   # ◻-◾ Square
    "\U00002614-\U00002615"   # ☔-☕ Weather
    "\U00002648-\U00002653"   # ♈-♓ Zodiac
    "\U0000267F"              # ♿ Wheelchair
    "\U00002693"              # ⚓ Anchor
    "\U000026A1"              # ⚡ High Voltage
    "\U000026AA-\U000026AB"   # ⚪-⚫ Circle
    "\U000026BD-\U000026BE"   # ⚽-⚾ Ball
    "\U000026C4-\U000026C5"   # ⛄-⛅ Snow/Cloud
    "\U000026D4"              # ⛔ No Entry
    "\U000026EA"              # ⛪ Church
    "\U000026F2-\U000026F3"   # ⛲-⛳ Fountain/Golf
    "\U000026F5"              # ⛵ Sailboat
    "\U000026FA"              # ⛺ Tent
    "\U000026FD"              # ⛽ Fuel Pump
    "\U00002702"              # ✂ Scissors
    "\U00002708-\U0000270D"   # ✈-✍ Airplane/Writing
    "\U0000270F"              # ✏ Pencil
    "\U00002712"              # ✒ Pen
    "\U00002714"              # ✔ Check
    "\U00002716"              # ✖ Multiply
    "\U0000271D"              # ✝ Cross
    "\U00002721"              # ✡ Star of David
    "\U00002728"              # ✨ Sparkles
    "\U00002733-\U00002734"   # ✳-✴ Asterisk/Star
    "\U00002744"              # ❄ Snowflake
    "\U00002747"              # ❇ Sparkle
    "\U0000274C"              # ❌ Cross Mark
    "\U0000274E"              # ❎ Cross Mark Button
    "\U00002753-\U00002755"   # ❓-❕ Question/Exclamation
    "\U00002757"              # ❗ Exclamation
    "\U00002763-\U00002764"   # ❣-❤ Heart
    "\U00002795-\U00002797"   # ➕-➗ Math
    "\U000027A1"              # ➡ Arrow
    "\U000027B0"              # ➰ Curly Loop
    "\U000027BF"              # ➿ Double Curly Loop
    "\U00002934-\U00002935"   # ⤴-⤵ Arrow
    "\U00002B05-\U00002B07"   # ⬅-⬇ Arrow
    "\U00002B1B-\U00002B1C"   # ⬛-⬜ Square
    "\U00002B50"              # ⭐ Star
    "\U00002B55"              # ⭕ Circle
    "\U00003030"              # 〰 Wavy Dash
    "\U0000303D"              # 〽 Part Alternation
    "\U00003297"              # ㊗ Congratulations
    "\U00003299"              # ㊙ Secret
    "\U0001F004"              # 🀄 Mahjong
    "\U0001F0CF"              # 🃏 Joker
    "\U0001F170-\U0001F171"   # 🅰-🅱 A/B
    "\U0001F17E-\U0001F17F"   # 🅾-🅿 O/P
    "\U0001F18E"              # 🆎 AB
    "\U0001F191-\U0001F19A"   # 🆑-🆚 CL-NG
    "\U0001F201-\U0001F202"   # 🈁-🈂 Koko/Sa
    "\U0001F21A"              # 🈚 Free
    "\U0001F22F"              # 🈯 Reserved
    "\U0001F232-\U0001F23A"   # 🈲-🈺 Prohibited-Open
    "\U0001F250-\U0001F251"   # 🉐-🉑 Bargain/Accept
    "\U0001F300-\U0001F320"   # 🌀-🌠 Weather/Astro (sub-range, already covered above)
    "]",
    re.UNICODE,
)


def contains_emoji(text: str) -> bool:
    """全面 Unicode emoji 检测（比 BaseSpider 版本覆盖更广）。"""
    if not text:
        return False
    return bool(_EMOJI_PATTERN.search(text))


def extract_emoji_chars(text: str) -> list[str]:
    """提取文本中所有 emoji 字符。"""
    if not text:
        return []
    return _EMOJI_PATTERN.findall(text)


# ═══════════════════════════════════════════════════════════════════════════════
# Emoji → 灰黑产语义映射词典
# ═══════════════════════════════════════════════════════════════════════════════

EMOJI_MEANING_MAP: dict[str, dict[str, str]] = {
    # ── 联系方式类 (contact) ──────────────────────────────────────────────
    "🛰":  {"meaning": "微信",      "category": "contact",   "note": "卫星=微信，灰产常用替代词"},
    "🛰️": {"meaning": "微信",      "category": "contact",   "note": "同上(vs16)"},
    "📲":  {"meaning": "联系/加好友","category": "contact",  "note": "手机+箭头=引导联系"},
    "📞":  {"meaning": "电话联系",   "category": "contact",  "note": "电话听筒"},
    "📱":  {"meaning": "手机/加好友","category": "contact",  "note": "智能手机=私域联系"},
    "💬":  {"meaning": "私信/咨询",  "category": "contact",  "note": "对话气泡"},
    "🗨":  {"meaning": "私聊",       "category": "contact",  "note": "左对话气泡"},
    "🗯":  {"meaning": "议价/谈判",  "category": "contact",  "note": "右愤怒气泡=讨价还价"},
    "💭":  {"meaning": "私信/想法",  "category": "contact",  "note": "思想气泡"},
    "✉":   {"meaning": "私信/邮件",  "category": "contact",  "note": "信封"},
    "✉️":  {"meaning": "私信/邮件",  "category": "contact",  "note": "同上(vs16)"},
    "📩":  {"meaning": "发消息/联系","category": "contact",  "note": "信封+箭头=发送"},
    "📧":  {"meaning": "邮件联系",   "category": "contact",  "note": "电子邮件"},
    "📤":  {"meaning": "发送/联系",  "category": "contact",  "note": "发件箱"},
    "📥":  {"meaning": "接收/收件",  "category": "contact",  "note": "收件箱"},
    "📮":  {"meaning": "投稿/联系",  "category": "contact",  "note": "邮筒=投递"},
    "👤":  {"meaning": "个人号/小号", "category": "contact", "note": "单人轮廓=个人账号"},
    "👥":  {"meaning": "群组/社群",  "category": "contact",  "note": "双人=群组"},
    "🗣":  {"meaning": "语音通话",   "category": "contact",  "note": "说话人头=语音联系"},
    "📢":  {"meaning": "广告/推广",  "category": "contact",  "note": "喇叭=公告/喊单"},
    "📣":  {"meaning": "喊单/推广",  "category": "contact",  "note": "扩音器=带单/喊单"},

    # ── 金钱交易类 (money) ──────────────────────────────────────────────────
    "💰":  {"meaning": "赚钱/刷单",  "category": "money",    "note": "钱袋=收益"},
    "💸":  {"meaning": "赚钱/套现",  "category": "money",    "note": "飞钱=快速套现"},
    "💴":  {"meaning": "套现/洗钱",  "category": "money",    "note": "日元钞票=跨境洗钱"},
    "💵":  {"meaning": "美元/套现",  "category": "money",    "note": "美元钞票"},
    "💶":  {"meaning": "欧元/套现",  "category": "money",    "note": "欧元钞票"},
    "💷":  {"meaning": "英镑/套现",  "category": "money",    "note": "英镑钞票"},
    "💳":  {"meaning": "银行卡/信用卡","category": "money",  "note": "信用卡=卡号交易"},
    "💱":  {"meaning": "换汇/洗钱",  "category": "money",    "note": "货币兑换"},
    "💲":  {"meaning": "美元/收费",  "category": "money",    "note": "美元符号"},
    "🤑":  {"meaning": "赚钱/暴利",  "category": "money",    "note": "钱脸=暴利诱惑"},
    "🪙":  {"meaning": "虚拟币/代币", "category": "money",   "note": "硬币=USDT等加密货币"},
    "💎":  {"meaning": "高价值/精准", "category": "money",   "note": "钻石=高价/精准流量"},
    "🏧":  {"meaning": "取款/洗钱",  "category": "money",    "note": "ATM标志=提现"},
    "🧧":  {"meaning": "红包/返利",  "category": "money",    "note": "红包=刷单返利"},
    "🎫":  {"meaning": "卡密/券码",  "category": "money",    "note": "票券=卡密交易"},
    "🎟":  {"meaning": "券/门票",    "category": "money",    "note": "入场券=活动票/优惠券"},
    "🎁":  {"meaning": "免费/福利",  "category": "money",    "note": "礼物=诱饵/免费送"},
    "🎀":  {"meaning": "福利/优惠",  "category": "money",    "note": "蝴蝶结=福利活动"},

    # ── 信任/质量信号类 (trust) ────────────────────────────────────────────
    "💯":  {"meaning": "靠谱/满分",  "category": "trust",    "note": "100分=绝对靠谱"},
    "✅":  {"meaning": "靠谱/已完成", "category": "trust",   "note": "勾号=已验证"},
    "✔":   {"meaning": "靠谱/认证",  "category": "trust",    "note": "对勾=认证"},
    "☑":   {"meaning": "已确认",     "category": "trust",    "note": "勾选框=已确认"},
    "🔥":  {"meaning": "热门/火爆",  "category": "trust",    "note": "火焰=爆款"},
    "🌟":  {"meaning": "精品/高端",  "category": "trust",    "note": "星星=优质"},
    "⭐":  {"meaning": "好评/刷评",  "category": "trust",    "note": "星=评价/评分"},
    "✨":  {"meaning": "新号/养号",  "category": "trust",    "note": "闪光=新号/新机会"},
    "🎯":  {"meaning": "精准引流",   "category": "trust",    "note": "靶心=精准/定向"},
    "🏅":  {"meaning": "排名/SEO",   "category": "trust",    "note": "奖牌=排名优化"},
    "🥇":  {"meaning": "第一名/刷榜","category": "trust",   "note": "金牌=榜首"},
    "🎖":  {"meaning": "认证/大V",   "category": "trust",    "note": "勋章=官方认证"},
    "🔰":  {"meaning": "新手/小白",  "category": "trust",    "note": "新手标志=容易上当"},
    "💡":  {"meaning": "教程/方法",  "category": "trust",    "note": "灯泡=教学/教程"},
    "💥":  {"meaning": "爆款/炸裂",  "category": "trust",    "note": "爆炸=爆款效果"},
    "💫":  {"meaning": "快速/秒到",  "category": "trust",    "note": "流星=秒到账"},

    # ── 平台/链接类 (platform) ─────────────────────────────────────────────
    "🌐":  {"meaning": "网站/暗网",  "category": "platform", "note": "地球=网址/暗网"},
    "🔗":  {"meaning": "链接",       "category": "platform", "note": "链接符号"},
    "📎":  {"meaning": "附件/文件",  "category": "platform", "note": "回形针=附件"},
    "🖥":  {"meaning": "电脑/远程",  "category": "platform", "note": "台式机=远程操作"},
    "💻":  {"meaning": "电脑/技术",  "category": "platform", "note": "笔记本=技术操作"},
    "⌨":   {"meaning": "打字/代聊",  "category": "platform", "note": "键盘=代聊/水军"},
    "🖱":  {"meaning": "点击/刷量",  "category": "platform", "note": "鼠标=刷点击"},
    "📟":  {"meaning": "联系/寻呼",  "category": "platform", "note": "传呼机=BP机联系"},
    "📠":  {"meaning": "传真/发送",  "category": "platform", "note": "传真机"},

    # ── 赌博类 (gambling) ──────────────────────────────────────────────────
    "🎰":  {"meaning": "赌博/老虎机", "category": "gambling","note": "老虎机=赌博"},
    "🎲":  {"meaning": "赌博/骰子",  "category": "gambling","note": "骰子=赌博游戏"},
    "🎴":  {"meaning": "花札/赌博",  "category": "gambling","note": "花札=日本赌博牌"},
    "🀄":  {"meaning": "麻将/赌博",  "category": "gambling","note": "红中=麻将赌博"},
    "🃏":  {"meaning": "扑克/赌博",  "category": "gambling","note": "鬼牌=德州/扑克"},
    "♠":   {"meaning": "赌博/黑桃",  "category": "gambling","note": "黑桃=牌类赌博"},
    "♥":   {"meaning": "赌博/红心",  "category": "gambling","note": "红心=牌类赌博"},
    "♦":   {"meaning": "赌博/方块",  "category": "gambling","note": "方块=牌类赌博"},
    "♣":   {"meaning": "赌博/梅花",  "category": "gambling","note": "梅花=牌类赌博"},

    # ── 色情/成人内容类 (adult) ────────────────────────────────────────────
    "🔞":  {"meaning": "色情/成人",  "category": "adult",    "note": "18禁=成人内容"},
    "🍆":  {"meaning": "色情暗示",   "category": "adult",    "note": "茄子=男性性暗示"},
    "🍑":  {"meaning": "色情暗示",   "category": "adult",    "note": "桃子=女性性暗示"},
    "🍒":  {"meaning": "色情暗示",   "category": "adult",    "note": "樱桃=性暗示"},
    "🌶":  {"meaning": "色情/辣",    "category": "adult",    "note": "辣椒=辣/性感"},
    "👙":  {"meaning": "色情/泳装",  "category": "adult",    "note": "比基尼"},
    "🩱":  {"meaning": "色情/泳装",  "category": "adult",    "note": "连体泳衣"},

    # ── 游戏/外挂类 (gaming) ───────────────────────────────────────────────
    "🎮":  {"meaning": "游戏/外挂",  "category": "gaming",   "note": "游戏手柄=游戏相关"},
    "🕹":  {"meaning": "游戏/操控",  "category": "gaming",   "note": "摇杆=游戏操控"},
    "🎯":  {"meaning": "精准/作弊",  "category": "gaming",   "note": "靶心=自瞄/精准"},
    "👾":  {"meaning": "游戏/脚本",  "category": "gaming",   "note": "太空入侵者=游戏脚本"},

    # ── 安全/违法类 (illegal) ──────────────────────────────────────────────
    "🔒":  {"meaning": "安全/加密",  "category": "illegal",  "note": "锁=安全/加密通信"},
    "🔑":  {"meaning": "账号/密码",  "category": "illegal",  "note": "钥匙=账号密码"},
    "🔓":  {"meaning": "破解/解锁",  "category": "illegal",  "note": "开锁=破解/撞库"},
    "🗝":  {"meaning": "密钥/老号",  "category": "illegal",  "note": "旧钥匙=老号/密码"},
    "💊":  {"meaning": "药品/违禁品", "category": "illegal", "note": "药丸=违禁药品"},
    "💉":  {"meaning": "注射/毒品",  "category": "illegal",  "note": "针筒=毒品注射"},
    "🌿":  {"meaning": "大麻/毒品",  "category": "illegal",  "note": "草药=大麻"},
    "🍄":  {"meaning": "迷幻/毒品",  "category": "illegal",  "note": "蘑菇=迷幻蘑菇"},
    "🔫":  {"meaning": "枪支/武器",  "category": "illegal",  "note": "水枪=枪支交易"},
    "💣":  {"meaning": "炸弹/威胁",  "category": "illegal",  "note": "炸弹=威胁/违法"},
    "🧨":  {"meaning": "炸药/违法",  "category": "illegal",  "note": "鞭炮=爆炸物"},
    "🗡":  {"meaning": "武器/刀具",  "category": "illegal",  "note": "匕首=管制刀具"},
    "⚔":   {"meaning": "武器/攻击",  "category": "illegal",  "note": "交叉剑=武器交易"},
    "🛡":  {"meaning": "防护/防封",  "category": "illegal",  "note": "盾牌=防封号/防检测"},
    "🧬":  {"meaning": "基因/违禁",  "category": "illegal",  "note": "DNA=基因编辑"},

    # ── 账号/身份类 (identity) ─────────────────────────────────────────────
    "🆔":  {"meaning": "身份证/实名", "category": "identity","note": "ID=实名认证/身份证"},
    "🆕":  {"meaning": "新号",       "category": "identity","note": "NEW=新注册号"},
    "🆓":  {"meaning": "免费",       "category": "identity","note": "FREE=免费"},
    "🆙":  {"meaning": "升级/涨粉",  "category": "identity","note": "UP=升级/提升"},
    "🆒":  {"meaning": "酷/受欢迎",  "category": "identity","note": "COOL=受欢迎"},
    "🔤":  {"meaning": "字母/编码",  "category": "identity","note": "拉丁字母=编码信息"},
    "🔡":  {"meaning": "小写/编码",  "category": "identity","note": "小写字母=密文"},
    "🔠":  {"meaning": "大写/编码",  "category": "identity","note": "大写字母=密文"},
    "🔢":  {"meaning": "数字/金额",  "category": "identity","note": "数字=金额/数量"},

    # ── 动作/状态类 (action) ───────────────────────────────────────────────
    "🤝":  {"meaning": "合作/交易",  "category": "action",   "note": "握手=交易达成"},
    "✍":   {"meaning": "签名/注册",  "category": "action",   "note": "写字=注册/签约"},
    "✏":   {"meaning": "代写/编辑",  "category": "action",   "note": "铅笔=代写作业/论文"},
    "📝":  {"meaning": "注册/填表",  "category": "action",   "note": "备忘录=填写信息"},
    "🔍":  {"meaning": "搜索/查找",  "category": "action",   "note": "放大镜左=搜索目标"},
    "🔎":  {"meaning": "搜索/查找",  "category": "action",   "note": "放大镜右=搜索目标"},
    "👁":  {"meaning": "偷窥/查看",  "category": "action",   "note": "眼睛=查看/监控"},
    "👁‍🗨": {"meaning": "社工库/查信息","category": "action", "note": "眼睛+气泡=社工库查询"},
    "🕵":  {"meaning": "侦查/调查",  "category": "action",   "note": "侦探=查信息/人肉"},
    "🕵️": {"meaning": "侦查/调查",  "category": "action",   "note": "同上(vs16)"},
    "🔔":  {"meaning": "通知/关注",  "category": "action",   "note": "铃铛=订阅通知"},
    "🔕":  {"meaning": "免打扰/隐私", "category": "action",  "note": "静音铃铛=隐身/隐私"},
    "📌":  {"meaning": "置顶/固定",  "category": "action",   "note": "图钉=置顶消息"},
    "📛":  {"meaning": "标签/身份",  "category": "action",   "note": "名札=身份标签"},
    "🔖":  {"meaning": "标签/分类",  "category": "action",   "note": "书签=分类标记"},

    # ── 数字/符号类 (symbol) ───────────────────────────────────────────────
    "1️⃣": {"meaning": "第一/优先",   "category": "symbol",   "note": "数字1=优先级"},
    "2️⃣": {"meaning": "第二/次选",   "category": "symbol",   "note": "数字2"},
    "3️⃣": {"meaning": "第三/更多",   "category": "symbol",   "note": "数字3"},
    "4️⃣": {"meaning": "第四",       "category": "symbol",   "note": "数字4"},
    "5️⃣": {"meaning": "第五",       "category": "symbol",   "note": "数字5"},
    "0️⃣": {"meaning": "零/免费",    "category": "symbol",   "note": "数字0"},
    "#️⃣": {"meaning": "话题/标签",   "category": "symbol",   "note": "#号=话题引流"},
    "*️⃣": {"meaning": "星号/重点",   "category": "symbol",   "note": "*号=重点标记"},
    "ℹ":  {"meaning": "信息/详情",   "category": "symbol",   "note": "信息符号"},
    "Ⓜ":  {"meaning": "地铁/商圈",   "category": "symbol",   "note": "M=地铁站/商圈"},
    "🅿":  {"meaning": "停车/地点",   "category": "symbol",   "note": "P=停车场/见面地点"},
    "🅰":  {"meaning": "A级/一等",   "category": "symbol",   "note": "A型血/一等"},
    "🅱":  {"meaning": "B级/二手",   "category": "symbol",   "note": "B型血/二等"},
    "🅾":  {"meaning": "O型/通用",   "category": "symbol",   "note": "O型血"},
    "🆎":  {"meaning": "混合/AB",    "category": "symbol",   "note": "AB型"},
    "🈯":  {"meaning": "指定/定向",  "category": "symbol",   "note": "指=指定服务"},
    "🈲":  {"meaning": "禁止/违规",  "category": "symbol",   "note": "禁=禁止/违规内容"},
    "🈹":  {"meaning": "打折/优惠",  "category": "symbol",   "note": "割=打折促销"},
    "🈚":  {"meaning": "免费/无",    "category": "symbol",   "note": "无=免费"},
    "🉐":  {"meaning": "划算/值得",  "category": "symbol",   "note": "得=物超所值"},
    "🉑":  {"meaning": "可以/接单",  "category": "symbol",   "note": "可=可接/可做"},
    "㊙":  {"meaning": "秘密/不公开", "category": "symbol",  "note": "秘=私密渠道"},
    "㊗":  {"meaning": "祝贺/中奖",  "category": "symbol",   "note": "祝=恭喜中奖"},
    "〽":  {"meaning": "波动/价格",  "category": "symbol",   "note": "波浪=行情波动"},
}


# ═══════════════════════════════════════════════════════════════════════════════
# EmojiTranslator 类
# ═══════════════════════════════════════════════════════════════════════════════

class EmojiTranslator:
    """Emoji 语义翻译器（惰性单例）。"""

    def __init__(self, use_llm: bool = False):
        self._use_llm = use_llm
        self._meaning_map = EMOJI_MEANING_MAP

    # ── 公共 API ──────────────────────────────────────────────────────────

    def translate(self, text: str, use_llm: bool = False) -> str:
        """将文本中的 emoji 替换为灰黑产语境的中文含义。

        Args:
            text: 含 emoji 的原始文本
            use_llm: 是否用 LLM 翻译词典未覆盖的 emoji（默认 False，零 API 开销）

        Returns:
            翻译后的文本，格式：原始 emoji 后跟 [emoji: 含义]

        Example:
            >>> EmojiTranslator().translate("🛰 douyin_pro888 💰日赚500")
            "🛰[微信] douyin_pro888 💰[赚钱/刷单]日赚500"
        """
        if not text:
            return text

        result_parts = []
        i = 0
        while i < len(text):
            # 检查是否 emoji（可能是多码点序列）
            emoji_seq = self._match_emoji_at(text, i)
            if emoji_seq:
                meaning_info = self._meaning_map.get(emoji_seq)
                if meaning_info:
                    result_parts.append(f"{emoji_seq}[{meaning_info['meaning']}]")
                else:
                    result_parts.append(emoji_seq)
                i += len(emoji_seq)
            else:
                # 还要检查单字符 emoji
                char = text[i]
                if _EMOJI_PATTERN.match(char):
                    meaning_info = self._meaning_map.get(char)
                    if meaning_info:
                        result_parts.append(f"{char}[{meaning_info['meaning']}]")
                    else:
                        result_parts.append(char)
                else:
                    result_parts.append(char)
                i += 1

        return "".join(result_parts)

    def extract_emojis(self, text: str) -> list[dict[str, Any]]:
        """提取文本中所有 emoji 及其结构化信息。

        Returns:
            [{"char": "🛰", "meaning": "微信", "position": 0, "category": "contact"}, ...]
        """
        if not text:
            return []

        results = []
        i = 0
        while i < len(text):
            emoji_seq = self._match_emoji_at(text, i)
            if emoji_seq:
                info = self._meaning_map.get(emoji_seq, {})
                results.append({
                    "char": emoji_seq,
                    "meaning": info.get("meaning", "未知"),
                    "position": i,
                    "category": info.get("category", "unknown"),
                    "note": info.get("note", ""),
                })
                i += len(emoji_seq)
            elif _EMOJI_PATTERN.match(text[i]):
                info = self._meaning_map.get(text[i], {})
                results.append({
                    "char": text[i],
                    "meaning": info.get("meaning", "未知"),
                    "position": i,
                    "category": info.get("category", "unknown"),
                    "note": info.get("note", ""),
                })
                i += 1
            else:
                i += 1

        return results

    def get_emoji_meaning(self, emoji: str) -> str:
        """获取单个 emoji 的灰黑产含义。"""
        info = self._meaning_map.get(emoji)
        return info["meaning"] if info else ""

    def get_emoji_category(self, emoji: str) -> str:
        """获取 emoji 的分类。"""
        info = self._meaning_map.get(emoji)
        return info["category"] if info else "unknown"

    def get_risk_signals(self, text: str) -> dict[str, Any]:
        """从 emoji 角度评估文本的灰黑产风险信号。

        Returns:
            {
                "has_emoji": bool,
                "emoji_count": int,
                "risk_categories": {"contact": 2, "money": 1, ...},  # 各类别 emoji 出现次数
                "translated_text": str,
                "risk_emoji": [{"char": "💰", "meaning": "赚钱/刷单", "category": "money"}, ...],
            }
        """
        emojis = self.extract_emojis(text)
        categories: dict[str, int] = {}
        risk_emoji = []
        for e in emojis:
            cat = e["category"]
            categories[cat] = categories.get(cat, 0) + 1
            if cat in ("contact", "money", "gambling", "adult", "illegal"):
                risk_emoji.append(e)

        return {
            "has_emoji": len(emojis) > 0,
            "emoji_count": len(emojis),
            "risk_categories": categories,
            "translated_text": self.translate(text),
            "risk_emoji": risk_emoji,
        }

    # ── 内部方法 ──────────────────────────────────────────────────────────

    @staticmethod
    def _match_emoji_at(text: str, pos: int) -> str:
        """匹配从 pos 位置开始的多码点 emoji 序列（ZWJ + 肤色修饰符等）。

        例如: 👁‍🗨 (U+1F441 U+200D U+1F5E8) 应作为一个整体.
        """
        if pos >= len(text):
            return ""

        m = _EMOJI_PATTERN.match(text, pos)
        if not m:
            return ""

        # 如果匹配到的字符后面跟着 ZWJ 或 skin tone 或 VS16，继续扩展
        end = m.end()
        while end < len(text):
            cp = text[end]
            if cp in ("‍", "️") or ("\U0001F3FB" <= cp <= "\U0001F3FF"):
                # ZWJ/skin tone 后面必须还有内容
                next_match = _EMOJI_PATTERN.match(text, end + 1)
                if cp == "‍" and next_match:
                    end = next_match.end()
                elif cp == "️":
                    end = end + 1
                elif "\U0001F3FB" <= cp <= "\U0001F3FF":
                    end = end + 1
                else:
                    break
            else:
                break

        return text[pos:end]

    @staticmethod
    def contains_emoji(text: str) -> bool:
        """全面检测文本是否包含 emoji。"""
        return contains_emoji(text)  # 使用模块级函数


# ── 模块级便捷函数 ──────────────────────────────────────────────────────────

def translate_emoji(text: str) -> str:
    """便捷函数：翻译文本中的 emoji。"""
    return emoji_translator.translate(text)


# ═══════════════════════════════════════════════════════════════════════════════
# 单例
# ═══════════════════════════════════════════════════════════════════════════════

emoji_translator = EmojiTranslator()
