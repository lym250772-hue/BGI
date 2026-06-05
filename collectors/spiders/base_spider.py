"""
采集器 Spider 基类 — 统一浏览器管理、反爬策略、重试、断点续采。

所有平台 Spider 继承此类，只需实现:
  - search_and_parse()  搜索+解析入口
  - _parse_results()    解析搜索结果
"""

import time
import re
import os
import json
import random
from datetime import datetime, timedelta
from pathlib import Path
from abc import ABC, abstractmethod
from loguru import logger
from playwright.sync_api import sync_playwright, Browser, BrowserContext, Page

from config.settings import settings


# ═══════════════════════════════════════════════════════════════════════════════
# User-Agent 池
# ═══════════════════════════════════════════════════════════════════════════════

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:133.0) Gecko/20100101 Firefox/133.0",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36 Edg/131.0.0.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.2 Safari/605.1.15",
]


def random_ua() -> str:
    return random.choice(USER_AGENTS)


# ═══════════════════════════════════════════════════════════════════════════════
# BaseSpider
# ═══════════════════════════════════════════════════════════════════════════════

class BaseSpider(ABC):
    """采集器 Spider 基类。

    子类需定义:
      - PLATFORM: str         平台标识 (weibo/tieba/zhihu/...)
      - HOME_URL: str         首页 URL（用于预热 + Cookie 域名上下文）
      - PAGE_SIZE: int        每页结果数（用于分页计算）
    """

    PLATFORM: str = ""
    HOME_URL: str = ""
    PAGE_SIZE: int = 20

    # ── 重试配置 ──────────────────────────────────────────────────────────
    MAX_RETRIES: int = 3          # 页面加载最大重试次数
    RETRY_BASE_DELAY: float = 2.0 # 重试基础等待秒数

    # ── 间隔配置 ──────────────────────────────────────────────────────────
    MIN_DELAY: float = 1.5        # 最小请求间隔
    MAX_DELAY: float = 4.0        # 最大请求间隔
    BACKOFF_THRESHOLD: int = 3    # 连续空结果触发退避的阈值

    # ── 浏览器通道 ──────────────────────────────────────────────────────────
    BROWSER_CHANNEL: str | None = None  # None=Playwright Chromium, 'msedge'=系统Edge

    # ── v3 持久化浏览器 ─────────────────────────────────────────────────────
    PERSISTENT_BROWSER: bool = False  # True = 使用 launch_persistent_context (v3模式)
    PERSISTENT_PROFILE_DIR: str | None = None  # 持久化profile目录

    def __init__(self, headless: bool = True):
        self.headless = headless
        self._playwright = None
        self._browser: Browser | None = None
        self._context: BrowserContext | None = None
        self._page: Page | None = None
        self._logged_in = False
        self._cookie_file = os.path.join(
            settings.raw_data_dir.as_posix(), f"{self.PLATFORM}_cookies.json"
        )
        self._session_established = False

        # ── 增量采集状态 ────────────────────────────────────────────────
        self._last_collected_at: dict[str, datetime] = {}
        self._incremental_file = os.path.join(
            settings.raw_data_dir.as_posix(),
            f"{self.PLATFORM}_last_collected.json",
        )

        # ── 断点续采状态 ────────────────────────────────────────────────
        self._checkpoint_file = os.path.join(
            settings.raw_data_dir.as_posix(),
            f"{self.PLATFORM}_checkpoint.json",
        )
        self._checkpoint: dict = {}  # {keyword: {"page": N, "offset": M, "collected": C}}

        # ── 采集统计 ────────────────────────────────────────────────────
        self.stats: dict[str, int] = {"pages_loaded": 0, "retries": 0, "errors": 0}

    # ═══════════════════════════════════════════════════════════════════════
    # 生命周期
    # ═══════════════════════════════════════════════════════════════════════

    def start(self):
        """启动浏览器、注入 Cookie、预热首页、加载增量状态。"""
        self._playwright = sync_playwright().start()
        launch_kwargs = {
            "headless": self.headless,
            "args": [
                "--disable-blink-features=AutomationControlled",
                "--no-sandbox",
                "--disable-dev-shm-usage",
            ],
        }
        if self.BROWSER_CHANNEL:
            launch_kwargs["channel"] = self.BROWSER_CHANNEL
        self._browser = self._playwright.chromium.launch(**launch_kwargs)
        self._context = self._browser.new_context(
            user_agent=random_ua(),
            locale="zh-CN",
            viewport={"width": 1366, "height": 768},
        )

        # 预热首页建立域名上下文
        try:
            temp_page = self._context.new_page()
            temp_page.goto(self.HOME_URL, wait_until="domcontentloaded", timeout=20000)
            time.sleep(1)
            temp_page.close()
        except Exception:
            logger.warning(f"预热访问 {self.HOME_URL} 超时，继续...")

        # 创建主 page（必须在 _inject_cookies 之前，知乎需要 page.evaluate）
        self._page = self._context.new_page()
        # Playwright-stealth 反检测
        try:
            from playwright_stealth import stealth_sync
            stealth_sync(self._page)
        except ImportError:
            self._page.add_init_script("""
                Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
            """)

        # 注入 Cookie（子类可能用 add_cookies 或 page.evaluate）
        self._inject_cookies()

        # 设置请求拦截（贴吧禁用：会触发百度安全验证）
        if self.PLATFORM != "tieba":
            self._setup_request_interception()

        # Cookie 注入后访问首页建立会话
        if self._logged_in:
            try:
                self._page.goto(self.HOME_URL, wait_until="networkidle" if self.PLATFORM == "tieba" else "domcontentloaded", timeout=20000)
                time.sleep(2)
                self._session_established = True
            except Exception:
                logger.warning("建立登录会话超时，继续...")
                self._session_established = False
        else:
            self._session_established = False

        # 加载增量 + 断点状态
        self._load_incremental_state()
        self._load_checkpoint()

        logger.info(
            f"{self.PLATFORM} Spider 已启动"
            f"（登录态={'是' if self._logged_in else '否'}）"
        )

    def close(self):
        """关闭浏览器，持久化状态。"""
        self._save_incremental_state()
        self._save_checkpoint()
        if self._browser:
            self._browser.close()
            logger.info(f"{self.PLATFORM} Spider 已关闭")
        if self._playwright:
            self._playwright.stop()

    # ═══════════════════════════════════════════════════════════════════════
    # v3 持久化浏览器启动（用于强反爬平台如闲鱼）
    # ═══════════════════════════════════════════════════════════════════════

    def start_persistent(self, user_data_dir: str = None):
        """使用持久化浏览器上下文启动（v3模式）。

        一次登录永久复用，Cookie/session/LocalStorage 全部保留在磁盘上。
        适用于反爬极严的平台（如阿里系闲鱼），需要非headless + 真实浏览器指纹。

        Args:
            user_data_dir: 浏览器profile目录路径
        """
        profile_dir = user_data_dir or self.PERSISTENT_PROFILE_DIR
        if not profile_dir:
            profile_dir = os.path.join(
                settings.raw_data_dir.as_posix(),
                "browser_profiles", self.PLATFORM,
            )
        os.makedirs(profile_dir, exist_ok=True)

        self._playwright = sync_playwright().start()
        launch_kwargs = {
            "headless": False,  # 持久化模式必须可见，否则极易被检测
            "user_data_dir": profile_dir,
            "args": [
                "--disable-blink-features=AutomationControlled",
                "--no-sandbox",
                "--disable-features=TranslateUI",
            ],
            "channel": "msedge",  # Edge内核，真实浏览器指纹
            "locale": "zh-CN",
            "viewport": {"width": 1440, "height": 900},
        }

        try:
            self._context = self._playwright.chromium.launch_persistent_context(
                **launch_kwargs,
            )
        except Exception:
            # Edge不可用时降级为默认Chromium（但反爬效果会降低）
            logger.warning("Edge不可用，降级为默认Chromium")
            del launch_kwargs["channel"]
            self._context = self._playwright.chromium.launch_persistent_context(
                **launch_kwargs,
            )

        self._page = self._context.new_page()
        self._page.add_init_script(
            "Object.defineProperty(navigator,'webdriver',{get:()=>false});"
        )

        # 检查登录状态（更精确的检测：查找登录表单/按钮而非页面文字）
        try:
            self._page.goto(self.HOME_URL, wait_until="domcontentloaded", timeout=20000)
            time.sleep(3)
            page_text = self._page.content()
            # 检测"未登录"特征（登录表单/弹窗，而非导航栏的"登录"链接）
            is_not_logged_in = (
                "手机号登录" in page_text or     # 登录页面标题
                "扫码登录" in page_text or       # 登录页面tab
                "验证码登录" in page_text or     # 登录方式
                "请先登录" in page_text or       # 需要登录弹窗
                "立即登录" in page_text          # 登录按钮
            )
            if is_not_logged_in or "验证" in page_text:
                if is_not_logged_in:
                    logger.warning("检测到登录页面，请在浏览器中手动完成登录")
                else:
                    logger.warning("检测到验证页面，请在浏览器中完成验证")
                # 等待用户手动登录（最多等待3分钟，已通过interactive_login登录过）
                for i in range(90):
                    time.sleep(2)
                    try:
                        page_text = self._page.content()
                        still_not_logged = (
                            "手机号登录" in page_text
                            or "扫码登录" in page_text
                            or "请先登录" in page_text
                        )
                        if not still_not_logged and "验证" not in page_text:
                            self._logged_in = True
                            logger.info("手动登录/验证完成")
                            break
                    except Exception:
                        pass
                else:
                    logger.warning("登录等待超时（3分钟），继续尝试采集")
            else:
                self._logged_in = True
                logger.info("检测到已登录状态（持久化Profile复用成功）")
        except Exception as exc:
            logger.warning(f"登录状态检测失败: {exc}")

        self._session_established = self._logged_in

        # 加载增量 + 断点状态
        self._load_incremental_state()
        self._load_checkpoint()

        logger.info(
            f"{self.PLATFORM} Spider 已启动（v3持久化模式）"
            f"（登录态={'是' if self._logged_in else '否'}，"
            f"Profile={profile_dir}）"
        )

    # ═══════════════════════════════════════════════════════════════════════
    # v3 人类行为模拟（贝塞尔鼠标 + 高斯滚动 + 键盘打字）
    # ═══════════════════════════════════════════════════════════════════════

    @staticmethod
    def gauss_delay(mi: float, ma: float) -> float:
        """高斯分布延迟。"""
        mid = (mi + ma) / 2
        return max(mi, min(ma, random.gauss(mid, (ma - mi) / 4)))

    def human_mouse(self):
        """随机贝塞尔鼠标移动（15-30步）。"""
        try:
            if self._page:
                self._page.mouse.move(
                    random.randint(200, 1200),
                    random.randint(200, 700),
                    steps=random.randint(15, 30),
                )
        except Exception:
            pass

    def human_scroll(self):
        """模拟人类滚动：随机步长，12-15%概率回滚。"""
        if not self._page:
            return
        try:
            for _ in range(random.randint(1, 3)):
                dy = random.randint(100, 400)
                if random.random() < 0.12:
                    dy = -random.randint(50, 150)  # 回滚
                self._page.evaluate(f"window.scrollBy(0, {dy})")
                time.sleep(random.uniform(0.2, 0.6))
        except Exception:
            pass

    def browse_homepage(self):
        """偶尔（~10%概率）模拟浏览首页行为。"""
        if random.random() < 0.1 and self._page:
            try:
                self.human_mouse()
                self._page.goto(self.HOME_URL, wait_until="domcontentloaded", timeout=15000)
                self.human_scroll()
                self.human_mouse()
                time.sleep(BaseSpider.gauss_delay(1, 4))
            except Exception:
                pass

    # ═══════════════════════════════════════════════════════════════════════
    # Cookie 管理
    # ═══════════════════════════════════════════════════════════════════════

    @classmethod
    def load_cookies(cls, platform: str = None) -> list[dict] | None:
        """加载平台 Cookie：优先环境变量 BGI_{PLATFORM}_COOKIES，文件兜底。"""
        p = platform or cls.PLATFORM
        # 1. 环境变量
        env_val = getattr(settings, f"{p}_cookies", "")
        if env_val:
            try:
                cookies = json.loads(env_val)
                if isinstance(cookies, list) and cookies:
                    return cookies
            except json.JSONDecodeError:
                pass
        # 2. 文件兜底
        cookie_file = os.path.join(
            settings.raw_data_dir.as_posix(), f"{p}_cookies.json"
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

    def _inject_cookies(self):
        """注入 Cookie（标准化 EditThisCookie 格式后通过 Playwright API 注入）。"""
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
                # 可选属性
                for src, dst in [("httpOnly", "httpOnly"), ("secure", "secure")]:
                    if c.get(src):
                        c_clean[dst] = True
                # sameSite: no_restriction/unspecified → None, others pass through
                ss = c.get("sameSite")
                if ss == "no_restriction":
                    c_clean["sameSite"] = "None"
                elif ss in ("Strict", "Lax", "None"):
                    c_clean["sameSite"] = ss
                # expires: convert expirationDate (unix timestamp) to float
                if c.get("expirationDate"):
                    c_clean["expires"] = float(c["expirationDate"])
                clean.append(c_clean)
            self._context.add_cookies(clean)
            self._logged_in = True
            logger.info(f"已注入 {len(clean)} 条 {self.PLATFORM} Cookie")
        except Exception as exc:
            logger.warning(f"Cookie 注入失败 ({len(cookies)} cookies): {exc}")

    # ═══════════════════════════════════════════════════════════════════════
    # 请求拦截（block 图片/CSS/字体 — 大幅加速）
    # ═══════════════════════════════════════════════════════════════════════

    def _setup_request_interception(self):
        """拦截非必要资源请求，只保留 HTML/JS/API。"""
        if not self._page:
            return
        self._page.route("**/*", lambda route: self._on_route(route))

    def _on_route(self, route):
        """路由处理器 — block 图片/CSS/字体。"""
        if route.request.resource_type in {"image", "stylesheet", "font", "media"}:
            route.abort()
        else:
            route.continue_()

    # ═══════════════════════════════════════════════════════════════════════
    # 页面加载（带重试）
    # ═══════════════════════════════════════════════════════════════════════

    def fetch_page(
        self, url: str, wait_selector: str = None,
        wait_timeout: int = 15000, referer: str = None,
    ) -> str | None:
        """加载页面并返回 HTML（支持重试）。

        Args:
            url: 目标 URL
            wait_selector: 等待的 CSS 选择器
            wait_timeout: 等待超时毫秒
            referer: Referer 头

        Returns:
            HTML 字符串，失败返回 None
        """
        last_error = None
        for attempt in range(1, self.MAX_RETRIES + 1):
            try:
                goto_opts = {"wait_until": "domcontentloaded", "timeout": 30000}
                if referer:
                    goto_opts["referer"] = referer
                self._page.goto(url, **goto_opts)

                # 等待关键元素渲染
                if wait_selector:
                    try:
                        self._page.wait_for_selector(
                            wait_selector, timeout=wait_timeout,
                        )
                    except Exception:
                        pass  # 选择器不是硬性要求

                time.sleep(1.5)
                self.stats["pages_loaded"] += 1

                # 检查是否被拦截
                if self._is_blocked():
                    logger.warning(f"  检测到拦截页面 (attempt {attempt})")
                    if attempt < self.MAX_RETRIES:
                        time.sleep(self.RETRY_BASE_DELAY * attempt)
                        continue
                    return None

                return self._page.content()

            except Exception as exc:
                last_error = exc
                self.stats["retries"] += 1
                logger.warning(f"  页面加载失败 (attempt {attempt}/{self.MAX_RETRIES}): {exc}")
                if attempt < self.MAX_RETRIES:
                    time.sleep(self.RETRY_BASE_DELAY * attempt)

        self.stats["errors"] += 1
        logger.error(f"  页面加载最终失败: {last_error}")
        return None

    def _is_blocked(self) -> bool:
        """检查当前页面是否被反爬拦截（子类可重写）。"""
        if not self._page:
            return False
        try:
            title = self._page.title()
            blocked_keywords = ["验证", "安全验证", "登录", "signin", "captcha", "拦截"]
            return any(kw in title for kw in blocked_keywords)
        except Exception:
            return False

    # ═══════════════════════════════════════════════════════════════════════
    # 增量采集
    # ═══════════════════════════════════════════════════════════════════════

    def _load_incremental_state(self):
        """从文件加载增量采集时间戳。"""
        if os.path.exists(self._incremental_file):
            try:
                with open(self._incremental_file, "r", encoding="utf-8") as f:
                    raw = json.load(f)
                for k, v in raw.items():
                    self._last_collected_at[k] = datetime.fromisoformat(v)
                if self._last_collected_at:
                    logger.info(f"已加载 {len(self._last_collected_at)} 个关键词的增量状态")
            except Exception as exc:
                logger.warning(f"加载增量状态失败: {exc}")

    def _save_incremental_state(self):
        """持久化增量采集时间戳。"""
        try:
            raw = {k: v.isoformat() for k, v in self._last_collected_at.items()}
            with open(self._incremental_file, "w", encoding="utf-8") as f:
                json.dump(raw, f, ensure_ascii=False, indent=2)
        except Exception as exc:
            logger.warning(f"保存增量状态失败: {exc}")

    def _update_last_collected(self, keyword: str, dt: datetime):
        """更新某关键词的最后采集时间。"""
        if keyword not in self._last_collected_at or dt > self._last_collected_at[keyword]:
            self._last_collected_at[keyword] = dt

    def _should_skip(self, keyword: str, item_time: datetime | None) -> bool:
        """增量模式：判断是否跳过旧数据。"""
        if not item_time:
            return False
        last_ts = self._last_collected_at.get(keyword)
        return last_ts is not None and item_time <= last_ts

    # ═══════════════════════════════════════════════════════════════════════
    # 断点续采
    # ═══════════════════════════════════════════════════════════════════════

    def _load_checkpoint(self):
        """加载断点续采状态。"""
        if os.path.exists(self._checkpoint_file):
            try:
                with open(self._checkpoint_file, "r", encoding="utf-8") as f:
                    self._checkpoint = json.load(f)
                if self._checkpoint:
                    logger.info(f"检测到断点: {len(self._checkpoint)} 个关键词有未完成任务")
            except Exception:
                pass

    def _save_checkpoint(self):
        """保存断点续采状态。"""
        try:
            with open(self._checkpoint_file, "w", encoding="utf-8") as f:
                json.dump(self._checkpoint, f, ensure_ascii=False, indent=2)
        except Exception:
            pass

    def _update_checkpoint(self, keyword: str, page: int, collected: int):
        """更新断点信息。"""
        self._checkpoint[keyword] = {"page": page, "collected_total": collected}
        # 每 5 页保存一次
        if page % 5 == 0:
            self._save_checkpoint()

    def _clear_checkpoint(self, keyword: str):
        """清除某关键词的断点（表示该词已完成）。"""
        self._checkpoint.pop(keyword, None)
        self._save_checkpoint()

    # ═══════════════════════════════════════════════════════════════════════
    # 自适应等待间隔
    # ═══════════════════════════════════════════════════════════════════════

    def _adaptive_delay(self, consecutive_empty: int = 0):
        """自适应等待：空结果越多等越久（反爬退避）。"""
        base = self.MIN_DELAY + random.random() * (self.MAX_DELAY - self.MIN_DELAY)
        if consecutive_empty >= self.BACKOFF_THRESHOLD:
            base += min(consecutive_empty * 2, 30)  # 最多加到 30 秒
        time.sleep(base)

    # ═══════════════════════════════════════════════════════════════════════
    # HTML 工具方法
    # ═══════════════════════════════════════════════════════════════════════

    @staticmethod
    def clean_html(text: str) -> str:
        """清理 HTML 标签，保留文本和关键结构。"""
        if not text:
            return ""
        text = re.sub(r"<br\s*/?>", "\n", text, flags=re.I)
        text = re.sub(r"</p>", "\n", text, flags=re.I)
        text = re.sub(r"</div>", "\n", text, flags=re.I)
        # 图片表情 alt 文本
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
        text = re.sub(r"\s+", " ", text)
        return text.strip()

    @staticmethod
    def contains_emoji(text: str) -> bool:
        """检测文本是否包含 Unicode emoji。"""
        emoji_pattern = re.compile(
            "[\U0001F600-\U0001F64F"
            "\U0001F300-\U0001F5FF"
            "\U0001F680-\U0001F6FF"
            "\U0001F1E0-\U0001F1FF"
            "\U00002600-\U000027BF]",
            flags=re.UNICODE,
        )
        return bool(emoji_pattern.search(text))

    # ═══════════════════════════════════════════════════════════════════════
    # 交互式登录（弹出浏览器 → 手动登录 → 自动保存 Cookie）
    # ═══════════════════════════════════════════════════════════════════════

    @classmethod
    def interactive_login(cls, headless: bool = False):
        """弹出浏览器让用户手动登录，登录完成后按 Enter 自动保存 Cookie。

        用法:
            python -c "from collectors.spiders.weibo_spider import WeiboSearchSpider; WeiboSearchSpider.interactive_login()"

        步骤:
            1. 打开浏览器 → 访问平台首页
            2. 用户在浏览器中手动完成登录（扫码/密码/验证码）
            3. 回到终端按 Enter 确认
            4. 自动保存 Cookie 到 data/raw/{platform}_cookies.json

        Args:
            headless: 是否无头模式（默认 False，必须可见才能手动登录）
        """
        platform = cls.PLATFORM
        home_url = cls.HOME_URL
        cookie_file = os.path.join(
            settings.raw_data_dir.as_posix(), f"{platform}_cookies.json"
        )

        logger.info("=" * 60)
        logger.info(f"  {platform} 交互式登录")
        logger.info("=" * 60)
        logger.info("")
        logger.info(f"  即将打开浏览器访问: {home_url}")
        logger.info(f"  请在浏览器中手动完成登录（扫码/密码/验证码均可）")
        logger.info(f"  登录成功后，回到此处按 Enter 键")
        logger.info(f"  Cookie 将自动保存到: {cookie_file}")
        logger.info("")

        playwright = None
        browser = None
        context = None
        page = None

        try:
            playwright = sync_playwright().start()
            browser = playwright.chromium.launch(
                headless=headless,
                args=[
                    "--disable-blink-features=AutomationControlled",
                    "--no-sandbox",
                    "--disable-dev-shm-usage",
                ],
            )
            context = browser.new_context(
                user_agent=random_ua(),
                locale="zh-CN",
                viewport={"width": 1366, "height": 768},
            )

            # stealth
            page = context.new_page()
            try:
                from playwright_stealth import stealth_sync
                stealth_sync(page)
            except ImportError:
                page.add_init_script("""
                    Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
                """)

            # 导航到首页
            logger.info(f"  正在访问 {home_url} ...")
            try:
                page.goto(home_url, wait_until="domcontentloaded", timeout=30000)
            except Exception:
                logger.warning(f"  首页加载超时，但浏览器窗口应该已打开，请继续手动操作")

            logger.info("")
            logger.info("  ╔══════════════════════════════════════════╗")
            logger.info("  ║  请在浏览器中完成登录                   ║")
            logger.info("  ║  登录成功后 → 回到这里按 Enter 确认     ║")
            logger.info("  ╚══════════════════════════════════════════╝")
            logger.info("")

            # 等待用户确认
            input("  按 Enter 保存 Cookie...")

            # 提取 Cookie
            cookies = context.cookies()
            if not cookies:
                logger.warning("  未提取到任何 Cookie！请确认是否已登录。")
                return False

            # 保存到文件
            os.makedirs(os.path.dirname(cookie_file), exist_ok=True)
            with open(cookie_file, "w", encoding="utf-8") as f:
                json.dump(cookies, f, ensure_ascii=False, indent=2)

            logger.info(f"  ✅ 成功保存 {len(cookies)} 条 Cookie → {cookie_file}")

            # 显示关键 Cookie 名称供确认
            key_names = {
                # 微博 / 贴吧 / 知乎 / 小红书 / 抖音
                "SUB", "BDUSS", "z_c0", "d_c0", "web_session", "a1",
                "s_v_web_id", "passport_csrf_token", "ttwid",
                # 闲鱼 / 阿里系
                "_m_h5_tk", "_m_h5_tk_enc", "cookie2", "_tb_token_",
                "isg", "xlly_s", "unb", "cna", "sgcookie",
            }
            found_keys = [c["name"] for c in cookies if c["name"] in key_names]
            if found_keys:
                logger.info(f"  🔑 检测到关键 Cookie: {', '.join(found_keys)}")
            else:
                logger.warning("  ⚠️  未检测到常见的关键 Cookie，登录可能未完成")

            return True

        except Exception as exc:
            logger.error(f"  交互式登录失败: {exc}")
            return False

        finally:
            if page:
                page.close()
            if context:
                context.close()
            if browser:
                browser.close()
            if playwright:
                playwright.stop()

    # ═══════════════════════════════════════════════════════════════════════
    # 工具方法
    # ═══════════════════════════════════════════════════════════════════════

    @staticmethod
    def ts_to_datetime(ts: int) -> datetime:
        """Unix 时间戳转 datetime。"""
        if ts and ts > 0:
            return datetime.utcfromtimestamp(ts)
        return datetime.utcnow()

    def screenshot(self, path: str = "debug.png"):
        """调试用：保存当前页面截图。"""
        if self._page:
            full_path = os.path.join(settings.raw_data_dir.as_posix(), path)
            self._page.screenshot(path=full_path, full_page=True)
            logger.info(f"截图已保存: {full_path}")

    def __enter__(self):
        self.start()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()

    # ═══════════════════════════════════════════════════════════════════════
    # 子类必须实现
    # ═══════════════════════════════════════════════════════════════════════

    @abstractmethod
    def search_and_parse(
        self, keyword: str, max_pages: int = 3, **kwargs
    ) -> list:
        """搜索关键词并返回解析后的结构化数据列表。"""
        ...
