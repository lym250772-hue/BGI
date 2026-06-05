"""
闲鱼搜索采集 Spider — v3 持久化浏览器模式。

闲鱼 (goofish.com) 是阿里巴巴旗下二手交易平台，灰产活动活跃
（账号交易、刷单服务、代实名、解封等）。

技术方案:
  - v3 持久化浏览器 (launch_persistent_context + Edge 内核)
  - SSR 数据提取 (__INITIAL_STATE__) + DOM 解析兜底
  - 强反爬对抗: 非headless + 高斯延迟5-16s + 贝塞尔鼠标 + 拟人滚动
  - 无限滚动分页（非页码翻页）

反爬关键:
  - 阿里系安全机制极严，必须使用非headless + 真实指纹
  - 每日限量 20-30 条 / session
  - 首次需手动扫码登录，之后复用 persistent profile
"""

import os
import time
import json
import re
import random
from dataclasses import dataclass, field
from datetime import datetime
from loguru import logger
from playwright.sync_api import sync_playwright

from config.settings import settings
from collectors.spiders.base_spider import BaseSpider


# ═══════════════════════════════════════════════════════════════════════════════
# ParsedXianyuItem
# ═══════════════════════════════════════════════════════════════════════════════

@dataclass
class ParsedXianyuItem:
    """闲鱼搜索结果解析条目。"""
    platform: str = "xianyu"
    content_raw: str = ""           # title + description
    content_type: str = "text"
    source_url: str = ""            # https://www.goofish.com/item?id=xxx
    author_uid: str = ""            # seller ID
    author_username: str = ""       # seller nickname
    item_id: str = ""               # listing/item ID
    collected_at: datetime = field(default_factory=datetime.utcnow)
    keyword: str = ""
    price: float = 0.0              # CNY
    location: str = ""              # seller IP location
    seller_rating: str = ""         # 芝麻信用等级
    listing_status: str = "active"  # active / sold
    like_count: int = 0
    comment_count: int = 0          # 留言数
    image_list: list[str] = field(default_factory=list)
    metadata: dict = field(default_factory=dict)


# ═══════════════════════════════════════════════════════════════════════════════
# 搜索关键词（灰产相关）
# ═══════════════════════════════════════════════════════════════════════════════

GREY_MARKET_KEYWORDS = [
    "账号交易", "刷单", "接码", "代实名", "解封",
    "涨粉", "流量推广", "抖音粉丝", "小红书推广",
    "投票", "刷量", "数据维护", "账号注册",
    "代认证", "企业认证", "蓝V认证",
    "微信多开", "协议号", "白号",
]


# ═══════════════════════════════════════════════════════════════════════════════
# XianyuSearchSpider
# ═══════════════════════════════════════════════════════════════════════════════

class XianyuSearchSpider(BaseSpider):
    """闲鱼搜索 Spider（v3 持久化浏览器）。

    使用 launch_persistent_context 保持登录态，
    通过 SSR 数据 + DOM 提取搜索结果。
    """

    PLATFORM = "xianyu"
    HOME_URL = "https://www.goofish.com"
    SEARCH_URL = "https://www.goofish.com/search"
    PAGE_SIZE = 20

    # ── 强反爬配置 ──────────────────────────────────────────────────────
    BROWSER_CHANNEL = "msedge"
    MIN_DELAY = 5.0      # 更保守的延迟（阿里安全比小红书/抖音更严）
    MAX_DELAY = 16.0
    BACKOFF_THRESHOLD = 2
    MAX_RETRIES = 3

    def __init__(self, headless: bool = False):
        # 闲鱼必须可见模式，headless 秒触发验证码
        super().__init__(headless=False)
        self._profile_dir = os.path.join(
            settings.raw_data_dir.as_posix(),
            "browser_profiles", "xianyu",
        )
        self._api_responses: list[dict] = []

    def start(self):
        """使用 v3 持久化浏览器启动（覆盖 BaseSpider.start()）。"""
        self.start_persistent(user_data_dir=self._profile_dir)

    def close(self):
        """关闭浏览器（兼容 v3 持久化模式）。"""
        self._save_incremental_state()
        self._save_checkpoint()
        if self._context:
            try:
                self._context.close()
            except Exception:
                pass
        if self._playwright:
            self._playwright.stop()
            logger.info(f"{self.PLATFORM} Spider 已关闭")

    # ═══════════════════════════════════════════════════════════════════════
    # 核心: 搜索 + 解析
    # ═══════════════════════════════════════════════════════════════════════

    def search_and_parse(
        self, keyword: str, max_pages: int = 3, **kwargs
    ) -> list[ParsedXianyuItem]:
        """搜索关键词，提取搜索结果列表。

        三层策略（按优先级）:
          1. 浏览器内 fetch API 调用（类似知乎/抖音的 page.evaluate(fetch) 模式）
          2. SSR 数据提取（__NEXT_DATA__ / __INITIAL_STATE__）
          3. DOM 解析兜底

        Args:
            keyword: 搜索关键词
            max_pages: 最大滚动次数

        Returns:
            ParsedXianyuItem 列表
        """
        all_items: list[ParsedXianyuItem] = []
        self._api_responses.clear()

        # 1. 导航到搜索页
        search_url = f"{self.SEARCH_URL}?q={keyword}&spm=goofish_search.search"
        try:
            self.human_mouse()
            time.sleep(self.gauss_delay(1, 3))
            self._page.goto(search_url, wait_until="domcontentloaded", timeout=30000)
            time.sleep(self.gauss_delay(3, 6))
        except Exception as exc:
            logger.error(f"搜索页加载失败: {exc}")
            return all_items

        if self._is_blocked():
            logger.error("检测到反爬拦截页面，终止本次采集")
            return all_items

        # ── 策略1: 浏览器内API调用（最优先） ──────────────────────
        api_items = self._fetch_via_browser_api(keyword, max_pages)
        if api_items:
            all_items.extend(api_items)
            logger.info(f"浏览器API调用获取 {len(api_items)} 条")

        # ── 策略2: SSR数据提取 ──────────────────────────────────
        ssr_items = self._parse_ssr_data(keyword)
        if ssr_items:
            existing_ids = {i.item_id for i in all_items}
            new_ssr = [it for it in ssr_items if it.item_id not in existing_ids]
            all_items.extend(new_ssr)
            logger.info(f"SSR 提取补充 {len(new_ssr)} 条")

        # ── 策略3: DOM解析兜底 ──────────────────────────────────
        if not all_items:
            logger.info("API+SSR 均未获取数据，尝试 DOM 解析...")
            try:
                html = self._page.content()
                dom_items = self._parse_dom_results(html, keyword)
                all_items.extend(dom_items)
                logger.info(f"DOM 解析获取 {len(dom_items)} 条")
            except Exception as exc:
                logger.error(f"DOM 解析失败: {exc}")

        # 去重 + 过滤空内容
        seen = set()
        unique = []
        for item in all_items:
            key = item.item_id or item.source_url
            if key not in seen and item.content_raw and item.content_raw.strip():
                seen.add(key)
                unique.append(item)

        logger.info(f"搜索 [{keyword}] 完成: 共获取 {len(unique)} 条")
        return unique

    # ═══════════════════════════════════════════════════════════════════════
    # 策略1: 浏览器内 fetch API 调用（最高效，数据最完整）
    # ═══════════════════════════════════════════════════════════════════════

    def _fetch_via_browser_api(
        self, keyword: str, max_pages: int = 3,
    ) -> list[ParsedXianyuItem]:
        """在浏览器上下文中直接调用闲鱼搜索API。

        利用 page.evaluate(fetch) 在真实浏览器内执行API请求，
        自动携带所有认证信息（Cookie/Token/签名），
        比SSR解析更可靠，比DOM解析更准确。

        闲鱼搜索API端点（goofish.com）可能是:
          - /api/search
          - /idle/search
          - /mtop.taobao.idle.search
        """
        items = []
        # 已知的闲鱼API端点（通过浏览器网络面板确认）
        api_endpoints = [
            "https://www.goofish.com/api/search?q={kw}&page={p}&size=20",
            "https://www.goofish.com/idle/search?q={kw}&page={p}&size=20",
        ]

        for page in range(1, max_pages + 1):
            if len(items) >= 30:
                break

            for endpoint_template in api_endpoints:
                url = endpoint_template.format(kw=keyword, p=page)
                try:
                    # 在浏览器JS上下文中执行fetch
                    result = self._page.evaluate(f"""
                        async () => {{
                            try {{
                                const resp = await fetch('{url}', {{
                                    headers: {{
                                        'Accept': 'application/json',
                                        'X-Requested-With': 'XMLHttpRequest',
                                    }},
                                    credentials: 'include',
                                }});
                                if (resp.ok) {{
                                    const text = await resp.text();
                                    return text;
                                }}
                            }} catch(e) {{}}
                            return null;
                        }}
                    """)
                    if result:
                        try:
                            data = json.loads(result)
                            parsed = self._extract_from_api_json(data, keyword)
                            if parsed:
                                items.extend(parsed)
                        except json.JSONDecodeError:
                            # 非JSON响应，继续尝试下一个端点
                            continue
                except Exception:
                    continue

            if items:
                time.sleep(self.gauss_delay(1, 3))

        return items

    @staticmethod
    def _extract_from_api_json(data: dict, keyword: str) -> list[ParsedXianyuItem]:
        """从API返回的JSON中提取商品列表。"""
        items = []

        def _find_list(obj, depth=0):
            if depth > 8:
                return []
            results = []
            if isinstance(obj, dict):
                for key, val in obj.items():
                    if key in ("items", "resultList", "list", "itemList",
                              "data", "records", "results"):
                        if isinstance(val, list):
                            results.extend(
                                v for v in val if isinstance(v, dict)
                                and ("itemId" in v or "item_id" in v or "id" in v)
                            )
                    elif isinstance(val, (dict, list)):
                        results.extend(_find_list(val, depth + 1))
            elif isinstance(obj, list):
                for elem in obj:
                    results.extend(_find_list(elem, depth + 1))
            return results

        raw_items = _find_list(data)
        for raw in raw_items:
            try:
                item_id = str(raw.get("itemId") or raw.get("item_id") or raw.get("id", ""))
                title = raw.get("title", "")
                if isinstance(title, list):
                    title = " ".join(str(t) for t in title)
                price = raw.get("price") or raw.get("salePrice") or raw.get("priceStr", "0")
                if isinstance(price, str):
                    try:
                        price = float(price.replace(",", ""))
                    except (ValueError, AttributeError):
                        price = 0.0

                seller = raw.get("seller") or raw.get("userInfo") or {}
                if isinstance(seller, dict):
                    seller_name = seller.get("nick") or seller.get("nickName", "")
                    seller_id = str(seller.get("userId") or seller.get("userNumId", ""))
                else:
                    seller_name = str(seller) if seller else ""
                    seller_id = ""

                if title.strip():
                    items.append(ParsedXianyuItem(
                        content_raw=str(title).strip(),
                        source_url=f"https://www.goofish.com/item?id={item_id}",
                        author_uid=seller_id,
                        author_username=seller_name,
                        item_id=item_id,
                        keyword=keyword,
                        price=float(price),
                        location=raw.get("location") or raw.get("ipLocation", ""),
                        seller_rating=raw.get("zhimaCredit") or "",
                        image_list=raw.get("images") or raw.get("imageList") or [],
                        metadata={
                            "keyword": keyword,
                            "item_id": item_id,
                            "price": float(price),
                        },
                    ))
            except Exception:
                continue

        return items

    # ═══════════════════════════════════════════════════════════════════════
    # SSR 数据提取
    # ═══════════════════════════════════════════════════════════════════════

    def _parse_ssr_data(self, keyword: str) -> list[ParsedXianyuItem]:
        """从 SSR 数据提取搜索结果（支持多种注入模式 + <script> 标签提取）。"""
        items = []

        # 方法1: 全局变量注入模式
        ssr_patterns = [
            "window.__INITIAL_STATE__",
            "window.__NEXT_DATA__",
            "window.__NUXT__",
            "window.__DATA__",
            "window.__RENDER_DATA__",
        ]
        for pattern in ssr_patterns:
            try:
                raw = self._page.evaluate(
                    f"(function(){{ try {{ return JSON.stringify({pattern}); }} catch(e) {{ return null; }} }})()"
                )
                if raw and raw != "null" and len(raw) > 10:
                    data = json.loads(raw)
                    extracted = self._extract_from_ssr(data, keyword)
                    if extracted:
                        items = extracted
                        break
            except Exception:
                continue

        # 方法2: <script> 标签中内嵌的 JSON 数据
        if not items:
            try:
                script_data = self._page.evaluate("""
                    () => {
                        const scripts = document.querySelectorAll('script[type="application/json"], script[id*="data"], script[id*="state"]');
                        const results = [];
                        scripts.forEach(s => {
                            try {
                                const data = JSON.parse(s.textContent);
                                if (data) results.push(data);
                            } catch(e) {}
                        });
                        // Also try __NEXT_DATA__ in script tag
                        const nextData = document.getElementById('__NEXT_DATA__');
                        if (nextData) {
                            try {
                                results.push(JSON.parse(nextData.textContent));
                            } catch(e) {}
                        }
                        return results;
                    }
                """)
                for data in (script_data or []):
                    extracted = self._extract_from_ssr(data, keyword)
                    if extracted:
                        items.extend(extracted)
            except Exception:
                pass

        return items

    def _extract_from_ssr(self, data: dict, keyword: str) -> list[ParsedXianyuItem]:
        """递归从 SSR 数据中提取商品列表。"""
        items = []

        def _recurse(obj, depth=0):
            if depth > 10:
                return
            if isinstance(obj, dict):
                # 检测商品条目
                if "itemId" in obj or "item_id" in obj:
                    try:
                        item = self._parse_ssr_item(obj, keyword)
                        if item and item.content_raw:
                            items.append(item)
                    except Exception:
                        pass
                # 遍历 array 类型的值
                for v in obj.values():
                    if isinstance(v, list):
                        for elem in v:
                            if isinstance(elem, dict) and (
                                "itemId" in elem or "item_id" in elem
                            ):
                                try:
                                    item = self._parse_ssr_item(elem, keyword)
                                    if item and item.content_raw:
                                        items.append(item)
                                except Exception:
                                    pass
                            _recurse(elem, depth + 1)
                    elif isinstance(v, dict):
                        _recurse(v, depth + 1)
            elif isinstance(obj, list):
                for elem in obj:
                    _recurse(elem, depth + 1)

        _recurse(data)
        return items

    def _parse_ssr_item(self, raw: dict, keyword: str) -> ParsedXianyuItem | None:
        """解析单个 SSR 商品条目。"""
        try:
            item_id = str(raw.get("itemId") or raw.get("item_id", ""))
            title = raw.get("title", "")
            if isinstance(title, list):  # 有时候 title 是数组
                title = title[0] if title else ""
            desc = raw.get("description") or raw.get("desc", "")
            content = f"{title}\n{desc}" if desc else title
            if not content.strip():
                return None

            price_val = raw.get("price") or raw.get("salePrice") or 0
            if isinstance(price_val, str):
                try:
                    price_val = float(price_val)
                except ValueError:
                    price_val = 0.0

            seller = raw.get("seller") or raw.get("userInfo") or {}
            if isinstance(seller, dict):
                seller_name = seller.get("nick") or seller.get("nickName", "")
                seller_id = str(seller.get("userId") or seller.get("userNumId", ""))
                seller_rating = seller.get("zhimaCredit") or seller.get("creditLevel", "")
            else:
                seller_name = str(seller) if seller else ""
                seller_id = ""
                seller_rating = ""

            return ParsedXianyuItem(
                content_raw=content.strip(),
                source_url=f"https://www.goofish.com/item?id={item_id}",
                author_uid=seller_id,
                author_username=seller_name,
                item_id=item_id,
                keyword=keyword,
                price=float(price_val),
                location=raw.get("location") or raw.get("ipLocation", ""),
                seller_rating=seller_rating,
                listing_status="active" if raw.get("status", 0) == 0 else "sold",
                like_count=int(raw.get("wantCount") or raw.get("likeCount") or 0),
                comment_count=int(raw.get("commentCount") or 0),
                image_list=raw.get("images") or raw.get("imageList") or [],
                metadata={
                    "keyword": keyword,
                    "item_id": item_id,
                    "price": float(price_val),
                    "location": raw.get("location") or raw.get("ipLocation", ""),
                    "seller_rating": seller_rating,
                },
            )
        except Exception as exc:
            logger.debug(f"SSR 条目解析失败: {exc}")
            return None

    # ═══════════════════════════════════════════════════════════════════════
    # DOM 解析（兜底）
    # ═══════════════════════════════════════════════════════════════════════

    def _parse_dom_results(self, html: str, keyword: str) -> list[ParsedXianyuItem]:
        """从 DOM 解析搜索结果（SSR 不可用时的兜底方案）。"""
        items = []
        try:
            # 通过 page.evaluate 提取 DOM 数据
            results = self._page.evaluate("""
                () => {
                    const items = [];
                    // 尝试多种选择器
                    const selectors = [
                        '[class*="searchResult"] [class*="item"]',
                        '[class*="card"]',
                        '[class*="listItem"]',
                        'a[href*="/item?"]',
                    ];
                    for (const sel of selectors) {
                        const els = document.querySelectorAll(sel);
                        if (els.length > 0) {
                            els.forEach(el => {
                                const link = el.querySelector('a[href*="/item?"]') || el.closest('a[href*="/item?"]');
                                const titleEl = el.querySelector('[class*="title"], h3, h4');
                                const priceEl = el.querySelector('[class*="price"], [class*="Price"]');
                                const sellerEl = el.querySelector('[class*="seller"], [class*="nick"], [class*="user"]');
                                const locEl = el.querySelector('[class*="location"], [class*="ip"]');
                                if (titleEl || link) {
                                    items.push({
                                        title: titleEl?.textContent?.trim() || '',
                                        url: link?.href || '',
                                        price: priceEl?.textContent?.trim() || '',
                                        seller: sellerEl?.textContent?.trim() || '',
                                        location: locEl?.textContent?.trim() || '',
                                    });
                                }
                            });
                            break;
                        }
                    }
                    return items;
                }
            """)

            for result in results or []:
                if not result.get("title") and not result.get("url"):
                    continue

                # 提取价格数字
                price_str = result.get("price", "0")
                price_match = re.search(r'[\d.]+', price_str.replace(',', ''))
                price = float(price_match.group()) if price_match else 0.0

                # 提取 item ID
                item_id = ""
                url = result.get("url", "")
                id_match = re.search(r'[?&]id=(\d+)', url)
                if id_match:
                    item_id = id_match.group(1)

                items.append(ParsedXianyuItem(
                    content_raw=result.get("title", ""),
                    source_url=url,
                    author_username=result.get("seller", ""),
                    item_id=item_id,
                    keyword=keyword,
                    price=price,
                    location=result.get("location", ""),
                    metadata={"keyword": keyword, "item_id": item_id, "price": price},
                ))

        except Exception as exc:
            logger.error(f"DOM 解析失败: {exc}")

        return items

    # ═══════════════════════════════════════════════════════════════════════
    # API 响应拦截
    # ═══════════════════════════════════════════════════════════════════════

    def _setup_search_interception(self):
        """拦截搜索 API 响应。"""
        if not self._page:
            return

        def _on_response(response):
            url = response.url
            if any(api in url for api in [
                "/search", "/mtop.taobao.idle.search",
                "/idle/search", "/goofish/search",
            ]):
                try:
                    body = response.json()
                    if body:
                        self._api_responses.append(body)
                except Exception:
                    pass

        try:
            self._page.on("response", _on_response)
            self._on_response_handler = _on_response
        except Exception:
            pass

    def _parse_api_responses(self, keyword: str) -> list[ParsedXianyuItem]:
        """解析拦截到的 API 响应。"""
        items = []
        for resp_data in self._api_responses:
            try:
                # 递归搜索商品列表
                results = self._find_items_in_json(resp_data)
                for raw in results:
                    item = self._parse_ssr_item(raw, keyword)
                    if item:
                        items.append(item)
            except Exception:
                pass
        return items

    @staticmethod
    def _find_items_in_json(data, depth=0):
        """递归在 JSON 中查找商品列表。"""
        results = []
        if depth > 10:
            return results
        if isinstance(data, dict):
            for key, val in data.items():
                if key in ("items", "resultList", "list", "itemList") and isinstance(val, list):
                    results.extend(v for v in val if isinstance(v, dict))
                elif isinstance(val, (dict, list)):
                    results.extend(XianyuSearchSpider._find_items_in_json(val, depth + 1))
        elif isinstance(data, list):
            for elem in data:
                if isinstance(elem, dict):
                    results.extend(XianyuSearchSpider._find_items_in_json(elem, depth + 1))
        return results

    # ═══════════════════════════════════════════════════════════════════════
    # 详情页留言采集
    # ═══════════════════════════════════════════════════════════════════════

    def fetch_item_messages(self, item_id: str, max_pages: int = 2) -> list[dict]:
        """提取商品详情页的留言（闲鱼留言 = 评论区）。

        留言显示在商品详情页下方，可通过 SSR 或 DOM 获取。
        """
        messages = []
        if not self._page:
            return messages

        detail_url = f"https://www.goofish.com/item?id={item_id}"
        try:
            self.human_mouse()
            time.sleep(self.gauss_delay(2, 5))
            self._page.goto(detail_url, wait_until="domcontentloaded", timeout=20000)
            time.sleep(self.gauss_delay(3, 6))
            self.human_scroll()

            # 从 SSR 或 DOM 提取留言
            try:
                data = self._page.evaluate("JSON.stringify(window.__INITIAL_STATE__)")
                ssr = json.loads(data) if data else {}
                messages_raw = self._find_messages_in_ssr(ssr)
                if messages_raw:
                    messages.extend(messages_raw)
            except Exception:
                pass

            # DOM 兜底
            if not messages:
                messages = self._page.evaluate("""
                    () => {
                        const msgs = [];
                        const sel = '[class*="message"], [class*="comment"], [class*="reply"]';
                        document.querySelectorAll(sel).forEach(el => {
                            const text = el.textContent?.trim();
                            if (text && text.length > 2) {
                                msgs.push({content: text, type: "message"});
                            }
                        });
                        return msgs;
                    }
                """) or []

        except Exception as exc:
            logger.warning(f"留言提取失败 (item={item_id}): {exc}")

        return messages

    def _find_messages_in_ssr(self, data, depth=0):
        """从 SSR 数据中递归查找留言。"""
        messages = []
        if depth > 8:
            return messages
        if isinstance(data, dict):
            for key, val in data.items():
                if key in ("messages", "comments", "replies") and isinstance(val, list):
                    for msg in val:
                        if isinstance(msg, dict):
                            messages.append({
                                "id": str(msg.get("id", "")),
                                "author_uid": str(msg.get("userId", "")),
                                "author_username": msg.get("userName", ""),
                                "content": msg.get("content") or msg.get("text", ""),
                                "created_at": str(msg.get("createTime", "")),
                                "type": "message",
                            })
                elif isinstance(val, (dict, list)):
                    messages.extend(self._find_messages_in_ssr(val, depth + 1))
        elif isinstance(data, list):
            for elem in data:
                messages.extend(self._find_messages_in_ssr(elem, depth + 1))
        return messages


# ═══════════════════════════════════════════════════════════════════════════════
# 测试入口
# ═══════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    import os
    spider = XianyuSearchSpider()
    try:
        spider.start()
        items = spider.search_and_parse("账号交易", max_pages=2)
        for item in items:
            logger.info(f"  {item.item_id}: {item.content_raw[:60]}... ¥{item.price}")
    finally:
        spider.close()
