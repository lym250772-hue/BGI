"""
抖音 Token 提取脚本 — 弹出浏览器 → 手动登录 → 模拟搜索 → 自动提取 msToken/webid

用法:
    python scripts/crawl/douyin_get_tokens.py

提取后保存到 data/raw/douyin_tokens.json，供 Spider 使用。
"""

import sys
import json
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from playwright.sync_api import sync_playwright
from loguru import logger


def main():
    TOKEN_FILE = PROJECT_ROOT / "data" / "raw" / "douyin_tokens.json"

    with sync_playwright() as p:
        # 使用系统 Chrome 浏览器（带登录态）
        try:
            browser = p.chromium.launch(
                headless=False,
                channel="chrome",  # 用系统 Chrome（有登录态）
                args=["--disable-blink-features=AutomationControlled"],
            )
        except Exception:
            logger.warning("系统 Chrome 不可用，尝试 Edge...")
            browser = p.chromium.launch(
                headless=False,
                channel="msedge",
                args=["--disable-blink-features=AutomationControlled"],
            )

        context = browser.new_context(
            locale="zh-CN",
            viewport={"width": 1440, "height": 900},
        )
        page = context.new_page()
        page.add_init_script(
            "Object.defineProperty(navigator, 'webdriver', {get: () => false});"
        )

        # ── 步骤1: 引导用户登录 ─────────────────────────────────────────
        print("\n" + "=" * 60)
        print("📱 请在浏览器中完成以下操作：")
        print("   1. 访问 douyin.com 并登录（如未登录）")
        print("   2. 如果有验证码/滑块，手动完成")
        print("   3. 确认已登录后，回到终端按 Enter")
        print("=" * 60)

        page.goto("https://www.douyin.com", wait_until="domcontentloaded", timeout=30000)
        input("\n✅ 登录完成后按 Enter 继续...")

        # ── 步骤2: 加载已有 Cookie ───────────────────────────────────────
        cookie_file = PROJECT_ROOT / "data" / "raw" / "douyin_cookies.json"
        if cookie_file.exists():
            with open(cookie_file, encoding="utf-8") as f:
                saved_cookies = json.load(f)
            clean_cookies = []
            for c in saved_cookies:
                clean = {
                    "name": c.get("name", ""),
                    "value": str(c.get("value", "")),
                    "domain": c.get("domain", ""),
                    "path": c.get("path", "/"),
                }
                if clean["name"] and clean["domain"]:
                    clean_cookies.append(clean)
            if clean_cookies:
                context.add_cookies(clean_cookies)
                logger.info(f"已注入 {len(clean_cookies)} 条保存的 Cookie")

        # ── 步骤3: 提取 webid + msToken ───────────────────────────────
        captured_webid = []
        captured_msToken = []

        def on_request(request):
            url = request.url
            if "webid=" in url and "douyin.com" in url and not captured_webid:
                import re
                m = re.search(r"webid=(\d+)", url)
                if m:
                    captured_webid.append(m.group(1))
            if "msToken=" in url and not captured_msToken:
                import re
                m = re.search(r"msToken=([^&]+)", url)
                if m:
                    captured_msToken.append(m.group(1))

        page.on("request", on_request)

        # ── 步骤4: 模拟搜索触发 API 请求 ─────────────────────────────
        print("\n🔍 模拟搜索以触发 API 请求（提取 msToken）...")

        # 先导航到 jingxuan
        try:
            page.goto("https://www.douyin.com/jingxuan", wait_until="domcontentloaded", timeout=15000)
            time.sleep(3)
        except Exception:
            pass

        # 移除可能的弹窗
        page.evaluate("""
        () => {
            var d = document.getElementById('trust-logout-dialog');
            if (d) d.remove();
            document.querySelectorAll('[class*="mask"], [class*="overlay"]')
                .forEach(function(e) { e.remove(); });
        }
        """)

        # 点击搜索框 → 输入 → 回车
        try:
            page.locator("input").first.click(timeout=5000)
            logger.info("  已点击搜索框")
        except Exception:
            page.mouse.click(700, 30)
            logger.info("  鼠标点击搜索框（兜底）")

        time.sleep(1)
        page.keyboard.type("测试", delay=150)
        time.sleep(0.3)
        page.keyboard.press("Enter")
        logger.info("  已按下 Enter，等待搜索结果...")

        # 等待 API 请求
        for i in range(15):
            time.sleep(1)
            if captured_msToken and captured_webid:
                break

        # 也尝试直接导航到用户页面触发 API
        if not captured_webid or not captured_msToken:
            logger.info("搜索未触发足够 API，尝试导航到用户页面...")
            page.goto(
                "https://www.douyin.com/user/MS4wLjABAAAAEpmH344CkCw2M58T33Q8TuFpdvJsOyaZcbWxAMc6H03wOVFf1Ow4mPP94TDUS4Us",
                wait_until="domcontentloaded", timeout=15000,
            )
            for i in range(10):
                time.sleep(1)
                if captured_msToken and captured_webid:
                    break

        # ── 步骤5: 保存结果 ───────────────────────────────────────────
        current_cookies = context.cookies()
        result = {
            "webid": captured_webid[0] if captured_webid else "",
            "msToken": captured_msToken[0] if captured_msToken else "",
            "cookies": current_cookies,
            "extracted_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        }

        TOKEN_FILE.parent.mkdir(parents=True, exist_ok=True)
        with open(TOKEN_FILE, "w", encoding="utf-8") as f:
            json.dump(result, f, ensure_ascii=False, indent=2, default=str)

        # 同时更新 Cookie 文件
        with open(cookie_file, "w", encoding="utf-8") as f:
            json.dump(current_cookies, f, ensure_ascii=False, indent=2, default=str)

        print("\n" + "=" * 60)
        print("📊 提取结果:")
        print(f"   webid:   {result['webid']}")
        print(f"   msToken: {result['msToken'][:60]}..." if result['msToken'] else "   msToken: ❌ 未提取到")
        print(f"   cookies: {len(result['cookies'])} 条")
        print(f"   已保存: {TOKEN_FILE}")
        print("=" * 60)

        if not result["msToken"]:
            print("\n⚠️ 未提取到 msToken。可能原因:")
            print("   1. 搜索页面未触发 search API")
            print("   2. 需要先在搜索页面进行更多交互")
            print("   3. 可尝试: 在浏览器中手动搜索，观察 DevTools Network 中的 msToken")
            print("\n💡 手动获取方法:")
            print("   1. 保持浏览器打开 → F12 → Network 标签")
            print("   2. 在 douyin.com 搜索关键词")
            print("   3. 找到 /aweme/v1/web/general/search/single/ 请求")
            print("   4. 复制 URL 中 msToken= 的值")
            print(f"   5. 写入 {TOKEN_FILE} 的 msToken 字段")

        browser.close()


if __name__ == "__main__":
    main()
