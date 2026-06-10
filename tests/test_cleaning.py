"""清洗层测试 — 无需数据库，纯内存测试。

运行: python -m pytest tests/test_cleaning.py -v
"""

import pytest

# ═══════════════════════════════════════════════════════════════════════════════
# 测试数据：各平台模拟真实爬取结果
# ═══════════════════════════════════════════════════════════════════════════════

SAMPLE_DATA = {
    "weibo": [
        # (原始文本, 期望清洗后关键词, 应为噪声?)
        ("刷单平台联系微信xxx  #刷单#", "刷单", False),
        ("展开全文 接码平台日赚500+ 转发微博", "接码", False),
        ("抱歉，由于作者设置，你暂时没有查看该微博的权限", "", True),
        ("纯微博转发 //@张三://@李四:转发微博", "", True),
    ],
    "zhihu": [
        ("谢邀。实名制手机卡接码平台，支持170/171号段，价格优惠。", "接码", False),
        ("知乎用户 发布于 2024/01/15 著作权归作者所有", "", True),
        ("如何评价现在的刷量产业链？以上。编辑于 2024-03-01", "刷量", False),
    ],
    "tieba": [
        ("收各种实名账号，量大价优，私聊", "实名账号", False),
        ("该楼层疑似违规已被系统折叠 隐藏此楼", "", True),
        ("纯表情帖 👍👍👍👍👍👍👍👍👍", "", True),
        ("贴吧正常讨论帖", "讨论", False),
    ],
    "douyin": [
        ("涨粉工作室 #涨粉 #抖音 #热门 #推荐 #上热门 #粉丝 #关注", "涨粉", False),
        ("在抖音，搜索刷单就能找到很多兼职 打开抖音看全文", "刷单", False),
    ],
    "xiaohongshu": [
        ("小红书爆款刷量教程 #刷量 #小红书运营 #涨粉秘籍 #自媒体 #内容创作 #爆款", "刷量", False),
        ("#ootd #穿搭 #日常 #ootd #ootd", "", True),
    ],
    "xianyu": [
        ("出抖音涨粉服务，真人粉不掉，50元1000粉", "涨粉", False),
        ("诚信经营 支持花呗付款 本店出售各类账号", "账号", False),
    ],
    "qq_group": [
        ("出Q号，10位老号，可换绑手机", "Q号", False),
        ("[系统消息]你已被管理员禁言23小时59分钟", "", True),
        ("[CQ:face,id=12][CQ:face,id=12][CQ:face,id=12]", "", True),
        ("邀请张三加入了群聊", "", True),
    ],
}


# ═══════════════════════════════════════════════════════════════════════════════
# Emoji 翻译器测试
# ═══════════════════════════════════════════════════════════════════════════════

class TestEmojiTranslator:
    def test_translate_appends_meaning(self):
        from cleaner.emoji_translator import translate
        result = translate("刷单💰联系")
        assert "[金钱/收益]" in result
        assert "刷单" in result

    def test_translate_no_emoji_returns_original(self):
        from cleaner.emoji_translator import translate
        result = translate("普通文本没有表情")
        assert result == "普通文本没有表情"

    def test_extract_emojis(self):
        from cleaner.emoji_translator import extract_emojis
        results = extract_emojis("刷单💰🔥")
        assert len(results) >= 1
        emoji_chars = [r[1] for r in results]
        assert "💰" in emoji_chars

    def test_emoji_density_low(self):
        from cleaner.emoji_translator import emoji_density
        assert emoji_density("正常中文文本") == 0.0

    def test_emoji_density_high(self):
        from cleaner.emoji_translator import emoji_density
        assert emoji_density("💰🔥🚀") > 0.3

    def test_has_excessive_emojis(self):
        from cleaner.emoji_translator import has_excessive_emojis
        assert has_excessive_emojis("💰💰💰💰💰💰", threshold=0.5)
        assert not has_excessive_emojis("这是一条正常文本💰", threshold=0.5)


# ═══════════════════════════════════════════════════════════════════════════════
# 平台过滤器测试
# ═══════════════════════════════════════════════════════════════════════════════

class TestPlatformFilters:
    def test_all_platforms_have_filters(self):
        from cleaner.platform_filters import PLATFORM_FILTERS
        expected = {"weibo", "zhihu", "tieba", "douyin", "xiaohongshu", "xianyu", "qq_group"}
        assert set(PLATFORM_FILTERS.keys()) == expected

    def test_filter_weibo_removes_boilerplate(self):
        from cleaner.platform_filters import filter_weibo
        text, is_noise, _ = filter_weibo("展开全文 刷单联系 转发微博")
        assert "展开全文" not in text
        assert "转发微博" not in text
        assert "刷单联系" in text
        assert not is_noise

    def test_filter_weibo_detects_permission_error(self):
        from cleaner.platform_filters import filter_weibo
        text, is_noise, reason = filter_weibo(
            "抱歉，由于作者设置，你暂时没有查看该微博的权限"
        )
        assert is_noise or len(text.strip()) < 5

    def test_filter_zhihu_removes_xieyao(self):
        from cleaner.platform_filters import filter_zhihu
        text, is_noise, _ = filter_zhihu("谢邀。实名手机卡接码平台")
        assert "谢邀" not in text
        assert "接码" in text
        assert not is_noise

    def test_filter_tieba_removes_system_fold(self):
        from cleaner.platform_filters import filter_tieba
        text, is_noise, _ = filter_tieba("该楼层疑似违规已被系统折叠 隐藏此楼")
        assert "系统折叠" not in text and "隐藏此楼" not in text
        # 去除后内容为空

    def test_filter_douyin_handles_hashtags(self):
        from cleaner.platform_filters import filter_douyin
        text, is_noise, _ = filter_douyin(
            "涨粉 #抖音 #热门 #推荐 #上热门 #粉丝 #关注"
        )
        # 超过5个hashtag，应该只保留前3个
        assert not is_noise

    def test_filter_xiaohongshu_handles_tags(self):
        from cleaner.platform_filters import filter_xiaohongshu
        text, is_noise, _ = filter_xiaohongshu(
            "刷量教程 #ootd #穿搭 #日常 #ootd #ootd #ootd"
        )
        assert not is_noise
        assert "刷量教程" in text

    def test_filter_xianyu_preserves_price_info(self):
        from cleaner.platform_filters import filter_xianyu
        text, is_noise, _ = filter_xianyu("出抖音涨粉服务，50元1000粉")
        assert not is_noise
        assert "涨粉" in text

    def test_filter_qq_detects_system_message(self):
        from cleaner.platform_filters import filter_qq_group
        text, is_noise, reason = filter_qq_group(
            "[系统消息]你已被管理员禁言23小时59分钟"
        )
        assert is_noise
        assert "系统消息" in reason

    def test_filter_qq_detects_pure_face(self):
        from cleaner.platform_filters import filter_qq_group
        text, is_noise, _ = filter_qq_group("[CQ:face,id=12][CQ:face,id=12][CQ:face,id=12]")
        # 全是CQ码，去除后为空
        assert is_noise or len(text.strip()) < 3

    def test_filter_qq_detects_join_notification(self):
        from cleaner.platform_filters import filter_qq_group
        text, is_noise, _ = filter_qq_group("邀请张三加入了群聊")
        assert is_noise

    def test_filter_unknown_platform_falls_back(self):
        from cleaner.platform_filters import filter_by_platform
        text, is_noise, _ = filter_by_platform("unknown_platform", "正常文本")
        assert not is_noise


# ═══════════════════════════════════════════════════════════════════════════════
# 噪声评分测试
# ═══════════════════════════════════════════════════════════════════════════════

class TestNoiseScorer:
    def test_empty_text_scores_max(self):
        from cleaner.pipeline import NoiseScorer
        score, reasons = NoiseScorer.score("")
        assert score == 1.0
        assert "空文本" in reasons

    def test_valid_intel_scores_low(self):
        from cleaner.pipeline import NoiseScorer
        score, _ = NoiseScorer.score("实名手机卡接码平台日赚500+")
        assert score < 0.3

    def test_pure_emoji_scores_high(self):
        from cleaner.pipeline import NoiseScorer
        score, reasons = NoiseScorer.score("👍👍👍")
        assert score >= 0.5

    def test_short_text_scores_medium(self):
        from cleaner.pipeline import NoiseScorer
        score, _ = NoiseScorer.score("好的")
        assert score >= 0.3

    def test_intel_keywords_reduce_score(self):
        from cleaner.pipeline import NoiseScorer
        score_with, _ = NoiseScorer.score("身份证银行卡手机号接码平台")
        score_without, _ = NoiseScorer.score("今天天气真好适合出去玩")
        assert score_with < score_without


# ═══════════════════════════════════════════════════════════════════════════════
# SimHash 去重测试
# ═══════════════════════════════════════════════════════════════════════════════

class TestSimHash:
    def test_compute_returns_hex(self):
        from cleaner.pipeline import CleaningPipeline
        sh = CleaningPipeline.compute_simhash("测试文本")
        assert sh.startswith("0x")
        assert len(sh) >= 16

    def test_identical_text_same_hash(self):
        from cleaner.pipeline import CleaningPipeline
        a = CleaningPipeline.compute_simhash("刷单平台接码服务")
        b = CleaningPipeline.compute_simhash("刷单平台接码服务")
        assert a == b

    def test_different_text_different_hash(self):
        from cleaner.pipeline import CleaningPipeline
        a = CleaningPipeline.compute_simhash("刷单平台接码服务")
        b = CleaningPipeline.compute_simhash("今天天气真好适合出去玩")
        assert a != b

    def test_similar_text_small_distance(self):
        from cleaner.pipeline import CleaningPipeline
        a = CleaningPipeline.compute_simhash("刷单平台接码服务联系微信")
        b = CleaningPipeline.compute_simhash("刷单平台接码服务联系wechat")
        dist = CleaningPipeline.hamming_distance(a, b)
        assert dist < 10  # 相似文本汉明距离应该很小

    def test_dissimilar_text_large_distance(self):
        from cleaner.pipeline import CleaningPipeline
        a = CleaningPipeline.compute_simhash("刷单平台接码服务")
        b = CleaningPipeline.compute_simhash("今天天气真好适合出去玩")
        dist = CleaningPipeline.hamming_distance(a, b)
        assert dist > 5


# ══════════════════════════════════════════════════════════════════════════════
# 清洗管道端到端测试
# ═══════════════════════════════════════════════════════════════════════════════

class TestCleaningPipeline:
    def test_clean_single_returns_all_fields(self):
        from cleaner.pipeline import CleaningPipeline
        p = CleaningPipeline()
        result = p.clean_single("weibo", "刷单联系微信")
        required = {"text", "original", "simhash", "is_noise", "noise_score",
                     "priority", "should_discard", "steps"}
        assert required.issubset(result.keys())

    def test_clean_single_has_steps(self):
        from cleaner.pipeline import CleaningPipeline
        p = CleaningPipeline()
        result = p.clean_single("weibo", "刷单联系微信💰")
        assert "emoji" in result["steps"]
        assert "platform" in result["steps"]
        assert "normalize" in result["steps"]
        assert "score" in result["steps"]
        assert "priority" in result["steps"]

    def test_clean_batch_dedup_works(self):
        from cleaner.pipeline import CleaningPipeline
        p = CleaningPipeline()
        items = [
            {"id": 1, "platform": "weibo", "content_raw": "刷单平台接码服务联系微信xxx"},
            {"id": 2, "platform": "weibo", "content_raw": "刷单平台接码服务联系微信xxx"},  # 完全相同
        ]
        results = p.clean_batch(items)
        # 第一条保留，第二条重复丢弃
        assert results[0]["status"] == "CLEANED"
        assert results[1]["is_duplicate"]
        assert results[1]["should_discard"]

    def test_clean_batch_mixed_results(self):
        from cleaner.pipeline import CleaningPipeline
        p = CleaningPipeline()
        items = [
            {"id": 1, "platform": "weibo", "content_raw": "刷单接码平台联系QQ"},
            {"id": 2, "platform": "tieba", "content_raw": "该楼层疑似违规已被系统折叠"},
            {"id": 3, "platform": "qq_group", "content_raw": "[系统消息]你已被禁言"},
            {"id": 4, "platform": "zhihu", "content_raw": "谢邀。如何评价刷量黑产？"},
        ]
        results = p.clean_batch(items)
        statuses = {r["id"]: r["status"] for r in results}
        # #1 和 #4 应该保留，#2 和 #3 应该丢弃
        assert statuses[1] == "CLEANED"
        assert statuses[4] == "CLEANED"
        assert statuses[2] == "DISCARDED"
        assert statuses[3] == "DISCARDED"

    def test_all_platforms_clean_without_error(self):
        from cleaner.pipeline import CleaningPipeline
        p = CleaningPipeline()
        for platform, samples in SAMPLE_DATA.items():
            for raw_text, _, _ in samples:
                result = p.clean_single(platform, raw_text)
                assert "text" in result
                assert "simhash" in result

    def test_noise_items_discarded(self):
        """各平台的噪声样本都应该被丢弃。"""
        from cleaner.pipeline import CleaningPipeline
        p = CleaningPipeline()
        noise_cases = [
            ("tieba", "该楼层疑似违规已被系统折叠", "贴吧系统折叠"),
            ("tieba", "纯表情帖 👍👍👍👍👍👍👍👍👍👍", "贴吧纯表情"),
            ("qq_group", "[系统消息]你已被管理员禁言23小时59分钟", "QQ系统消息"),
            ("qq_group", "邀请张三加入了群聊", "QQ入群通知"),
            ("weibo", "抱歉，由于作者设置，你暂时没有查看该微博的权限", "微博权限错误"),
        ]
        for platform, text, desc in noise_cases:
            result = p.clean_single(platform, text)
            assert result["should_discard"], f"应丢弃 {desc}: {text[:50]}"

    def test_short_weak_keyword_is_discarded(self):
        """只命中弱风险词、没有交易动作和联系方式的短标题不进入研判。"""
        from cleaner.pipeline import CleaningPipeline
        p = CleaningPipeline()
        result = p.clean_single(
            "xiaohongshu",
            "【标题】华西黄牛",
            author_username="羊洋扬",
            source_keyword="黄牛",
        )
        assert result["should_discard"]
        assert "短文本仅命中弱风险词" in result["noise_reason"]

    def test_actionable_keyword_with_contact_is_kept(self):
        """有核心风险词、交易动作和联系方式的内容要保留。"""
        from cleaner.pipeline import CleaningPipeline
        p = CleaningPipeline()
        result = p.clean_single(
            "telegram",
            "接码平台推荐，海外实体卡，包教包会，联系微信 douyin_pro888",
            source_keyword="接码",
        )
        assert not result["should_discard"]
        assert result["relevance_score"] >= 0.3

    def test_public_warning_without_traceable_entity_is_discarded(self):
        """官方/媒体预警类内容没有联系方式或交易动作时不进入研判池。"""
        from cleaner.pipeline import CleaningPipeline
        p = CleaningPipeline()
        result = p.clean_single(
            "weibo",
            "警惕刷单兼职类诈骗，公安提醒全民反诈",
            author_username="平安检察",
            source_keyword="刷单",
        )
        assert result["should_discard"]
        assert "媒体/警方提示类内容" in result["noise_reason"]

    def test_intel_items_kept(self):
        """各平台的情报样本都应该保留。"""
        from cleaner.pipeline import CleaningPipeline
        p = CleaningPipeline()
        intel_cases = [
            ("weibo", "刷单接码平台联系QQ微信xxx", "微博刷单"),
            ("zhihu", "如何找靠谱的接码平台？实名手机卡哪里买？", "知乎接码"),
            ("tieba", "收各种实名账号，量大价优", "贴吧账号交易"),
            ("douyin", "涨粉工作室，50元1000粉，真人粉不掉", "抖音涨粉"),
            ("xiaohongshu", "分享一个靠谱的刷量渠道，亲测有效", "小红书刷量"),
            ("xianyu", "出抖音涨粉服务，真人粉不掉，50元1000粉", "闲鱼涨粉"),
            ("qq_group", "出Q号，10位老号，可换绑手机", "QQ号交易"),
        ]
        for platform, text, desc in intel_cases:
            result = p.clean_single(platform, text)
            assert not result["should_discard"], f"应保留 {desc}: {text[:50]}"

    def test_priority_high_for_risk_keywords(self):
        from cleaner.pipeline import CleaningPipeline
        p = CleaningPipeline()
        result = p.clean_single("weibo", "出售实名银行卡四件套")
        # "银行卡" 应在 HIGH_RISK_KEYWORDS 中
        assert result["priority"] == "high" or result["priority"] == "HIGH"

    def test_compat_process_method(self):
        """兼容旧的 process() 接口。"""
        from cleaner.pipeline import CleaningPipeline
        p = CleaningPipeline()
        result = p.process("刷单接码平台", platform="weibo")
        assert "text" in result
        assert "simhash" in result
        assert "should_discard" in result


# ═══════════════════════════════════════════════════════════════════════════════
# 边界条件测试
# ═══════════════════════════════════════════════════════════════════════════════

class TestEdgeCases:
    def test_empty_string(self):
        from cleaner.pipeline import CleaningPipeline
        p = CleaningPipeline()
        result = p.clean_single("weibo", "")
        assert result["should_discard"]

    def test_whitespace_only(self):
        from cleaner.pipeline import CleaningPipeline
        p = CleaningPipeline()
        result = p.clean_single("weibo", "   \n  \t  ")
        assert result["should_discard"]

    def test_very_long_text(self):
        from cleaner.pipeline import CleaningPipeline
        p = CleaningPipeline()
        long_text = "刷单联系微信" * 200
        result = p.clean_single("weibo", long_text)
        assert len(result["text"]) > 0

    def test_mixed_languages(self):
        from cleaner.pipeline import CleaningPipeline
        p = CleaningPipeline()
        result = p.clean_single("weibo",
            "DDoS攻击平台 C2 server 上线 肉鸡 僵尸网络 botnet")
        assert not result["should_discard"]

    def test_html_in_text(self):
        from cleaner.pipeline import CleaningPipeline
        p = CleaningPipeline()
        result = p.clean_single("weibo",
            "<div>刷单</div><br/>联系<span>微信</span>")
        assert "刷单" in result["text"]
        assert "<div>" not in result["text"]
        assert "<br/>" not in result["text"]

    def test_unicode_escape(self):
        from cleaner.pipeline import CleaningPipeline
        p = CleaningPipeline()
        result = p.clean_single("weibo",
            r"刷单接码平台")  # 接码平台 = 接码平台
        assert "接码平台" in result["text"]

    def test_batch_empty_list(self):
        from cleaner.pipeline import CleaningPipeline
        p = CleaningPipeline()
        results = p.clean_batch([])
        assert results == []
