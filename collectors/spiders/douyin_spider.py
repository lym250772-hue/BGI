"""
抖音关键词搜索 Spider — X-Bogus 签名 + 纯 HTTP API + DOM 兜底

核心策略:
  1. Playwright 提取 msToken + webid + Cookie
  2. execjs 调用 dy.js 生成 X-Bogus 签名
  3. 纯 HTTP requests 调用搜索 API (aweme/v1/web/general/search/single/)
  4. 兜底: Playwright 首页搜索框

反爬要点:
  - Playwright 提取 msToken/webid（浏览器自动刷新）
  - X-Bogus 签名（douyin 内部 JS 算法）
  - 完整浏览器参数模拟（device_platform/aid/channel 等）
  - 随机 UA + viewport

参考:
  - JargeWu/DouYin_Spider (GitHub)
  - CSDN: Selenium 抖音评论采集
"""

import time
import json
import re
import random
import execjs
import requests
from pathlib import Path
from datetime import datetime, timezone, timedelta
from dataclasses import dataclass, field
from urllib.parse import quote
from loguru import logger
from playwright.sync_api import sync_playwright

from collectors.base import now_bjt
from collectors.spiders.base_spider import BaseSpider


# ── X-Bogus 生成器（全局单例） ────────────────────────────────────────────────

_xbogus_js = None

def _get_xbogus_js():
    global _xbogus_js
    if _xbogus_js is None:
        js_path = Path(__file__).parent / "douyin_xbogus.js"
        with open(js_path, "r", encoding="gb18030") as f:
            _xbogus_js = execjs.compile(f.read())
    return _xbogus_js

def generate_xbogus(query_string: str) -> str:
    """生成抖音 X-Bogus 签名参数。"""
    return _get_xbogus_js().call("get_dy_xb", query_string)


# ── 解析结果结构 ──────────────────────────────────────────────────────────────

@dataclass
class ParsedDouyinItem:
    platform: str = "douyin"
    content_raw: str = ""
    content_type: str = "video"
    source_url: str = ""
    author_uid: str = ""
    author_username: str = ""
    aweme_id: str = ""
    collected_at: datetime = field(default_factory=datetime.utcnow)
    keyword: str = ""
    like_count: int = 0
    comment_count: int = 0
    share_count: int = 0
    play_count: int = 0
    duration: int = 0
    hashtags: list[str] = field(default_factory=list)
    video_cover_url: str = ""
    image_list: list[str] = field(default_factory=list)
    metadata: dict = field(default_factory=dict)


# ── Spider ─────────────────────────────────────────────────────────────────────

class DouyinSearchSpider(BaseSpider):
    """抖音搜索 Spider — X-Bogus 签名 + 纯 HTTP API。"""

    PLATFORM = "douyin"
    HOME_URL = "https://www.douyin.com"
    SEARCH_URL = "https://www.douyin.com/search"
    SEARCH_API = "https://www.douyin.com/aweme/v1/web/general/search/single/"
    PAGE_SIZE = 15
    MIN_DELAY = 2.0
    MAX_DELAY = 4.0
    MAX_RETRIES = 3
    BACKOFF_THRESHOLD = 4

    def __init__(self, headless: bool = True):
        super().__init__(headless)
        self._msToken = ""
        self._webid = ""

    # ═══════════════════════════════════════════════════════════════════════════
    # 反检测启动（覆盖 BaseSpider.start）
    # ═══════════════════════════════════════════════════════════════════════════

    def start(self):
        """启动浏览器 — 提取 msToken + webid，建立登录会话。"""
        self._playwright = sync_playwright().start()
        launch_kwargs = {
            "headless": self.headless,
            "args": [
                "--disable-blink-features=AutomationControlled",
                "--no-sandbox",
                "--disable-dev-shm-usage",
            ],
        }
        if hasattr(self, 'BROWSER_CHANNEL') and self.BROWSER_CHANNEL:
            launch_kwargs["channel"] = self.BROWSER_CHANNEL
        self._browser = self._playwright.chromium.launch(**launch_kwargs)

        ua = random.choice([
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36 Edg/120.0.0.0",
        ])
        self._context = self._browser.new_context(
            user_agent=ua,
            locale="zh-CN",
            viewport={"width": 1440, "height": 900},
        )
        self._page = self._context.new_page()
        self._page.add_init_script(
            "Object.defineProperty(navigator, 'webdriver', {get: () => false});"
        )
        self._inject_cookies()
        self._setup_request_interception()

        # 🆕 提取 msToken 和 webid
        self._extract_tokens()

        self._load_incremental_state()
        self._load_checkpoint()
        logger.info(f"{self.PLATFORM} Spider 已启动（登录态={'是' if self._logged_in else '否'}）")

    def _extract_tokens(self):
        """从浏览器 Cookie 和页面请求中提取 msToken 和 webid。"""
        # 拦截 API 请求提取 webid
        captured_webid = []

        def on_request(request):
            url = request.url
            if 'webid=' in url and 'douyin.com' in url:
                import re as _re
                m = _re.search(r'webid=(\d+)', url)
                if m:
                    captured_webid.append(m.group(1))

        self._page.on('request', on_request)

        # 导航到用户主页（触发 API 请求以提取 webid）
        try:
            self._page.goto(
                'https://www.douyin.com/user/MS4wLjABAAAAEpmH344CkCw2M58T33Q8TuFpdvJsOyaZcbWxAMc6H03wOVFf1Ow4mPP94TDUS4Us',
                wait_until='domcontentloaded', timeout=15000,
            )
            time.sleep(3)
        except Exception:
            logger.warning("token 提取页面加载超时")

        # 从 Cookie 提取 msToken
        page_cookies = self._context.cookies()
        for c in page_cookies:
            if c['name'] == 'msToken':
                self._msToken = c['value']
                logger.info(f"已提取 msToken: {self._msToken[:20]}...")

        if captured_webid:
            self._webid = captured_webid[0]
            logger.info(f"已提取 webid: {self._webid}")

        # 如果浏览器没拿到，尝试从保存的 tokens 文件加载
        if not self._msToken:
            token_file = Path("data/raw/douyin_tokens.json")
            if token_file.exists():
                try:
                    with open(token_file, encoding="utf-8") as f:
                        saved = json.load(f)
                    if saved.get("msToken"):
                        self._msToken = saved["msToken"]
                        logger.info(f"从 douyin_tokens.json 加载 msToken")
                    if not self._webid and saved.get("webid"):
                        self._webid = saved["webid"]
                except Exception:
                    pass

        # 如果还没有，尝试 localStorage
        if not self._msToken:
            try:
                ms = self._page.evaluate("() => localStorage.getItem('mxmsToken') || ''")
                if ms:
                    self._msToken = ms
                    logger.info(f"从 localStorage 提取 msToken")
            except Exception:
                pass

        # 如果仍然没有，记录警告
        if not self._msToken:
            logger.warning(
                "未获取到 msToken，搜索 API 可能被反垃圾拦截。"
                "请运行: python scripts/crawl/douyin_get_tokens.py"
            )

    # ═══════════════════════════════════════════════════════════════════════════
    # Cookie 注入
    # ═══════════════════════════════════════════════════════════════════════════

    def _inject_cookies(self):
        """注入抖音 Cookie。"""
        cookies = self.load_cookies(self.PLATFORM)
        if not cookies:
            logger.warning(
                f"未配置 {self.PLATFORM} Cookie"
                f"（环境变量 BGI_{self.PLATFORM.upper()}_COOKIES 或文件），搜索可能受限"
            )
            return

        try:
            clean = []
            for c in cookies:
                c_clean = {
                    "name": c.get("name", ""),
                    "value": str(c.get("value", "")),
                    "domain": c.get("domain", ""),
                    "path": c.get("path", "/"),
                }
                if not c_clean["name"] or not c_clean["domain"]:
                    continue
                for src, dst in [("httpOnly", "httpOnly"), ("secure", "secure")]:
                    if c.get(src):
                        c_clean[dst] = True
                ss = c.get("sameSite")
                if ss == "no_restriction":
                    c_clean["sameSite"] = "None"
                elif ss in ("Strict", "Lax", "None"):
                    c_clean["sameSite"] = ss
                if c.get("expirationDate"):
                    c_clean["expires"] = float(c["expirationDate"])
                clean.append(c_clean)
            self._context.add_cookies(clean)
            self._logged_in = True
            logger.info(f"已注入 {len(clean)} 条 {self.PLATFORM} Cookie")

            # JS 补充注入关键 Cookie
            key_names = {"s_v_web_id", "passport_csrf_token", "tt_webid", "ttwid",
                         "msToken", "odin_tt", "__ac_nonce", "__ac_signature"}
            js_parts = []
            for c in clean:
                if c["name"] in key_names:
                    js_parts.append(f"{c['name']}={c['value']}")
            if js_parts and self._page:
                js_cookie_str = "; ".join(js_parts)
                self._page.add_init_script(
                    f"document.cookie = '{js_cookie_str}; path=/; domain=.douyin.com';"
                )
        except Exception as exc:
            logger.warning(f"Cookie 注入失败 ({len(cookies)} cookies): {exc}")

    # ═══════════════════════════════════════════════════════════════════════════
    # 搜索入口
    # ═══════════════════════════════════════════════════════════════════════════

    def search_and_parse(
        self, keyword: str, max_pages: int = 3, **kwargs
    ) -> list[ParsedDouyinItem]:
        if not self._page:
            raise RuntimeError("Spider 未启动，请先调用 start()")

        max_items = kwargs.get("max_items", 0)
        use_incremental = kwargs.get("incremental", False)
        start_page = kwargs.get("start_page", 1)
        checkpoint_cb = kwargs.get("checkpoint_callback")
        all_items = []
        consecutive_empty = 0

        for page_num in range(start_page, max_pages + 1):
            logger.info(f"搜索 [{keyword}] 第{page_num}/{max_pages}页")
            try:
                items = self._call_search_api(keyword, page_num)

                new_count = 0
                for item in items:
                    if use_incremental and self._should_skip(keyword, item.collected_at):
                        continue
                    all_items.append(item)
                    new_count += 1
                    self._update_last_collected(keyword, item.collected_at or now_bjt())
                    if max_items and len(all_items) >= max_items:
                        break

                logger.info(f"  第{page_num}页: {len(items)} 条, 新增 {new_count} 条")

                if not items:
                    consecutive_empty += 1
                    if consecutive_empty >= self.BACKOFF_THRESHOLD:
                        break
                else:
                    consecutive_empty = 0

                if max_items and len(all_items) >= max_items:
                    break

            except Exception as exc:
                logger.error(f"  第{page_num}页失败: {exc}")
                self.stats["errors"] += 1
                time.sleep(random.uniform(3.0, 6.0))
                continue

            if checkpoint_cb:
                checkpoint_cb(keyword, page_num, len(all_items))

            self._adaptive_delay(consecutive_empty)

        logger.info(
            f"[{keyword}] 完成: {len(all_items)} 条 "
            f"({self.stats['pages_loaded']} pages, {self.stats['retries']} retries, {self.stats['errors']} errors)"
        )
        return all_items


    # ═══════════════════════════════════════════════════════════════════════════
    # 页面内 API 调用
    # ═══════════════════════════════════════════════════════════════════════════

    def _call_search_api(self, keyword: str, page: int = 1) -> list[ParsedDouyinItem]:
        """搜索 API — Playwright fetch + X-Bogus（保持浏览器指纹一致）。"""
        offset = (page - 1) * 10

        # 构建请求参数
        params = [
            ("device_platform", "webapp"), ("aid", "6383"), ("channel", "channel_pc_web"),
            ("search_channel", "aweme_general"), ("sort_type", "0"), ("publish_time", "0"),
            ("keyword", keyword), ("search_source", "normal_search"),
            ("query_correct_type", "1"), ("is_filter_search", "0"), ("from_group_id", ""),
            ("offset", str(offset)), ("count", "15"),
            ("pc_client_type", "1"), ("version_code", "190600"), ("version_name", "19.6.0"),
            ("cookie_enabled", "true"),
        ]
        if self._msToken:
            params.append(("msToken", self._msToken))
        if self._webid:
            params.append(("webid", self._webid))

        query_string = "&".join(f"{k}={v}" for k, v in params)
        try:
            query_string += f"&X-Bogus={generate_xbogus(query_string)}"
        except Exception as e:
            logger.warning(f"X-Bogus 生成失败: {e}")
            return []

        # 🆕 在浏览器内用 fetch 调用（TLS 指纹一致 + Cookie 自动携带）
        js_code = f"""
        async () => {{
            try {{
                const url = 'https://www.douyin.com/aweme/v1/web/general/search/single/?{query_string}';
                const resp = await fetch(url, {{
                    method: 'GET', credentials: 'include',
                    headers: {{ 'Accept': 'application/json', 'Referer': 'https://www.douyin.com/' }}
                }});
                if (!resp.ok) return {{ error: true, status: resp.status }};
                return await resp.json();
            }} catch(e) {{ return {{ error: true, message: e.message }}; }}
        }}
        """
        result = self._page.evaluate(js_code)
        self.stats["pages_loaded"] += 1
        time.sleep(random.uniform(self.MIN_DELAY, self.MAX_DELAY))

        if not result or result.get("error"):
            return []

        items_data = result.get("data", [])
        if not isinstance(items_data, list):
            items_data = []

        items = []
        for item_data in items_data:
            if item_data.get("type") != 1:
                continue
            aweme = item_data.get("aweme_info", item_data)
            parsed = self._parse_aweme(aweme, keyword)
            if parsed:
                items.append(parsed)
        return items

    # ═══════════════════════════════════════════════════════════════════════════

    def _parse_aweme(self, aweme: dict, keyword: str) -> ParsedDouyinItem | None:
        """解析单个 aweme/video 对象。"""
        aweme_id = str(aweme.get("aweme_id", "") or aweme.get("awemeId", ""))
        if not aweme_id:
            return None

        # 描述文本（最重要的灰黑产线索来源）
        desc = aweme.get("desc", "") or aweme.get("description", "")

        # 作者
        author = aweme.get("author", {}) or {}
        author_name = author.get("nickname", "") or author.get("short_id", "")
        author_uid = str(author.get("uid", "") or author.get("id", ""))

        # 互动统计
        statistics = aweme.get("statistics", {}) or {}

        # 视频信息
        video = aweme.get("video", {}) or {}
        duration = video.get("duration", 0) or 0

        # 封面
        cover = video.get("cover", {}) or {}
        cover_url = ""
        for key in ("url_list", "url"):
            urls = cover.get(key, [])
            if isinstance(urls, list) and urls:
                cover_url = urls[0]
                break
            elif isinstance(urls, str):
                cover_url = urls
                break

        # 话题标签
        hashtags = []
        for tag in aweme.get("text_extra", []) or []:
            tag_name = tag.get("hashtag_name", "") or tag.get("hashtagName", "")
            if tag_name:
                hashtags.append(tag_name)
        # 也尝试从 cha_list 提取
        for cha in aweme.get("cha_list", []) or []:
            cha_name = cha.get("cha_name", "") or cha.get("chaName", "")
            if cha_name and cha_name not in hashtags:
                hashtags.append(cha_name)

        # 图片集（图集类型）
        images = aweme.get("images", []) or aweme.get("image_infos", []) or []
        image_urls = []
        if images:
            for img in images:
                if isinstance(img, dict):
                    urls = img.get("url_list", []) or img.get("urlList", [])
                    if urls and isinstance(urls, list):
                        image_urls.append(urls[0])
                    elif isinstance(urls, str):
                        image_urls.append(urls)

        # 内容类型
        content_type = "video"
        if image_urls:
            content_type = "image"
        elif aweme.get("media_type", 0) == 4:
            content_type = "image"

        # 构建 content_raw
        content_parts = []
        if desc:
            content_parts.append(f"【描述】{desc}")
        if hashtags:
            content_parts.append(f"【话题】{' '.join('#' + h for h in hashtags)}")
        if content_type == "image":
            content_parts.append("【类型】图集")
        if duration:
            content_parts.append(f"【时长】{duration}秒")
        if not content_parts:
            content_parts.append("【无文本内容】")

        # 时间
        create_time = aweme.get("create_time", 0) or aweme.get("createTime", 0)

        item = ParsedDouyinItem(
            content_raw="\n".join(content_parts),
            content_type=content_type,
            source_url=f"https://www.douyin.com/video/{aweme_id}",
            author_uid=author_uid,
            author_username=author_name,
            aweme_id=aweme_id,
            collected_at=self.ts_to_datetime(create_time) if create_time else now_bjt(),
            keyword=keyword,
            like_count=int(statistics.get("digg_count", 0) or statistics.get("diggCount", 0)),
            comment_count=int(statistics.get("comment_count", 0) or statistics.get("commentCount", 0)),
            share_count=int(statistics.get("share_count", 0) or statistics.get("shareCount", 0)),
            play_count=int(statistics.get("play_count", 0) or statistics.get("playCount", 0)),
            duration=duration,
            hashtags=hashtags,
            video_cover_url=cover_url,
            image_list=image_urls,
            metadata={
                "keyword": keyword,
                "aweme_id": aweme_id,
                "hashtags": hashtags,
                "image_list": image_urls,
                "has_image": bool(image_urls),
                "has_video": content_type == "video",
                "has_emoji": self.contains_emoji(desc),
                "like_count": int(statistics.get("digg_count", 0) or statistics.get("diggCount", 0)),
                "comment_count": int(statistics.get("comment_count", 0) or statistics.get("commentCount", 0)),
                "share_count": int(statistics.get("share_count", 0) or statistics.get("shareCount", 0)),
                "play_count": int(statistics.get("play_count", 0) or statistics.get("playCount", 0)),
                "duration": duration,
                "video_cover_url": cover_url,
                "parse_method": "api",
            },
        )
        return item

    # ═══════════════════════════════════════════════════════════════════════════
    # DOM 解析（兜底方案）
    # ═══════════════════════════════════════════════════════════════════════════

    def _parse_dom_results(
        self, html: str, keyword: str
    ) -> list[ParsedDouyinItem]:
        """从 HTML 中解析抖音搜索结果。"""
        items = []
        seen_ids = set()

        # 尝试从 __INITIAL_STATE__ 或 RENDER_DATA 中提取（SSR 数据）
        ssr_patterns = [
            r'window\.__INITIAL_STATE__\s*=\s*({.*?});\s*</script>',
            r'<script[^>]*id="RENDER_DATA"[^>]*>(.*?)</script>',
            r'window\._SSR_HYDRATED_DATA\s*=\s*({.*?});\s*</script>',
        ]

        for pattern in ssr_patterns:
            ssr_m = re.search(pattern, html, re.DOTALL)
            if ssr_m:
                try:
                    raw_json = ssr_m.group(1)
                    # RENDER_DATA 可能是 URL-encoded
                    if raw_json.startswith("%"):
                        from urllib.parse import unquote
                        raw_json = unquote(raw_json)
                    ssr_data = json.loads(raw_json)
                    # 递归搜索 aweme 列表
                    aweme_list = self._find_aweme_list(ssr_data)
                    for aweme in aweme_list:
                        aweme_id = str(aweme.get("aweme_id", "") or aweme.get("awemeId", ""))
                        if not aweme_id or aweme_id in seen_ids:
                            continue
                        seen_ids.add(aweme_id)
                        item = self._parse_aweme(aweme, keyword)
                        if item:
                            items.append(item)
                    if items:
                        break
                except (json.JSONDecodeError, Exception):
                    continue

        # 纯 DOM 卡片解析（无 SSR 数据时）
        if not items:
            card_pattern = r'<li[^>]*class="[^"]*search-item[^"]*"[^>]*>(.*?)</li>'
            for card_m in re.finditer(card_pattern, html, re.DOTALL):
                card = card_m.group(1)

                # 视频 ID
                video_id = ""
                vid_m = re.search(r'data-video-id="(\d+)"', card)
                if vid_m:
                    video_id = vid_m.group(1)
                else:
                    vid_m = re.search(r'/video/(\d+)', card)
                    if vid_m:
                        video_id = vid_m.group(1)
                if not video_id or video_id in seen_ids:
                    continue
                seen_ids.add(video_id)

                # 描述
                desc = ""
                desc_m = re.search(r'class="[^"]*desc[^"]*"[^>]*>([^<]+)', card)
                if desc_m:
                    desc = desc_m.group(1).strip()

                # 作者
                author_name = ""
                author_m = re.search(r'class="[^"]*author[^"]*"[^>]*>.*?<span[^>]*>([^<]+)', card, re.DOTALL)
                if author_m:
                    author_name = author_m.group(1).strip()

                content_parts = []
                if desc:
                    content_parts.append(f"【描述】{self.clean_html(desc)}")
                if not content_parts:
                    content_parts.append("【无文本内容】")

                item = ParsedDouyinItem(
                    content_raw="\n".join(content_parts),
                    source_url=f"https://www.douyin.com/video/{video_id}",
                    author_username=author_name,
                    aweme_id=video_id,
                    collected_at=now_bjt(),
                    keyword=keyword,
                    metadata={
                        "keyword": keyword,
                        "aweme_id": video_id,
                        "has_emoji": self.contains_emoji(desc),
                        "parse_method": "dom",
                    },
                )
                items.append(item)

        return items

    @staticmethod
    def _find_aweme_list(obj, max_depth=6):
        """递归搜索 SSR 数据中的 aweme 列表。"""
        if max_depth <= 0:
            return []
        if isinstance(obj, list):
            # 检查是否像 aweme 列表
            if obj and isinstance(obj[0], dict) and "aweme_id" in obj[0]:
                return obj
            results = []
            for item in obj:
                results.extend(DouyinSearchSpider._find_aweme_list(item, max_depth - 1))
            return results
        elif isinstance(obj, dict):
            # 直接查找 aweme_list / data 等关键字段
            for key in ("aweme_list", "data", "search_result", "user_list"):
                if key in obj and isinstance(obj[key], list):
                    result = DouyinSearchSpider._find_aweme_list(obj[key], max_depth - 1)
                    if result:
                        return result
            # 递归进入
            results = []
            for v in obj.values():
                results.extend(DouyinSearchSpider._find_aweme_list(v, max_depth - 1))
            return results
        return []

    # ═══════════════════════════════════════════════════════════════════════════
    # 工具方法
    # ═══════════════════════════════════════════════════════════════════════════

    def _build_search_url(self, keyword: str) -> str:
        """构建搜索 URL。"""
        encoded = quote(keyword)
        return f"{self.SEARCH_URL}/{encoded}"

    def _is_blocked(self) -> bool:
        """检查是否触发反爬。"""
        if not self._page:
            return False
        try:
            title = self._page.title()
            blocked_signals = ["验证", "登录", "滑块", "验证码", "captcha", "verify",
                               "访问被拒绝", "请完成安全验证"]
            if any(kw in title for kw in blocked_signals):
                return True
            url = self._page.url
            if "verify" in url.lower() or "captcha" in url.lower() or "login" in url.lower():
                return True
            return False
        except Exception:
            return False
