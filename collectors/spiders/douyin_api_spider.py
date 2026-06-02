"""
抖音 AJAX API Spider — 纯 HTTP 请求，无需浏览器。
基于抖音内部 AJAX 接口，获取热搜榜数据。

可用的 API:
  - 热搜榜: aweme/v1/web/hot/search/list/  (公开，Cookie增强稳定性)
  - 搜索API需要客户端签名(msToken/X-Bogus)，纯HTTP不可用

热搜榜返回:
  - word_list: 50条热搜词 (word, hot_value, group_id, video_count, label, etc.)
  - trending_list: 5条实时上升热点

用法:
    spider = DouyinAPISpider()
    hot = spider.get_hot_search()
    gray_items = spider.filter_gray_market(hot)  # 过滤灰黑产相关
"""

import time
import random
import requests
from datetime import datetime
from dataclasses import dataclass, field
from loguru import logger

from collectors.spiders.base_spider import BaseSpider


# 灰黑产风险关键词（匹配热搜词）
GRAY_KEYWORDS = [
    "刷单", "诈骗", "接码", "出号", "代付", "跑分", "博彩", "赌博",
    "色情", "裸聊", "招嫖", "外挂", "辅助", "脚本", "薅羊毛",
    "套现", "洗钱", "盗号", "撞库", "猫池", "卡商", "代理IP",
    "VPN", "暗网", "数据买卖", "隐私泄露", "批量注册", "群控",
    "云手机", "模拟器", "代收", "四件套", "八件套", "假币",
    "伪基站", "枪支", "毒品", "网赌", "网警", "违禁",
]


@dataclass
class ParsedDouyinHotItem:
    platform: str = "douyin"
    content_raw: str = ""
    content_type: str = "text"
    source_url: str = ""
    author_uid: str = ""
    author_username: str = ""
    group_id: str = ""
    collected_at: datetime = field(default_factory=datetime.utcnow)
    keyword: str = ""
    hot_value: int = 0
    video_count: int = 0
    label: int = 0
    metadata: dict = field(default_factory=dict)


class DouyinAPISpider:
    """抖音 AJAX API Spider — 热搜榜 + 关键词交叉匹配。

    使用方式:
        spider = DouyinAPISpider()
        hot = spider.get_hot_search()
        gray = spider.filter_gray_market(hot)
    """

    PLATFORM = "douyin"
    HOT_SEARCH_API = "https://www.douyin.com/aweme/v1/web/hot/search/list/"
    MIN_DELAY = 1.0
    MAX_DELAY = 3.0

    def __init__(self):
        self._session = requests.Session()
        self._cookies_loaded = False

    # ═══════════════════════════════════════════════════════════════════════════
    # Cookie
    # ═══════════════════════════════════════════════════════════════════════════

    def _load_cookies(self):
        if self._cookies_loaded:
            return
        cookies = BaseSpider.load_cookies("douyin")
        if cookies:
            for c in cookies:
                self._session.cookies.set(
                    c.get("name", ""), str(c.get("value", "")),
                    domain=c.get("domain", ""), path=c.get("path", "/"),
                )
            logger.info(f"已加载 {len(cookies)} 条抖音 Cookie")
        else:
            logger.warning("未找到抖音 Cookie，热搜 API 可能受限")
        self._cookies_loaded = True

    @property
    def headers(self) -> dict:
        return {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/131.0.0.0 Safari/537.36"
            ),
            "Referer": "https://www.douyin.com/",
            "Accept": "application/json, text/plain, */*",
        }

    # ═══════════════════════════════════════════════════════════════════════════
    # 热搜榜
    # ═══════════════════════════════════════════════════════════════════════════

    def get_hot_search(self) -> list[dict]:
        """获取抖音热搜榜。

        Returns:
            [{word, hot_value, group_id, video_count, label, sentence_tag, ...}, ...]
        """
        self._load_cookies()
        resp = self._session.get(
            f"{self.HOT_SEARCH_API}?detail_list=1",
            headers=self.headers, timeout=15,
        )
        if resp.status_code != 200:
            logger.error(f"热搜 API 失败: HTTP {resp.status_code}")
            return []
        data = resp.json()
        if data.get("status_code") != 0:
            logger.error(f"热搜 API status_code={data.get('status_code')}")
            return []

        word_list = data.get("data", {}).get("word_list", [])
        trending_list = data.get("data", {}).get("trending_list", [])
        logger.info(
            f"获取抖音热搜: {len(word_list)} 条热搜 + {len(trending_list)} 条上升热点"
        )
        return word_list + trending_list

    # ═══════════════════════════════════════════════════════════════════════════
    # 灰黑产关键词过滤
    # ═══════════════════════════════════════════════════════════════════════════

    def filter_gray_market(self, hot_items: list[dict]) -> list[ParsedDouyinHotItem]:
        """从热搜中过滤出灰黑产相关内容。

        逻辑: 热搜词与灰黑产关键词做子串匹配，匹配到则标记为疑似灰黑产。
        """
        results = []
        for item in hot_items:
            word = item.get("word", "")
            # 匹配风险关键词
            matched = []
            for kw in GRAY_KEYWORDS:
                if kw in word:
                    matched.append(kw)
            if matched:
                parsed = self._to_item(item, matched)
                results.append(parsed)
        logger.info(f"灰黑产过滤: {len(hot_items)} → {len(results)} 条疑似")
        return results

    def _to_item(self, raw: dict, matched_keywords: list[str]) -> ParsedDouyinHotItem:
        """将热搜条目转为 ParsedDouyinHotItem。"""
        word = raw.get("word", "")
        gid = str(raw.get("group_id", ""))
        hot_value = raw.get("hot_value", 0)
        video_count = raw.get("video_count", 0)
        label = raw.get("label", 0)
        sentence_tag = raw.get("sentence_tag", 0)

        source_url = f"https://www.douyin.com/search/{word}" if word else ""

        return ParsedDouyinHotItem(
            content_raw=f"【抖音热搜】{word}",
            content_type="text",
            source_url=source_url,
            group_id=gid,
            collected_at=datetime.utcnow(),
            keyword=word,
            hot_value=hot_value,
            video_count=video_count,
            label=label,
            metadata={
                "keyword": word,
                "group_id": gid,
                "hot_value": hot_value,
                "video_count": video_count,
                "label": label,
                "sentence_tag": sentence_tag,
                "matched_keywords": matched_keywords,
                "source": "douyin_hot_search",
                "fetch_method": "ajax_api",
            },
        )

    # ═══════════════════════════════════════════════════════════════════════════
    # 周期采集（生成 IntelItem 流）
    # ═══════════════════════════════════════════════════════════════════════════

    def collect_gray_items(self) -> list[ParsedDouyinHotItem]:
        """获取热搜并过滤灰黑产，一站式接口。"""
        hot = self.get_hot_search()
        if not hot:
            return []
        time.sleep(self.MIN_DELAY + random.random() * (self.MAX_DELAY - self.MIN_DELAY))
        return self.filter_gray_market(hot)
