"""数据清洗管道 — 完整的 6 步清洗流程。

Step 0: Emoji 语义翻译   → 提取 emoji，追加中文语义说明
Step 1: 平台感知清洗      → 调用 platform_filters 去除平台特定噪声
Step 2: 文本规范化        → HTML标签、空白符、全半角统一
Step 3: SimHash 去重      → 作者感知去重：同一作者+相似内容=重复，不同作者=情报线索
Step 4: 噪声评分          → 0.0-1.0 综合噪声分数
Step 5: 优先级标记        → 高危关键词 → HIGH，否则 NORMAL

核心设计原则：
  - 同一内容 + 同一作者  = 重复（丢弃）
  - 同一内容 + 不同作者  = 情报线索（保留，标注相似群组）—— 不同卖家发同样的服务说明
    意味着多个独立来源，恰恰是情报价值所在
  - 短文本 + 含情报关键词 = 不丢弃 —— QQ/群聊中的短消息往往是直接的交易信号
  - [image]/[video] 占位消息 → MEDIA_ONLY 状态（不丢弃，标记为需媒体分析）

支持两种模式：
  - clean_batch(): 批量清洗，自动维护 seen_hashes 实现去重
  - clean_single(): 单条清洗，用于调试和实时采集
"""

from __future__ import annotations

import re
import hashlib
from typing import Optional
from loguru import logger

from config.settings import settings
from schema import HIGH_RISK_KEYWORDS, Priority

# ═══════════════════════════════════════════════════════════════════════════════
# SimHash 引擎
# ═══════════════════════════════════════════════════════════════════════════════

try:
    from simhash import SimHash as _SimHashC  # type: ignore

    def _compute_simhash(text: str) -> str:
        return hex(_SimHashC(text).value)
except ImportError:
    from cleaner.simhash_py import SimHash as _SimHashPy

    def _compute_simhash(text: str) -> str:
        return hex(_SimHashPy(text).value)


# ═══════════════════════════════════════════════════════════════════════════════
# 噪声评分器
# ═══════════════════════════════════════════════════════════════════════════════

class NoiseScorer:
    """多维度噪声评分，综合判断内容质量。"""

    # ── 加分项（内容质量高）──
    BONUS_KEYWORDS = [
        "实名", "身份证", "银行卡", "手机号", "支付宝", "微信",
        "QQ号", "账号", "密码", "验证码", "接码", "刷单",
        "涨粉", "解封", "代收", "代付", "跑分", "洗钱",
        "USDT", "BTC", "ETH", "虚拟币", "交易所", "搬砖",
        "引流", "吸粉", "买粉", "买量", "刷量", "刷赞",
        "劫持", "木马", "病毒", "后门", "免杀", "壳",
        "肉鸡", "僵尸", "DDOS", "CC攻击", "撞库", "脱库",
    ]

    # ── 减分项（噪声特征）──
    PENALTY_PATTERNS = [
        (re.compile(r"^(.)\1{5,}$"), 0.3, "单字符重复"),
        (re.compile(r"[!！?？]{3,}"), 0.15, "过多标点"),
        (re.compile(r"http"), 0.05, "含URL"),
        (re.compile(r"@\w+"), 0.05, "含@提及"),
    ]

    @classmethod
    def score(cls, text: str) -> tuple[float, list[str]]:
        """计算噪声分数。

        Returns:
            (noise_score, reasons): 0.0=干净, 1.0=完全噪声, 及原因列表
        """
        if not text or not text.strip():
            return 1.0, ["空文本"]

        score = 0.0
        reasons: list[str] = []

        # ── 基础分：文本长度（含情报关键词的短文本不重罚）──
        length = len(text)
        has_intel_signal = any(kw in text for kw in cls.BONUS_KEYWORDS)
        if length < 5:
            if has_intel_signal:
                score += 0.15   # 有情报纸条的极短文本：可能是直接报价/联系方式
                reasons.append(f"极短情报({length}字)")
            else:
                score += 0.5
                reasons.append(f"文本过短({length}字)")
        elif length < 15:
            if has_intel_signal:
                # 短但含情报关键词，不惩罚（QQ/群聊中常见）
                pass
            else:
                score += 0.2
                reasons.append(f"文本较短({length}字)")

        # ── 中文字符比例 ──
        chinese_chars = len(re.findall(r"[一-鿿]", text))
        total_chars = len(text.replace(" ", "").replace("\n", ""))
        if total_chars > 0:
            chinese_ratio = chinese_chars / total_chars
            if chinese_ratio < 0.1:
                score += 0.3
                reasons.append(f"中文比例过低({chinese_ratio:.0%})")
            elif chinese_ratio < 0.3:
                score += 0.1
                reasons.append(f"中文比例偏低({chinese_ratio:.0%})")

        # ── Emoji 密度 ──
        from cleaner.emoji_translator import emoji_density
        density = emoji_density(text)
        if density > 0.5:
            score += 0.4
            reasons.append(f"Emoji密度过高({density:.0%})")
        elif density > 0.3:
            score += 0.15
            reasons.append(f"Emoji密度偏高({density:.0%})")

        # ── 减分模式 ──
        for pattern, penalty, reason in cls.PENALTY_PATTERNS:
            if pattern.search(text):
                score += penalty
                reasons.append(reason)

        # ── 加分：含灰黑产关键词 ──
        bonus_count = sum(1 for kw in cls.BONUS_KEYWORDS if kw in text)
        if bonus_count >= 3:
            score -= 0.15
            reasons.append(f"含{bonus_count}个情报关键词")
        elif bonus_count >= 1:
            score -= 0.05
            reasons.append(f"含{bonus_count}个情报关键词")

        # ── 纯数字/符号 ──
        nonsymbol = re.findall(r"[一-鿿a-zA-Z0-9]", text)
        if len(nonsymbol) == 0:
            score += 0.6
            reasons.append("无有效文字")

        return max(0.0, min(1.0, score)), reasons


# ═══════════════════════════════════════════════════════════════════════════════
# 清洗管道
# ═══════════════════════════════════════════════════════════════════════════════

class CleaningPipeline:
    """6 步清洗管道，所有步骤零 LLM 调用。

    核心设计：
      - 作者感知去重：同一作者+相似内容=重复；不同作者+相似内容=情报线索（保留）
      - 短情报保护：含黑灰产关键词的短文本不受长度惩罚（QQ/群聊中的交易信号）
      - 媒体占位处理：[image]/[video] 等占位符 → MEDIA_ONLY 状态（不丢弃）
      - 内容角色标注：区分「灰产从业者发布」「媒体报道」「受害者讲述」「警方警示」

    用法:
        pipeline = CleaningPipeline()

        # 批量清洗（带去重）
        results = pipeline.clean_batch([
            {"id": 1, "platform": "weibo", "content_raw": "...", "author_uid": "123"},
            {"id": 2, "platform": "zhihu", "content_raw": "...", "author_uid": "456"},
        ])

        # 单条清洗（不去重，调试用）
        result = pipeline.clean_single("weibo", "刷单联系微信xxx", author_uid="123")
    """

    def __init__(self, simhash_threshold: int = None):
        self.simhash_threshold = simhash_threshold or settings.simhash_threshold
        # 作者感知的去重记录：{simhash: {author_uid: summary}}
        self._seen_authors: dict[str, dict[str, str]] = {}
        # 相似内容群组（用于跨作者交叉引用）
        self._similarity_groups: dict[str, list[str]] = {}
        # 兼容旧接口
        self._seen_hashes: dict[str, str] = {}

    # ── Step 0: Emoji 翻译 ──────────────────────────────────────────────

    @staticmethod
    def _step_emoji(text: str) -> dict:
        """Emoji 语义翻译。"""
        from cleaner.emoji_translator import translate, extract_emojis
        emojis = extract_emojis(text)
        translated = translate(text, append=True)
        return {
            "text": translated,
            "emojis_found": [e[1] for e in emojis],
            "emoji_count": len(emojis),
        }

    # ── Step 1: 平台感知清洗 ─────────────────────────────────────────────

    @staticmethod
    def _step_platform(platform: str, text: str) -> dict:
        """调用平台过滤器去除噪声。"""
        from cleaner.platform_filters import filter_by_platform
        cleaned, is_noise, reason = filter_by_platform(platform, text)
        return {
            "text": cleaned,
            "is_platform_noise": is_noise,
            "platform_noise_reason": reason,
        }

    # ── Step 2: 文本规范化 ──────────────────────────────────────────────

    @staticmethod
    def _step_normalize(text: str) -> dict:
        """基础文本规范化。"""
        # HTML 标签
        text = re.sub(r"<[^>]+>", " ", text)
        # HTML 实体
        text = re.sub(r"&[a-zA-Z]+;|&#\d+;", " ", text)
        # 零宽字符
        text = text.replace("​", "").replace("​", "").replace("‌", "").replace("‍", "")
        # Unicode 转义
        try:
            text = re.sub(r"\\u([0-9a-fA-F]{4})", lambda m: chr(int(m.group(1), 16)), text)
        except (ValueError, OverflowError):
            pass
        # 不换行空格
        text = text.replace("\xa0", " ")
        # 空白规范
        text = re.sub(r"\s+", " ", text)
        return {"text": text.strip()}

    # ── Step 3: SimHash 去重（作者感知）─────────────────────────────────

    @staticmethod
    def compute_simhash(text: str) -> str:
        """计算文本的 SimHash 指纹。"""
        return _compute_simhash(text)

    @staticmethod
    def hamming_distance(a: str, b: str) -> int:
        """两个 hex SimHash 的汉明距离。"""
        if len(a) != len(b):
            return max(len(a), len(b)) * 4
        x = int(a, 16) ^ int(b, 16)
        return x.bit_count()

    @staticmethod
    def compute_md5(text: str) -> str:
        """计算文本的 MD5 哈希（用于精确去重）。"""
        import hashlib
        return hashlib.md5(text.encode("utf-8")).hexdigest()

    def _check_duplicate(self, new_hash: str, author_uid: str = "",
                         text: str = "") -> dict:
        """作者感知去重检查。

        去重策略（按优先级）：
          1. 同一作者 + 汉明距离 ≤ threshold + 文本长度≥30字 → DUPLICATE
             （短文本（<30字）即使距离近也可能只是同作者的不同帖子/标题，不判重）
          2. 不同作者 + 汉明距离 ≤ threshold → SIMILAR
             （多人发同一内容=情报线索，保留！）
          3. 无作者信息 + 汉明距离 ≤ threshold → 保守：不判定为重复
          4. 汉明距离 > threshold → UNIQUE

        Returns:
            {"is_duplicate": bool, "is_similar": bool, "similar_to": str,
             "dup_type": "SAME_AUTHOR"|"CROSS_AUTHOR"|None}
        """
        result = {"is_duplicate": False, "is_similar": False,
                  "similar_to": "", "dup_type": None}

        # 如果没有作者信息，不做去重判定（保守策略：不因缺元数据而丢情报）
        if not author_uid or not author_uid.strip():
            return result

        # 短文本放宽阈值：短标题/短消息即使距离近也可能是不同内容
        text_len = len(text) if text else 0
        effective_threshold = self.simhash_threshold
        if text_len < 30:
            # 短文本：汉明距离必须为0（精确相同）才可能判重
            effective_threshold = 0
        elif text_len < 80:
            # 中等文本：阈值减半（≤1）
            effective_threshold = max(1, self.simhash_threshold // 2)

        for seen_hash, authors in self._seen_authors.items():
            dist = self.hamming_distance(new_hash, seen_hash)
            if dist <= effective_threshold:
                if author_uid in authors:
                    # 同一作者，相似内容 → 真正重复
                    result["is_duplicate"] = True
                    result["dup_type"] = "SAME_AUTHOR"
                    result["similar_to"] = authors[author_uid][:80]
                    return result
                else:
                    # 不同作者，相似内容 → 情报线索（可能是多人发同一广告/服务）
                    result["is_similar"] = True
                    result["dup_type"] = "CROSS_AUTHOR"
                    # 收集跨作者引用的摘要
                    other_authors = [a for a in authors.keys() if a != "__unknown__"]
                    if other_authors:
                        result["similar_to"] = f"author(s): {', '.join(other_authors[:3])}"
                    else:
                        result["similar_to"] = "cross-author match"
                    return result

        return result

    def _record_hash(self, simhash: str, author_uid: str = "", summary: str = ""):
        """记录 hash，关联作者。无作者信息时不做关联记录（避免跨条目误判）。"""
        if simhash not in self._seen_authors:
            self._seen_authors[simhash] = {}
        if author_uid and author_uid.strip():
            self._seen_authors[simhash][author_uid] = summary[:80] if summary else ""

    # 兼容旧接口
    def _is_duplicate(self, new_hash: str) -> tuple[bool, Optional[str]]:
        """旧版去重接口（仅用于兼容 process() 方法）。"""
        result = self._check_duplicate(new_hash, author_uid="", text="")
        return result["is_duplicate"], result.get("similar_to")

    # ── 内容角色检测 ─────────────────────────────────────────────────

    # 媒体/官方账号特征词（发布者可能是报道者而非灰产参与者）
    NEWS_SOURCE_PATTERNS = [
        "新闻", "日报", "晚报", "都市报", "财经", "传媒", "资讯",
        "警方", "警察", "公安", "检察院", "法院", "网警", "反诈",
        "律师", "法律", "律所", "司法",
        "记者", "编辑", "小编",
        "曝光", "揭秘", "警惕", "注意", "提醒", "预警",
    ]

    @classmethod
    def detect_content_role(cls, text: str, author_username: str = "",
                            platform: str = "") -> str:
        """检测内容角色：区分发布者立场。

        Returns:
            "actor" — 疑似灰产从业者/参与者
            "media" — 媒体/官方报道
            "police" — 警方/反诈警示
            "victim" — 受害者自述
            "unknown" — 无法判断
        """
        text_lower = text.lower()

        # 警方/反诈
        police_kw = ["警方", "警察", "公安", "反诈", "网警", "检察院", "法院",
                     "抓获", "破获", "打掉", "摧毁", "抓捕", "犯罪嫌疑人"]
        if any(kw in text for kw in police_kw):
            return "police"

        # 受害者自述
        victim_kw = ["被骗", "被骗了", "上当", "亏了", "坑了", "血泪",
                     "借钱", "还不上了", "逾期", "催收", "爆通讯录",
                     "我该怎么办", "求助", "有没有人"]
        if any(kw in text for kw in victim_kw):
            return "victim"

        # 媒体/新闻
        if any(kw in author_username for kw in cls.NEWS_SOURCE_PATTERNS):
            return "media"
        media_kw = ["记者", "据报道", "本报讯", "近日", "爆料", "曝光",
                    "揭秘", "震惊", "扩散", "提醒", "警惕"]
        if sum(1 for kw in media_kw if kw in text) >= 2:
            return "media"

        # 疑似灰产从业者（发广告/服务/交易信息）
        actor_kw = ["出号", "接码", "出抖", "卖号", "收号", "刷单", "日结",
                    "需要的来", "懂的来", "私我", "加我", "联系我",
                    "一手", "批发", "低价", "量大", "出量", "价格"]
        if any(kw in text for kw in actor_kw):
            return "actor"

        return "unknown"

    # ── Step 4: 噪声评分 ────────────────────────────────────────────────

    @staticmethod
    def _step_score(text: str) -> dict:
        """计算综合噪声分数。"""
        score, reasons = NoiseScorer.score(text)
        return {
            "noise_score": round(score, 4),
            "noise_reasons": reasons,
        }

    # ── Step 5: 优先级标记 ──────────────────────────────────────────────

    @staticmethod
    def _step_priority(text: str) -> dict:
        """高危关键词标记。"""
        text_lower = text.lower()
        for kw in HIGH_RISK_KEYWORDS:
            if kw in text_lower:
                return {"priority": Priority.HIGH, "matched_keyword": kw}
        return {"priority": Priority.NORMAL, "matched_keyword": ""}

    # ── 主入口 ──────────────────────────────────────────────────────────

    def clean_single(self, platform: str, text: str,
                     author_uid: str = "", author_username: str = "",
                     skip_dedup: bool = True) -> dict:
        """单条清洗。

        Args:
            platform: 平台标识
            text: 原始文本
            author_uid: 作者 UID（用于作者感知去重）
            author_username: 作者昵称（用于内容角色检测）
            skip_dedup: 单条清洗默认跳过去重（去重在 clean_batch 中进行）

        Returns:
            {
                "text": str,              # 清洗后文本
                "original": str,          # 原始文本
                "simhash": str,           # SimHash 指纹
                "md5": str,               # MD5 精确哈希
                "is_noise": bool,         # 是否判定为噪声
                "is_media_only": bool,    # 是否为纯媒体占位（[image]/[video]等）
                "content_role": str,      # 内容角色: actor/media/police/victim/unknown
                "noise_reason": str,      # 噪声原因（汇总）
                "noise_score": float,     # 噪声分数 0-1
                "priority": str,          # normal / high
                "should_discard": bool,   # 是否应丢弃（不含去重判定）
                "steps": {                # 各步骤详情
                    "emoji": {...},
                    "platform": {...},
                    "normalize": {...},
                    "score": {...},
                    "priority": {...},
                },
            }
        """
        original = text
        steps: dict[str, dict] = {}

        # ── 媒体占位检测 ──
        MEDIA_PLACEHOLDERS = [
            "[image]", "[视频]", "[video]", "[图片]", "[语音]", "[文件]",
            "[file]", "[audio]", "[表情]", "[sticker]", "[贴纸]",
            "(纯媒体消息)", "【无文本内容】", "【仅图片】", "【仅视频】",
        ]
        is_media_only = any(text.strip() == mp for mp in MEDIA_PLACEHOLDERS)
        if not is_media_only:
            # 检查是否只有媒体占位 + 极少文字（如 "[image] 看看"）
            stripped = text.strip()
            for mp in MEDIA_PLACEHOLDERS:
                stripped = stripped.replace(mp, "")
            if len(stripped.strip()) <= 2:
                is_media_only = True

        # Step 0: Emoji 提取
        emoji_result = self._step_emoji(text)
        steps["emoji"] = emoji_result

        # Step 1: 平台感知清洗（使用原始文本，避免 emoji 翻译稀释密度影响判断）
        platform_result = self._step_platform(platform, text)
        text_cleaned = platform_result["text"]
        steps["platform"] = platform_result

        # 非噪声条目：对清洗后文本追加 emoji 语义
        if emoji_result["emoji_count"] > 0 and not platform_result["is_platform_noise"]:
            from cleaner.emoji_translator import translate
            text_cleaned = translate(text_cleaned, append=True)

        # Step 2: 文本规范化
        norm_result = self._step_normalize(text_cleaned)
        text_cleaned = norm_result["text"]
        steps["normalize"] = norm_result

        # Step 3: 计算 SimHash + MD5（不在 clean_single 中做去重）
        sh = self.compute_simhash(text_cleaned)
        md5 = self.compute_md5(text_cleaned)

        # Step 4: 噪声评分
        score_result = self._step_score(text_cleaned)
        steps["score"] = score_result

        # Step 5: 优先级
        priority_result = self._step_priority(text_cleaned)
        steps["priority"] = priority_result

        # ── 内容角色检测 ──
        content_role = self.detect_content_role(text_cleaned, author_username, platform)

        # ── 综合判断 ──
        if is_media_only:
            # 纯媒体消息：不丢弃（可能包含有价值的图片/视频）
            is_noise = False
        else:
            is_noise = (
                platform_result["is_platform_noise"]
                or score_result["noise_score"] >= 0.6
                or len(text_cleaned.strip()) < 3
            )

        noise_reason_parts = []
        if platform_result.get("platform_noise_reason"):
            noise_reason_parts.append(platform_result["platform_noise_reason"])
        if score_result["noise_reasons"]:
            noise_reason_parts.append("; ".join(score_result["noise_reasons"]))
        if len(text_cleaned.strip()) < 3 and not is_media_only:
            noise_reason_parts.append("文本过短(<3字符)")

        # 媒体占位：特殊标注
        if is_media_only and not noise_reason_parts:
            noise_reason_parts.append("纯媒体占位消息")

        return {
            "text": text_cleaned,
            "original": original,
            "simhash": sh,
            "md5": md5,
            "is_noise": is_noise,
            "is_media_only": is_media_only,
            "content_role": content_role,
            "noise_reason": " | ".join(noise_reason_parts) if noise_reason_parts else "",
            "noise_score": score_result["noise_score"],
            "priority": priority_result["priority"],
            "should_discard": is_noise,  # 不含去重判定，在 clean_batch 中合并
            "steps": steps,
        }

    def clean_batch(self, items: list[dict]) -> list[dict]:
        """批量清洗，维护作者感知的去重状态。

        Args:
            items: [{"id": int, "platform": str, "content_raw": str,
                      "author_uid": str, "author_username": str}, ...]

        Returns:
            [{"id": int, "platform": str, "text": str, "simhash": str,
              "md5": str, "is_noise": bool, "is_duplicate": bool,
              "is_similar": bool, "similar_to": str, "dup_type": str,
              "is_media_only": bool, "content_role": str,
              "should_discard": bool, "noise_score": float,
              "priority": str, "status": str}, ...]

        Status 取值:
          - CLEANED: 清洗通过，非重复
          - DISCARDED: 噪声或真正重复（同一作者+相似内容）
          - MEDIA_ONLY: 纯媒体占位消息，保留但标记
          - SIMILAR: 与已存在内容相似但作者不同（情报线索，保留）
        """
        results = []
        stats = {"cleaned": 0, "discarded": 0, "media_only": 0, "similar": 0}

        for item in items:
            raw_id = item.get("id", 0)
            platform = item.get("platform", "unknown")
            raw_text = item.get("content_raw", "")
            author_uid = item.get("author_uid", "")
            author_username = item.get("author_username", "")

            # 单条清洗
            single = self.clean_single(platform, raw_text,
                                       author_uid=author_uid,
                                       author_username=author_username,
                                       skip_dedup=True)

            # ── 作者感知去重检查 ──
            dedup = self._check_duplicate(single["simhash"], author_uid, single["text"])

            # ── 确定最终状态 ──
            if single["is_media_only"]:
                # 纯媒体占位 → MEDIA_ONLY（保留，标记为需媒体分析）
                status = "MEDIA_ONLY"
                stats["media_only"] += 1
                self._record_hash(single["simhash"], author_uid, single["text"])
            elif single["should_discard"]:
                # 噪声（平台规则判定或评分过高或过短）
                status = "DISCARDED"
                stats["discarded"] += 1
            elif dedup["is_duplicate"]:
                # 同一作者 + 相似内容 → 真正重复，丢弃
                status = "DISCARDED"
                stats["discarded"] += 1
                dup_reason = f"作者重复({dedup['dup_type']})"
                if single["noise_reason"]:
                    single["noise_reason"] = dup_reason + " | " + single["noise_reason"]
                else:
                    single["noise_reason"] = dup_reason
            elif dedup["is_similar"]:
                # 不同作者 + 相似内容 → 情报线索（保留！）
                status = "SIMILAR"
                stats["similar"] += 1
                self._record_hash(single["simhash"], author_uid, single["text"])
            else:
                # 全新内容
                status = "CLEANED"
                stats["cleaned"] += 1
                self._record_hash(single["simhash"], author_uid, single["text"])

            # 跨作者引用信息
            similar_to = ""
            if dedup.get("similar_to"):
                similar_to = dedup["similar_to"]

            results.append({
                "id": raw_id,
                "platform": platform,
                "text": single["text"],
                "original": raw_text,
                "simhash": single["simhash"],
                "md5": single["md5"],
                "is_noise": single["is_noise"],
                "is_duplicate": dedup["is_duplicate"],
                "is_similar": dedup["is_similar"],
                "similar_to": similar_to,
                "dup_type": dedup.get("dup_type", ""),
                "is_media_only": single["is_media_only"],
                "content_role": single["content_role"],
                "should_discard": status == "DISCARDED",
                "noise_score": single["noise_score"],
                "noise_reason": single["noise_reason"],
                "priority": single["priority"],
                "status": status,
                "steps": single["steps"],
            })

            # 进度汇报
            total = len(results)
            if total % 20 == 0:
                logger.info(
                    f"Cleaning: {total} items → "
                    f"{stats['cleaned']} cleaned, {stats['similar']} similar(diff author), "
                    f"{stats['media_only']} media_only, {stats['discarded']} discarded"
                )

        total = len(results)
        logger.info(
            f"Cleaning complete: {total} items → "
            f"{stats['cleaned']} cleaned, {stats['similar']} similar(diff author), "
            f"{stats['media_only']} media_only, {stats['discarded']} discarded"
        )
        return results

    # ── 兼容旧接口 ──────────────────────────────────────────────────────

    def process(self, raw_text: str, existing_hashes: list[str] = None,
                platform: str = "unknown", author_uid: str = "",
                author_username: str = "") -> dict:
        """兼容旧版 CleaningPipeline.process() 接口。

        供 main.py clean 命令使用。
        """
        existing_hashes = existing_hashes or []

        # 先用新管道清洗
        result = self.clean_single(platform, raw_text,
                                   author_uid=author_uid,
                                   author_username=author_username)

        # 作者感知去重检查
        dedup = self._check_duplicate(result["simhash"], author_uid, result["text"])

        # 检查旧版 hash 去重（兼容）
        dup_legacy = False
        for h in existing_hashes:
            if self.hamming_distance(result["simhash"], h) <= self.simhash_threshold:
                dup_legacy = True
                break

        # 媒体占位特殊处理
        if result["is_media_only"]:
            self._record_hash(result["simhash"], author_uid, result["text"])
            return {
                "text": result["text"],
                "simhash": result["simhash"],
                "md5": result["md5"],
                "is_duplicate": False,
                "is_similar": False,
                "is_media_only": True,
                "content_role": result["content_role"],
                "is_noise": False,
                "noise_reason": result["noise_reason"],
                "priority": result["priority"],
                "should_discard": False,  # MEDIA_ONLY 不丢弃
                "status": "MEDIA_ONLY",
            }

        # 作者感知去重判定
        if dedup["is_duplicate"]:
            return {
                "text": result["text"],
                "simhash": result["simhash"],
                "md5": result["md5"],
                "is_duplicate": True,
                "is_similar": False,
                "is_media_only": False,
                "content_role": result["content_role"],
                "is_noise": result["is_noise"],
                "noise_reason": f"作者重复({dedup.get('dup_type', '')}) | {result['noise_reason']}",
                "priority": result["priority"],
                "should_discard": True,
                "status": "DISCARDED",
            }

        if dedup["is_similar"]:
            self._record_hash(result["simhash"], author_uid, result["text"])
            return {
                "text": result["text"],
                "simhash": result["simhash"],
                "md5": result["md5"],
                "is_duplicate": False,
                "is_similar": True,
                "similar_to": dedup.get("similar_to", ""),
                "is_media_only": False,
                "content_role": result["content_role"],
                "is_noise": result["is_noise"],
                "noise_reason": result["noise_reason"],
                "priority": result["priority"],
                "should_discard": result["should_discard"] or dup_legacy,
                "status": "SIMILAR" if not result["should_discard"] and not dup_legacy else "DISCARDED",
            }

        # 全新内容
        self._record_hash(result["simhash"], author_uid, result["text"])
        return {
            "text": result["text"],
            "simhash": result["simhash"],
            "md5": result["md5"],
            "is_duplicate": False,
            "is_similar": False,
            "is_media_only": False,
            "content_role": result["content_role"],
            "is_noise": result["is_noise"],
            "noise_reason": result["noise_reason"],
            "priority": result["priority"],
            "should_discard": result["should_discard"] or dup_legacy,
            "status": "CLEANED" if not result["should_discard"] and not dup_legacy else "DISCARDED",
        }

    # 保留旧版的静态方法兼容
    @staticmethod
    def normalize(text: str) -> str:
        """兼容旧版：仅做基础规范化。"""
        return CleaningPipeline._step_normalize(text)["text"]
