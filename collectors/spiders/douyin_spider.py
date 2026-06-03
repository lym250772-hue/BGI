"""
抖音关键词搜索 Spider（Playwright + API 拦截 + DOM 兜底）

核心策略:
  1. 优先拦截 XHR 搜索 API 获取结构化 JSON（/aweme/v1/web/search/item/）
  2. 兜底 DOM 解析搜索结果卡片
  3. Playwright stealth + Cookie 注入

反爬要点:
  - Cookie 注入（s_v_web_id / passport_csrf_token / tt_webid 等）
  - 首页预热 + 搜索入口渐进式访问
  - 随机 UA + viewport
  - 较长请求间隔（抖音反爬极强）

抖音搜索机制:
  - Web 搜索页: https://www.douyin.com/search/{keyword}
  - 搜索 API: GET /aweme/v1/web/search/item/?keyword=...&search_id=...
  - 新版 Web API: /aweme/v1/web/general/search/single/?
  - 需要 msToken / X-Bogus / _signature 等签名参数
  - 浏览器内自动携带签名，无需逆向

灰黑产数据采集关注点:
  - 视频描述中的引流话术（加微信/QQ、免费领取、兼职等）
  - 评论区违规内容（需单独采集）
  - 账号主页信息（简介含联系方式）
  - 话题标签（#刷单 #兼职 #日赚 等）
"""

import time
import json
import re
import random
from datetime import datetime
from dataclasses import dataclass, field
from urllib.parse import quote
from loguru import logger
from playwright.sync_api import sync_playwright

from collectors.spiders.base_spider import BaseSpider, random_ua


# ── 解析结果结构 ──────────────────────────────────────────────────────────────

@dataclass
class ParsedDouyinItem:
    """抖音搜索结果条目（视频/Aweme）。"""
    platform: str = "douyin"
    content_raw: str = ""
    content_type: str = "video"
    source_url: str = ""
    author_uid: str = ""
    author_username: str = ""
    aweme_id: str = ""            # 视频 ID
    collected_at: datetime = field(default_factory=datetime.utcnow)
    keyword: str = ""
    like_count: int = 0
    comment_count: int = 0
    share_count: int = 0
    play_count: int = 0
    duration: int = 0             # 视频时长（秒）
    hashtags: list[str] = field(default_factory=list)
    video_cover_url: str = ""
    image_list: list[str] = field(default_factory=list)  # 图集图片 URL
    metadata: dict = field(default_factory=dict)


# ── Spider ─────────────────────────────────────────────────────────────────────

class DouyinSearchSpider(BaseSpider):
    """抖音搜索 Spider — API 拦截 + DOM 兜底。"""

    PLATFORM = "douyin"
    HOME_URL = "https://www.douyin.com"
    SEARCH_URL = "https://www.douyin.com/search"
    BROWSER_CHANNEL = "msedge"  # 用系统 Edge 绕过验证码
    # 搜索 API (新版 2024+)
    SEARCH_API = "/aweme/v1/web/search/item/"
    GENERAL_SEARCH_API = "/aweme/v1/web/general/search/single/"
    PAGE_SIZE = 15
    MIN_DELAY = 3.0
    MAX_DELAY = 6.0
    MAX_RETRIES = 3
    BACKOFF_THRESHOLD = 4

    def __init__(self, headless: bool = True):
        super().__init__(headless)
        self._api_responses: list[dict] = []
        self._api_capture_enabled = False
        self._search_id = ""  # 抖音搜索 ID（翻页需要）

    # ═══════════════════════════════════════════════════════════════════════════
    # 反检测启动（覆盖 BaseSpider.start）
    # ═══════════════════════════════════════════════════════════════════════════

    def start(self):
        """启动浏览器 — 抖音专用反检测：incognito + 隐藏 webdriver + 随机 UA。"""
        self._playwright = sync_playwright().start()
        launch_kwargs = {
            "headless": self.headless,
            "args": [
                "--disable-blink-features=AutomationControlled",
                "--no-sandbox",
                "--disable-dev-shm-usage",
                "--incognito",
            ],
        }
        if self.BROWSER_CHANNEL:
            launch_kwargs["channel"] = self.BROWSER_CHANNEL
        self._browser = self._playwright.chromium.launch(**launch_kwargs)

        # 随机 UA（Mac/Windows 交替降低指纹一致性）
        ua = random.choice([
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36 Edg/131.0.0.0",
        ])
        self._context = self._browser.new_context(
            user_agent=ua,
            locale="zh-CN",
            viewport={"width": 1440, "height": 900},
        )

        # 隐藏 webdriver 标记
        self._page = self._context.new_page()
        self._page.add_init_script(
            "Object.defineProperty(navigator, 'webdriver', {get: () => false});"
        )

        # 注入 Cookie
        self._inject_cookies()

        # 预热：访问首页
        try:
            self._page.goto(self.HOME_URL, wait_until="domcontentloaded", timeout=15000)
            time.sleep(2)
        except Exception:
            logger.warning("预热超时，将在搜索时重试")

        # 加载增量 + 断点状态
        self._load_incremental_state()
        self._load_checkpoint()

        logger.info(
            f"{self.PLATFORM} Spider 已启动"
            f"（登录态={'是' if self._logged_in else '否'}）"
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
    # API 拦截
    # ═══════════════════════════════════════════════════════════════════════════

    def _setup_request_interception(self):
        """拦截搜索 API 响应。"""
        if not self._page:
            return

        def _on_response(response):
            if not self._api_capture_enabled:
                return
            url = response.url
            if self.SEARCH_API in url or self.GENERAL_SEARCH_API in url:
                try:
                    body = response.json()
                    if body and body.get("status_code", -1) == 0:
                        self._api_responses.append(body)
                        data_block = body.get("data", {}) or body.get("aweme_list", [])
                        count = len(data_block) if isinstance(data_block, list) else len(data_block.get("data", []))
                        logger.debug(f"  拦截到搜索 API 响应: {count} 条")
                except Exception:
                    pass

        self._page.on("response", _on_response)

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
        self._search_id = ""  # 重置 search_id（每个关键词独立）

        # 🆕 优先使用 API 直调（page.evaluate fetch），失败后回退首页搜索框
        for page_num in range(start_page, max_pages + 1):
            logger.info(f"搜索 [{keyword}] 第{page_num}/{max_pages}页")

            try:
                # 方式1: API 直调（快速、可靠）
                items = self._call_search_api(keyword, page_num)
                if items:
                    logger.debug(f"  API 直调获取 {len(items)} 条")
                else:
                    # 方式2: 回退到首页搜索框 + body 正则（仅第1页）
                    if page_num == 1:
                        logger.debug("  API 无数据，回退首页搜索框方案")
                        items = self._search_via_homepage(keyword)
                    else:
                        logger.debug("  API 无数据且非首页，跳过")
                        break

                new_count = 0
                for item in items:
                    if use_incremental and self._should_skip(keyword, item.collected_at):
                        continue
                    all_items.append(item)
                    new_count += 1
                    self._update_last_collected(keyword, item.collected_at or datetime.utcnow())
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
                    logger.info(f"  已达到 max_items={max_items}")
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
    # 首页搜索框 → 搜索结果页 DOM 提取
    # ═══════════════════════════════════════════════════════════════════════════

    def _search_via_homepage(self, keyword: str) -> list[ParsedDouyinItem]:
        """从首页通过搜索框触发搜索，绕过直接/search/ URL 的验证码。

        关键：必须用 Playwright 原生键盘操作（click + type + Enter），
        JS dispatchEvent 无法触发 React/Vue 的导航。
        """
        # 步骤1: 确保在首页（无验证码）
        need_reload = True
        if "douyin.com" in self._page.url and "验证" not in self._page.title():
            if self._page.url.rstrip("/").endswith("douyin.com") or "/jingxuan" in self._page.url:
                need_reload = False
        if need_reload:
            self._page.goto(self.HOME_URL, wait_until="domcontentloaded", timeout=15000)
            time.sleep(2.0 + random.random())
            # 如果还是验证码，等一会再试
            if "验证" in self._page.title():
                logger.warning("  首页验证码，等待后重试...")
                time.sleep(5.0)
                self._page.goto(self.HOME_URL, wait_until="domcontentloaded", timeout=15000)
                time.sleep(2.0)

        # 步骤2: 移除遮罩 + 关闭信任登录弹窗
        self._page.evaluate('''
        () => {
            // 关闭 trust-logout-dialog
            const trustDialog = document.querySelector('#trust-logout-dialog');
            if (trustDialog) trustDialog.remove();
            // 移除各类遮罩
            document.querySelectorAll('[class*="mask"], [class*="overlay"], [class*="dialog"], [class*="modal"]')
                .forEach(m => m.remove());
        }
        ''')
        time.sleep(1.0)

        # 步骤3: Playwright 原生键盘操作 — 点搜索框 → 输入 → Enter
        self._page.mouse.click(500, 300)
        time.sleep(0.5)

        # 点击搜索框（用 JS 直接 focus 避免被遮罩挡住）
        try:
            self._page.locator('input[placeholder*="搜索"]').first.click(timeout=5000)
        except Exception:
            try:
                self._page.evaluate('() => { const inp = document.querySelector("input[placeholder*=\\"搜索\\"]"); if (inp) inp.focus(); }')
            except Exception:
                self._page.mouse.click(700, 30)
            time.sleep(0.5)

        # 输入 + 回车
        self._page.keyboard.type(keyword, delay=100)
        time.sleep(0.3 + random.random() * 0.3)
        self._page.keyboard.press('Enter')

        # 步骤4: 等待搜索结果加载
        time.sleep(4.0 + random.random() * 2.0)

        # 如果没跳转，手动导航（带 referer）
        if "search" not in self._page.url:
            from urllib.parse import quote
            self._page.goto(
                f"https://www.douyin.com/search/{quote(keyword)}?type=general",
                wait_until="domcontentloaded", timeout=15000,
                referer="https://www.douyin.com/",
            )

        # 等待 body 内容渲染
        for _ in range(15):
            body_len = self._page.evaluate("() => document.body.innerText.length")
            if body_len > 200:
                break
            time.sleep(0.5)

        return self._parse_search_page_dom(keyword)

    def _parse_search_page_dom(self, keyword: str) -> list[ParsedDouyinItem]:
        """从当前搜索页提取视频/图集卡片。

        方案1（优先）: 正则解析 body.innerText — 抖音搜索结果通过 JS 渲染，
        文本内容在 body 中完整可见，包含 时长+点赞+描述+作者+日期 的固定模式。
        方案2（兜底）: DOM 选择器提取 a[href*="/video/"]。
        """
        # 方案1: 正则文本提取
        items = self._parse_from_body_text(keyword)
        if items:
            return items

        # 方案2: DOM 链接提取
        return self._parse_from_video_links(keyword)

    def _parse_from_body_text(self, keyword: str) -> list[ParsedDouyinItem]:
        """从 body.innerText 正则提取搜索结果。

        body 中的搜索结果格式:
            时长\n点赞\n描述\n@作者\n· 日期
        """
        body_text = self._page.evaluate("() => document.body.innerText")
        if len(body_text) < 200:
            return []

        import re
        # 匹配: 时长 + 点赞 + 描述 + @作者 + 日期
        pattern = re.compile(
            r'(\d{2}:\d{2})\s*\n\s*([\d.]+[亿万]?)\s*\n\s*(.+?)\s*\n\s*@(.+?)\s*\n\s*·\s*(.+?)(?=\n\d{2}:\d{2}|\n相关搜索|\n\s*$)',
            re.DOTALL,
        )
        matches = pattern.findall(body_text)

        items = []
        for duration, likes, desc, author, date_str in matches:
            desc = desc.replace('\n', ' ').strip()
            author = author.strip()
            date_str = date_str.strip()

            if len(desc) < 4:
                continue

            # 解析点赞数
            like_count = self._parse_count(likes)

            content_parts = [f"【描述】{desc}"]
            if author:
                content_parts.append(f"【作者】{author}")
            content_parts.append(f"【时长】{duration}")
            content_parts.append(f"【点赞】{likes}")
            content_parts.append(f"【日期】{date_str}")

            item = ParsedDouyinItem(
                content_raw="\n".join(content_parts),
                content_type="video",
                source_url=f"https://www.douyin.com/search/{keyword}",
                author_username=author,
                aweme_id="",  # 搜索结果页没有暴露 aweme_id
                collected_at=datetime.utcnow(),
                keyword=keyword,
                like_count=like_count,
                duration=self._parse_duration(duration),
                metadata={
                    "keyword": keyword,
                    "has_emoji": self.contains_emoji(desc),
                    "like_count": like_count,
                    "duration": duration,
                    "date": date_str,
                    "parse_method": "body_text_regex",
                },
            )
            items.append(item)

        return items

    def _parse_from_video_links(self, keyword: str) -> list[ParsedDouyinItem]:
        """从 DOM a[href*=\"/video/\"] 提取搜索结果（兜底方案）。"""
        items = []
        seen_ids = set()

        raw_results = self._page.evaluate("""() => {
            var results = [];
            var seen = {};
            document.querySelectorAll('a').forEach(function(a) {
                var href = a.href;
                var idx = href.indexOf('/video/');
                if (idx === -1) return;
                var vid = href.substring(idx + 7).split('?')[0];
                if (!vid || seen[vid]) return;
                seen[vid] = true;
                var c = a.closest('div');
                if (c) c = c.parentElement;
                var text = (c ? c.innerText : a.innerText) || '';
                text = text.trim();
                if (text.length > 15) {
                    results.push({vid: vid, text: text.substring(0, 200)});
                }
            });
            return results;
        }""")

        for r in raw_results:
            vid = r.get("vid", "")
            title = r.get("text", "")
            if not vid or vid in seen_ids or len(title) < 3:
                continue
            seen_ids.add(vid)

            item = ParsedDouyinItem(
                content_raw=f"【描述】{title}",
                content_type="video",
                source_url=f"https://www.douyin.com/video/{vid}",
                aweme_id=vid,
                collected_at=datetime.utcnow(),
                keyword=keyword,
                metadata={
                    "keyword": keyword,
                    "aweme_id": vid,
                    "parse_method": "video_links_dom",
                },
            )
            items.append(item)

        return items

    @staticmethod
    def _parse_count(count_str: str) -> int:
        """解析点赞数: '4965' -> 4965, '4.1万' -> 41000, '10.1万' -> 101000"""
        count_str = count_str.strip()
        if '万' in count_str:
            try:
                return int(float(count_str.replace('万', '')) * 10000)
            except ValueError:
                return 0
        elif '亿' in count_str:
            try:
                return int(float(count_str.replace('亿', '')) * 100000000)
            except ValueError:
                return 0
        else:
            try:
                return int(count_str)
            except ValueError:
                return 0

    @staticmethod
    def _parse_duration(duration_str: str) -> int:
        """解析时长: '01:48' -> 108, '10:04' -> 604"""
        parts = duration_str.strip().split(':')
        if len(parts) == 2:
            try:
                return int(parts[0]) * 60 + int(parts[1])
            except ValueError:
                return 0
        return 0

    def _scroll_for_more(self, keyword: str) -> list[ParsedDouyinItem]:
        """滚动加载更多搜索结果（后续页）。"""
        self._page.evaluate("() => window.scrollTo(0, document.body.scrollHeight)")
        time.sleep(2.0 + random.random() * 2.0)
        return self._parse_search_page_dom(keyword)

    # ═══════════════════════════════════════════════════════════════════════════
    # 页面内 API 调用
    # ═══════════════════════════════════════════════════════════════════════════

    def _call_search_api(self, keyword: str, page: int = 1) -> list[ParsedDouyinItem]:
        """在浏览器内通过 page.evaluate(fetch) 调用抖音搜索 API。"""
        from urllib.parse import quote
        encoded = quote(keyword)
        offset = (page - 1) * self.PAGE_SIZE

        # 首次获取 search_id（使用绝对 URL，兼容从 creator.douyin.com 发起）
        if not self._search_id:
            js_get_sid = (
                "async () => {"
                "  try {"
                f"    const resp = await fetch('https://www.douyin.com/aweme/v1/web/general/search/single/?"
                f"keyword={encoded}&offset=0&count=1&search_source=normal_search',"
                "      { method: 'GET', credentials: 'include',"
                "        headers: { 'Accept': 'application/json' } });"
                "    const json = await resp.json();"
                "    return json?.data?.search_id || json?.log_pb?.impr_id || '';"
                "  } catch(e) { return ''; }"
                "}"
            )
            try:
                sid = self._page.evaluate(js_get_sid)
                if sid:
                    self._search_id = str(sid)
                    logger.debug(f"  获取 search_id: {self._search_id}")
            except Exception:
                pass
            time.sleep(1.0 + random.random())

        # 正式搜索 — 使用绝对 URL（兼容从 creator.douyin.com 发起）
        search_id_param = f"&search_id={self._search_id}" if self._search_id else ""
        js_code = (
            "async () => {"
            "  try {"
            f"    const url = 'https://www.douyin.com/aweme/v1/web/search/item/?keyword={encoded}"
            f"&offset={offset}&count={self.PAGE_SIZE}&search_source=normal_search{search_id_param}';"
            "    const resp = await fetch(url,"
            "      { method: 'GET', credentials: 'include',"
            "        headers: { 'Accept': 'application/json', 'Referer': 'https://www.douyin.com/' } });"
            "    if (!resp.ok) return { error: true, status: resp.status };"
            "    const json = await resp.json();"
            "    return json;"
            "  } catch(e) { return { error: true, message: e.message }; }"
            "}"
        )
        result = self._page.evaluate(js_code)
        self.stats["pages_loaded"] += 1
        time.sleep(1.5 + random.random() * 2.0)  # API 频率控制

        if not result or result.get("error"):
            status = result.get("status", "?") if result else "null"
            msg = result.get("message", "") if result else ""
            logger.warning(f"  搜索 API 异常 (status={status}, msg={msg})")
            return []

        # 解析响应（数据在 aweme_list 字段，新版 API 不再用 data 包装）
        # 兼容多种响应格式: aweme_list / data / data.data
        aweme_list = (result.get("aweme_list") or result.get("data") or [])
        if isinstance(aweme_list, dict):
            aweme_list = aweme_list.get("data") or aweme_list.get("aweme_list") or []
        if not isinstance(aweme_list, list):
            aweme_list = []

        items = []
        for raw in aweme_list:
            aweme = raw.get("aweme_info", raw)
            item = self._parse_aweme(aweme, keyword)
            if item:
                items.append(item)

        return items

    # ═══════════════════════════════════════════════════════════════════════════
    # API 响应解析
    # ═══════════════════════════════════════════════════════════════════════════

    def _parse_api_responses(
        self, responses: list[dict], keyword: str
    ) -> list[ParsedDouyinItem]:
        """解析拦截到的 API 响应。"""
        items = []
        seen_ids = set()

        for resp in responses:
            data_block = resp.get("data", [])
            if isinstance(data_block, dict):
                data_list = data_block.get("data", [])
            elif isinstance(data_block, list):
                data_list = data_block
            else:
                continue

            for raw in data_list:
                aweme = raw.get("aweme_info", raw)
                aweme_id = str(aweme.get("aweme_id", "") or aweme.get("awemeId", ""))
                if not aweme_id or aweme_id in seen_ids:
                    continue
                seen_ids.add(aweme_id)

                item = self._parse_aweme(aweme, keyword)
                if item:
                    items.append(item)

        return items

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
            collected_at=self.ts_to_datetime(create_time) if create_time else datetime.utcnow(),
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
                    collected_at=datetime.utcnow(),
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
