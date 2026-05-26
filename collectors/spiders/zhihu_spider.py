"""
知乎关键词搜索 Spider（Playwright + API 拦截）

核心策略:
  不解析 HTML，通过 page.evaluate() 在浏览器上下文中直接调用
  知乎搜索 API (/api/v4/search_v3)，获取结构化 JSON 响应。
  优势：无需处理 x-zse-96 签名头，浏览器自动携带。

流程:
  1. 启动 Chromium → 注入 Cookie → 访问知乎首页建立会话
  2. 通过 page.evaluate(fetch) 调用搜索 API → 获取 JSON 结果
  3. 可选：调用问题答案 API 获取完整回答 + 评论
  4. 输出 ParsedZhihuItem 列表

反爬策略:
  - 随机 User-Agent 轮换
  - navigator.webdriver 隐藏
  - 较长随机请求间隔 (3~6s, 知乎反爬强)
  - Cookie 登录态注入
  - 限制每次翻页数和请求频率
"""

import time
import re
import os
import json
import random
from datetime import datetime, timedelta
from dataclasses import dataclass, field
from loguru import logger
from playwright.sync_api import sync_playwright, Browser, Page

from config.settings import settings


# ── User-Agent 池 ──────────────────────────────────────────────────────────────

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:120.0) Gecko/20100101 Firefox/120.0",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/118.0.0.0 Safari/537.36",
]


def random_ua() -> str:
    return random.choice(USER_AGENTS)


# ── 解析结果结构 ──────────────────────────────────────────────────────────────

@dataclass
class ParsedZhihuItem:
    """知乎搜索结果解析后的结构化数据。"""
    platform: str = "zhihu"
    content_raw: str = ""              # 问题标题 + 回答摘要
    content_type: str = "text"
    source_url: str = ""               # 问题或答案链接
    author_uid: str = ""
    author_username: str = ""
    question_id: str = ""
    answer_id: str = ""
    collected_at: datetime = field(default_factory=datetime.utcnow)
    keyword: str = ""
    voteup_count: int = 0              # 点赞数
    comment_count: int = 0             # 评论数
    topics: list[str] = field(default_factory=list)  # 话题标签
    metadata: dict = field(default_factory=dict)


@dataclass
class ParsedZhihuComment:
    """知乎回答下的单条评论。"""
    author_username: str = ""
    author_uid: str = ""
    content: str = ""
    created_time: datetime | None = None


# ── Spider ─────────────────────────────────────────────────────────────────────

class ZhihuSearchSpider:
    """知乎搜索 Spider — 通过 API 搜索并返回结构化数据。

    使用方式:
        spider = ZhihuSearchSpider()
        spider.start()
        items = spider.search_and_parse("刷单", max_pages=2)
        spider.close()
    """

    ZHIHU_HOME = "https://www.zhihu.com"
    SEARCH_API = "https://www.zhihu.com/api/v4/search_v3"
    ANSWERS_API = "https://www.zhihu.com/api/v4/questions/{qid}/answers"
    COMMENTS_API = "https://www.zhihu.com/api/v4/answers/{aid}/comments"
    PAGE_SIZE = 20  # 知乎 API 每页返回数量

    def __init__(
        self,
        headless: bool = True,
        fetch_answers: bool = True,
        fetch_comments: bool = False,
        max_answers_per_question: int = 3,
    ):
        """
        Args:
            headless: 是否无头模式
            fetch_answers: 是否拉取问题的完整回答内容
            fetch_comments: 是否拉取回答的评论（会增加请求量）
            max_answers_per_question: 每个问题最多拉取多少条回答
        """
        self.headless = headless
        self.fetch_answers = fetch_answers
        self.fetch_comments = fetch_comments
        self.max_answers = max_answers_per_question
        self._playwright = None
        self._browser: Browser | None = None
        self._context = None
        self._page: Page | None = None
        self._logged_in = False
        self._cookie_file = os.path.join(
            settings.raw_data_dir.as_posix(), "zhihu_cookies.json"
        )
        self._last_collected_at: dict[str, datetime] = {}
        self._incremental_file = os.path.join(
            settings.raw_data_dir.as_posix(), "zhihu_last_collected.json"
        )

    @staticmethod
    def _load_cookies(platform: str) -> list[dict] | None:
        """加载平台 Cookie：优先环境变量 BGI_{PLATFORM}_COOKIES，文件兜底。"""
        env_val = getattr(settings, f"{platform}_cookies", "")
        if env_val:
            try:
                cookies = json.loads(env_val)
                if isinstance(cookies, list) and cookies:
                    return cookies
            except json.JSONDecodeError:
                pass
        cookie_file = os.path.join(
            settings.raw_data_dir.as_posix(), f"{platform}_cookies.json"
        )
        if os.path.exists(cookie_file):
            try:
                with open(cookie_file, "r", encoding="utf-8") as f:
                    cookies = json.load(f)
                if isinstance(cookies, list) and cookies:
                    return cookies
            except Exception:
                pass
        return None

    # ── 生命周期 ────────────────────────────────────────────────────────────

    def start(self):
        """启动浏览器，建立知乎会话。使用 JS 注入 Cookie（add_cookies 对知乎无效）。"""
        self._playwright = sync_playwright().start()
        self._browser = self._playwright.chromium.launch(
            headless=self.headless,
            args=[
                "--disable-blink-features=AutomationControlled",
                "--no-sandbox",
            ],
        )
        self._context = self._browser.new_context(
            user_agent=random_ua(),
            locale="zh-CN",
            viewport={"width": 1366, "height": 768},
        )

        self._page = self._context.new_page()
        self._page.add_init_script("""
            Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
        """)

        # 先访问知乎首页建立域名上下文
        try:
            self._page.goto(self.ZHIHU_HOME, wait_until="domcontentloaded", timeout=20000)
            time.sleep(2)
        except Exception:
            logger.warning("预热访问 zhihu.com 超时，继续...")

        # 通过 JS 注入 Cookie（Playwright 的 add_cookies 对知乎无效）
        cookies = self._load_cookies("zhihu")
        if cookies:
            try:
                self._inject_cookies_via_js(cookies)
                self._logged_in = True
                logger.info(f"已通过 JS 注入 {len(cookies)} 条知乎 Cookie")
            except Exception as exc:
                logger.warning(f"Cookie JS 注入失败: {exc}")
        else:
            logger.warning("未配置知乎 Cookie（环境变量 BGI_ZHIHU_COOKIES 或文件），搜索可能受限")

        self._load_incremental_state()
        logger.info(
            f"知乎搜索 Spider 已启动（登录态={'是' if self._logged_in else '否'}）"
        )

    def _inject_cookies_via_js(self, cookies: list[dict]):
        """通过 page.evaluate 在浏览器中执行 document.cookie 设置。

        只注入认证 Token（z_c0 / d_c0），跳过服务端动态生成的会话
        Cookie（JOID/osd/__zse_ck 等），避免旧值覆盖新值导致登录失效。
        """
        # 只注入认证 Cookie，服务端会话 Cookie 让其自然生成
        auth_cookie_names = {"z_c0", "d_c0"}
        for c in cookies:
            if c["name"] not in auth_cookie_names:
                continue
            self._page.evaluate(
                """(args) => {
                    document.cookie = args[0] + '=' + args[1] + '; domain=' + args[2] + '; path=' + args[3] + '; SameSite=Lax';
                }""",
                [c["name"], c["value"], c.get("domain", ".zhihu.com"), c.get("path", "/")],
            )

    def close(self):
        """关闭浏览器，持久化增量状态。"""
        self._save_incremental_state()
        if self._browser:
            self._browser.close()
            logger.info("知乎搜索 Spider 已关闭")
        if self._playwright:
            self._playwright.stop()

    # ── 增量采集状态 ────────────────────────────────────────────────────────

    def _load_incremental_state(self):
        if os.path.exists(self._incremental_file):
            try:
                with open(self._incremental_file, "r", encoding="utf-8") as f:
                    raw = json.load(f)
                for k, v in raw.items():
                    self._last_collected_at[k] = datetime.fromisoformat(v)
                logger.info(f"已加载 {len(self._last_collected_at)} 个知乎关键词的增量状态")
            except Exception as exc:
                logger.warning(f"加载增量状态失败: {exc}")

    def _save_incremental_state(self):
        try:
            raw = {k: v.isoformat() for k, v in self._last_collected_at.items()}
            with open(self._incremental_file, "w", encoding="utf-8") as f:
                json.dump(raw, f, ensure_ascii=False, indent=2)
        except Exception as exc:
            logger.warning(f"保存增量状态失败: {exc}")

    def _update_last_collected(self, keyword: str, dt: datetime):
        if keyword not in self._last_collected_at or dt > self._last_collected_at[keyword]:
            self._last_collected_at[keyword] = dt

    # ── 搜索入口 ────────────────────────────────────────────────────────────

    def search_and_parse(self, keyword: str, max_pages: int = 3) -> list[ParsedZhihuItem]:
        """按关键词搜索知乎：访问搜索页 → 解析 SSR/渲染 DOM → 返回结构化数据。"""
        if not self._page:
            raise RuntimeError("Spider 未启动，请先调用 start()")

        last_ts = self._last_collected_at.get(keyword)
        if last_ts:
            logger.info(f"增量采集 [{keyword}]：跳过 {last_ts.isoformat()} 之前的内容")

        all_items = []
        for page_num in range(1, max_pages + 1):
            offset = (page_num - 1) * self.PAGE_SIZE
            logger.info(f"搜索 [{keyword}] 第{page_num}/{max_pages}页")

            try:
                items = self._fetch_and_parse_search_page(keyword, offset)
                if not items:
                    logger.warning(f"  搜索结果为空，可能已到末尾")
                    break

                new_count = 0
                for item in items:
                    if last_ts and item.collected_at and item.collected_at <= last_ts:
                        continue
                    new_count += 1

                    # 获取完整回答内容
                    if self.fetch_answers and item.question_id:
                        try:
                            answers = self._fetch_answers(item.question_id)
                            if answers:
                                best_answer = answers[0]
                                if best_answer.get("content"):
                                    item.content_raw = (
                                        f"【问题】{item.content_raw}\n"
                                        f"【回答】@{best_answer.get('author_username', '')}: "
                                        f"{best_answer.get('content', '')}"
                                    )
                                item.metadata["answers"] = answers
                                item.metadata["answer_count"] = len(answers)
                        except Exception as exc:
                            logger.debug(f"  获取问题 {item.question_id} 回答失败: {exc}")
                        delay = 2.0 + random.random() * 3.0
                        time.sleep(delay)

                    all_items.append(item)
                    self._update_last_collected(keyword, item.collected_at or datetime.utcnow())

                logger.info(f"  第{page_num}页: 解析 {len(items)} 条, 新增 {new_count} 条")

                if len(items) < self.PAGE_SIZE:
                    break

            except Exception as exc:
                logger.error(f"  第{page_num}页处理失败: {exc}")
                continue

            if page_num < max_pages:
                delay = 3.0 + random.random() * 3.0
                time.sleep(delay)

        logger.info(f"搜索 [{keyword}] 完成，共 {len(all_items)} 条知乎内容")
        return all_items

    def _fetch_and_parse_search_page(
        self, keyword: str, offset: int = 0
    ) -> list[ParsedZhihuItem]:
        """访问知乎搜索页，从渲染 DOM 提取搜索结果。

        先导航到搜索页 → 注入 Cookie → 重载页面（让 Cookie 随请求发送）
        → 等待结果渲染 → 提取 DOM。
        """
        from urllib.parse import quote

        url = f"https://www.zhihu.com/search?type=content&q={quote(keyword)}"
        if offset > 0:
            url += f"&offset={offset}"

        # 步骤1：先打开搜索页建立域名上下文
        self._page.goto(url, wait_until="domcontentloaded", timeout=30000)
        time.sleep(1)

        # 步骤2：注入认证 Cookie
        if self._logged_in:
            self._reinject_auth_cookies()
            time.sleep(0.5)

        # 步骤3：重载页面，让 Cookie 随 HTTP 请求发送
        self._page.reload(wait_until="domcontentloaded", timeout=30000)
        time.sleep(1)

        # 步骤4：等待搜索结果动态渲染
        try:
            self._page.wait_for_selector(".SearchResult-Card", timeout=15000)
        except Exception:
            pass
        time.sleep(2)

        html = self._page.content()
        items = []

        # 从 SSR 提取
        items.extend(self._parse_search_from_ssr(html, keyword))

        # 从渲染 DOM 提取
        if not items:
            items.extend(self._parse_search_from_dom(keyword))

        return items

    def _reinject_auth_cookies(self):
        """重新注入认证 Cookie（每次导航后调用）。"""
        cookies = self._load_cookies("zhihu")
        if not cookies:
            return
        auth_names = {"z_c0", "d_c0"}
        for c in cookies:
            if c["name"] not in auth_names:
                continue
            self._page.evaluate(
                """(args) => {
                    document.cookie = args[0] + '=' + args[1] + '; domain=' + args[2] + '; path=' + args[3] + '; SameSite=Lax';
                }""",
                [c["name"], c["value"], c.get("domain", ".zhihu.com"), c.get("path", "/")],
            )

    def _parse_search_from_ssr(self, html: str, keyword: str) -> list[ParsedZhihuItem]:
        """从 SSR JSON 数据中提取搜索结果。"""
        items = []
        init_m = re.search(
            r'<script[^>]*id="js-initialData"[^>]*>(.*?)</script>',
            html, re.DOTALL,
        )
        if not init_m:
            return items

        try:
            data = json.loads(init_m.group(1))
            ist = data.get("initialState", {})
            search = ist.get("search", {})

            # 尝试多个可能的查询键
            for qtype in [
                "generalByQuery", "generalByQueryInADay",
                "generalByQueryInAWeek", "generalByQueryInThreeMonths",
            ]:
                qdata = search.get(qtype, {})
                if not isinstance(qdata, dict) or not qdata:
                    continue
                for key, val in qdata.items():
                    if not key.isdigit():
                        continue
                    obj = val.get("object", {}) if isinstance(val, dict) else {}
                    item = self._parse_search_object(obj, keyword)
                    if item and item.content_raw:
                        items.append(item)
                if items:
                    break
        except (json.JSONDecodeError, KeyError, TypeError):
            pass

        return items

    def _parse_search_from_dom(self, keyword: str) -> list[ParsedZhihuItem]:
        """从渲染后的 DOM 中提取搜索结果（知乎新版 React 渲染结构）。"""
        js_code = """
        () => {
            const items = [];
            // 知乎搜索卡片: .Card.SearchResult-Card > .List-item
            const cards = document.querySelectorAll('.SearchResult-Card');
            cards.forEach(card => {
                const linkEl = card.querySelector('a[href*="/question/"]');
                const link = linkEl ? linkEl.href : '';
                const title = linkEl ? linkEl.innerText.trim() : '';
                // 内容摘要: .RichContent
                const contentEl = card.querySelector('[class*="RichContent"]');
                const snippet = contentEl ? contentEl.innerText.trim() : '';
                // 作者/元信息: .ContentItem-action 或其他
                const metaEl = card.querySelector('[class*="AuthorInfo"], .ContentItem-action');
                const author = metaEl ? metaEl.innerText.trim() : '';
                if (title) {
                    items.push({ title, excerpt: snippet, author, url: link });
                }
            });
            return items;
        }
        """
        try:
            dom_items = self._page.evaluate(js_code)
            result = []
            for d in dom_items:
                if not d.get("title"):
                    continue
                qid = ""
                url_match = re.search(r"/question/(\d+)", d.get("url", ""))
                if url_match:
                    qid = url_match.group(1)
                content_parts = [f"【问题】{d['title']}"]
                if d.get("excerpt"):
                    content_parts.append(f"【摘要】{d['excerpt']}")
                item = ParsedZhihuItem(
                    content_raw="\n".join(content_parts),
                    source_url=d.get("url", ""),
                    author_username=d.get("author", ""),
                    question_id=qid,
                    keyword=keyword,
                )
                result.append(item)
            return result
        except Exception:
            return []

    def _parse_search_object(self, obj: dict, keyword: str) -> ParsedZhihuItem | None:
        """从单个搜索 JSON 对象解析为 ParsedZhihuItem。"""
        result_type = obj.get("type", "")

        question = obj.get("question", {}) or {}
        title = question.get("title", "")
        qid = str(question.get("id", ""))
        question_url = question.get("url", "")
        if question_url and not question_url.startswith("http"):
            question_url = f"https://www.zhihu.com{question_url}"

        if not title and result_type == "question":
            title = obj.get("title", "")
            qid = str(obj.get("id", ""))
            question_url = obj.get("url", "")
            if question_url and not question_url.startswith("http"):
                question_url = f"https://www.zhihu.com{question_url}"

        if not title:
            return None

        excerpt = self._clean_html(obj.get("excerpt", ""))
        content_raw = title
        if excerpt and excerpt != title:
            content_raw = f"【问题】{title}\n【摘要】{excerpt}"

        author = obj.get("author", {}) or {}
        topics = [t.get("name", "") for t in (question.get("topics", []) or []) if isinstance(t, dict)]

        return ParsedZhihuItem(
            content_raw=content_raw,
            source_url=question_url,
            author_uid=str(author.get("id", "")),
            author_username=author.get("name", ""),
            question_id=qid,
            answer_id=str(obj.get("id", "")),
            collected_at=self._ts_to_datetime(obj.get("created_time", 0)),
            keyword=keyword,
            voteup_count=obj.get("voteup_count", 0),
            comment_count=obj.get("comment_count", 0),
            topics=topics,
            metadata={
                "keyword": keyword,
                "result_type": result_type,
                "voteup_count": obj.get("voteup_count", 0),
                "comment_count": obj.get("comment_count", 0),
                "topics": topics,
                "has_emoji": self._contains_emoji(title + excerpt),
            },
        )

    # ── API 调用（通过 page.evaluate 在浏览器上下文内执行）─────────────────

    def _call_search_api(self, keyword: str, offset: int = 0) -> list[dict]:
        """在浏览器上下文中调用知乎搜索 API，返回 JSON 结果列表。"""
        from urllib.parse import quote
        encoded = quote(keyword)
        url = f"{self.SEARCH_API}?q={encoded}&type=content&offset={offset}&limit={self.PAGE_SIZE}"

        js_code = f"""
        async () => {{
            try {{
                const resp = await fetch('{url}', {{
                    method: 'GET',
                    credentials: 'include',
                    headers: {{
                        'Accept': 'application/json',
                        'X-Requested-With': 'XMLHttpRequest',
                    }}
                }});
                if (!resp.ok) {{
                    return {{ error: true, status: resp.status }};
                }}
                return await resp.json();
            }} catch(e) {{
                return {{ error: true, message: e.message }};
            }}
        }}
        """
        result = self._page.evaluate(js_code)

        if not result or result.get("error"):
            status = result.get("status", "?") if result else "null"
            logger.warning(f"  搜索 API 返回异常 (status={status})")
            return []

        # 知乎 API 返回格式: {"data": [...], "paging": {...}}
        data = result.get("data", [])
        return data if isinstance(data, list) else []

    def _fetch_answers(self, question_id: str) -> list[dict]:
        """获取问题的回答列表（通过知乎问题 API）。"""
        url = self.ANSWERS_API.format(qid=question_id)
        url += f"?limit={self.max_answers}&offset=0"
        url += "&include=data[*].content,comment_count,voteup_count,created_time,author"

        js_code = f"""
        async () => {{
            try {{
                const resp = await fetch('{url}', {{
                    method: 'GET',
                    credentials: 'include',
                    headers: {{
                        'Accept': 'application/json',
                        'X-Requested-With': 'XMLHttpRequest',
                    }}
                }});
                if (!resp.ok) {{
                    return {{ error: true, status: resp.status }};
                }}
                return await resp.json();
            }} catch(e) {{
                return {{ error: true, message: e.message }};
            }}
        }}
        """
        result = self._page.evaluate(js_code)

        if not result or result.get("error"):
            return []

        data = result.get("data", [])
        if not isinstance(data, list):
            return []

        answers = []
        for answer_data in data:
            parsed = self._parse_answer(answer_data, question_id)

            # 可选：获取评论
            if self.fetch_comments and answer_data.get("id"):
                try:
                    comments = self._fetch_comments(str(answer_data["id"]))
                    parsed["comments"] = comments
                except Exception:
                    parsed["comments"] = []

            answers.append(parsed)

        return answers

    def _fetch_comments(self, answer_id: str) -> list[dict]:
        """获取回答的评论列表。"""
        url = self.COMMENTS_API.format(aid=answer_id) + "?limit=20&offset=0"

        js_code = f"""
        async () => {{
            try {{
                const resp = await fetch('{url}', {{
                    method: 'GET',
                    credentials: 'include',
                    headers: {{
                        'Accept': 'application/json',
                        'X-Requested-With': 'XMLHttpRequest',
                    }}
                }});
                if (!resp.ok) return {{ error: true }};
                return await resp.json();
            }} catch(e) {{
                return {{ error: true }};
            }}
        }}
        """
        result = self._page.evaluate(js_code)

        if not result or result.get("error"):
            return []

        data = result.get("data", [])
        if not isinstance(data, list):
            return []

        comments = []
        for c in data:
            comments.append({
                "author_username": c.get("author", {}).get("member", {}).get("name", ""),
                "author_uid": c.get("author", {}).get("member", {}).get("id", ""),
                "content": self._clean_html(c.get("content", "")),
                "created_time": self._ts_to_datetime(c.get("created_time", 0)),
            })
        return comments

    # ── 数据解析 ────────────────────────────────────────────────────────────

    def _parse_search_result(self, result: dict, keyword: str) -> ParsedZhihuItem | None:
        """解析单条搜索结果 JSON。"""
        obj = result.get("object", {})
        if not obj:
            return None

        result_type = obj.get("type", "")

        # 提取问题信息（answer 和 article 类型下都有 question 字段）
        question = obj.get("question", {})
        title = ""
        qid = ""
        question_url = ""

        if question:
            title = question.get("title", "")
            qid = str(question.get("id", ""))
            question_url = question.get("url", "")
            if question_url and not question_url.startswith("http"):
                question_url = f"https://www.zhihu.com{question_url}"

        # 如果没有问题信息，可能是 question 类型的搜索结果
        if not title and result_type == "question":
            title = obj.get("title", "")
            qid = str(obj.get("id", ""))
            question_url = obj.get("url", "")
            if question_url and not question_url.startswith("http"):
                question_url = f"https://www.zhihu.com{question_url}"

        if not title:
            return None

        # 摘要/节选内容
        excerpt = obj.get("excerpt", "")
        snippet = self._clean_html(excerpt) if excerpt else ""

        # 组合内容
        content_raw = title
        if snippet and snippet != title:
            content_raw = f"【问题】{title}\n【摘要】{snippet}"

        # 作者
        author = obj.get("author", {})
        author_name = author.get("name", "") if isinstance(author, dict) else ""
        author_uid = author.get("id", "") if isinstance(author, dict) else ""

        # 话题
        topics = []
        for t in question.get("topics", []) if question else []:
            if isinstance(t, dict):
                topics.append(t.get("name", ""))

        item = ParsedZhihuItem(
            content_raw=content_raw,
            content_type="text",
            source_url=question_url,
            author_uid=str(author_uid),
            author_username=author_name,
            question_id=qid,
            answer_id=str(obj.get("id", "")),
            collected_at=self._ts_to_datetime(obj.get("created_time", 0)),
            keyword=keyword,
            voteup_count=obj.get("voteup_count", 0),
            comment_count=obj.get("comment_count", 0),
            topics=topics,
            metadata={
                "keyword": keyword,
                "result_type": result_type,
                "voteup_count": obj.get("voteup_count", 0),
                "comment_count": obj.get("comment_count", 0),
                "topics": topics,
                "has_emoji": self._contains_emoji(title + snippet),
            },
        )
        return item

    def _parse_answer(self, answer_data: dict, question_id: str) -> dict:
        """解析单条回答 JSON。"""
        author = answer_data.get("author", {})
        content_html = answer_data.get("content", "")
        content_text = self._clean_html(content_html) if content_html else ""

        # 提取回答中的表情符号
        content_text = self._extract_emojis_inline(content_text)

        question = answer_data.get("question", {})
        question_title = question.get("title", "") if question else ""

        return {
            "author_username": author.get("name", "") if author else "",
            "author_uid": str(author.get("id", "")) if author else "",
            "content": content_text,
            "question_title": question_title,
            "voteup_count": answer_data.get("voteup_count", 0),
            "comment_count": answer_data.get("comment_count", 0),
            "answer_id": str(answer_data.get("id", "")),
            "created_time": self._ts_to_datetime(answer_data.get("created_time", 0)),
            "comments": [],  # filled later if fetch_comments is enabled
        }

    # ── 辅助方法 ────────────────────────────────────────────────────────────

    @staticmethod
    def _clean_html(text: str) -> str:
        """清理 HTML 标签，保留文本和结构。"""
        if not text:
            return ""
        # 处理换行标签
        text = re.sub(r"<br\s*/?>", "\n", text, flags=re.I)
        text = re.sub(r"</p>", "\n", text, flags=re.I)
        text = re.sub(r"</div>", "\n", text, flags=re.I)
        # 图片保留 alt 文本
        text = re.sub(r'<img[^>]*alt="([^"]*)"[^>]*>', r"[\1]", text)
        text = re.sub(r"<img[^>]*>", "[图片]", text)
        # 链接保留文本
        text = re.sub(r"<a[^>]*>([^<]*)</a>", r"\1", text)
        # 去除其余标签
        text = re.sub(r"<[^>]+>", " ", text)
        # HTML 实体
        text = re.sub(r"&nbsp;", " ", text)
        text = re.sub(r"&amp;", "&", text)
        text = re.sub(r"&lt;", "<", text)
        text = re.sub(r"&gt;", ">", text)
        text = re.sub(r"&quot;", '"', text)
        # 折叠空白
        text = re.sub(r"\s+", " ", text)
        return text.strip()

    @staticmethod
    def _extract_emojis_inline(text: str) -> str:
        """确保 Unicode emoji 保留在文本中。"""
        return text

    @staticmethod
    def _contains_emoji(text: str) -> bool:
        """检测文本是否包含 Unicode emoji 或知乎表情。"""
        emoji_pattern = re.compile(
            "[\U0001F600-\U0001F64F"   # emoticons
            "\U0001F300-\U0001F5FF"   # symbols & pictographs
            "\U0001F680-\U0001F6FF"   # transport & map
            "\U0001F1E0-\U0001F1FF"   # flags
            "\U00002600-\U000027BF"   # misc symbols
            "]", flags=re.UNICODE,
        )
        return bool(emoji_pattern.search(text))

    @staticmethod
    def _ts_to_datetime(ts: int) -> datetime:
        """Unix 时间戳转 datetime。"""
        if ts and ts > 0:
            return datetime.utcfromtimestamp(ts)
        return datetime.utcnow()

    # ── 调试工具 ────────────────────────────────────────────────────────────

    def screenshot(self, path: str = "zhihu_debug.png"):
        """保存当前页面截图。"""
        if self._page:
            full_path = os.path.join(settings.raw_data_dir.as_posix(), path)
            self._page.screenshot(path=full_path, full_page=True)
            logger.info(f"截图已保存: {full_path}")

    def __enter__(self):
        self.start()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()
