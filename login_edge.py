"""Edge 浏览器一键登录 — 逐平台打开 Edge，手动登录后按 Enter 保存 Cookie。
用法:
    python login_edge.py              # 登录全部平台
    python login_edge.py zhihu        # 只登录知乎
    python login_edge.py zhihu weibo  # 登录知乎+微博
"""
import json, os, sys
from loguru import logger
from playwright.sync_api import sync_playwright
from config.settings import settings

HOME_URLS = {
    "zhihu": "https://www.zhihu.com/signin",
    "weibo": "https://weibo.com",
    "tieba": "https://tieba.baidu.com/index.html",
    "douyin": "https://www.douyin.com",
    "xiaohongshu": "https://www.xiaohongshu.com",
}

KEY_COOKIES = {
    "zhihu": ["z_c0", "d_c0"],
    "weibo": ["SUB", "SUBP"],
    "tieba": ["BDUSS", "STOKEN"],
    "douyin": ["ttwid", "sessionid"],
    "xiaohongshu": ["a1", "web_session"],
}

# 要登录的平台
if len(sys.argv) > 1:
    platforms = [p for p in sys.argv[1:] if p in HOME_URLS]
else:
    platforms = list(HOME_URLS.keys())

print("=" * 55)
print("  BGI Edge 浏览器登录工具")
print("=" * 55)
print()
print(f"  将依次登录: {', '.join(platforms)}")
print(f"  每个平台登录完成后，回到此处按 Enter")
print()

for i, p in enumerate(platforms, 1):
    print(f"[{i}/{len(platforms)}] 正在打开 Edge → {HOME_URLS[p]} ...")
    cookie_file = os.path.join(settings.raw_data_dir.as_posix(), f"{p}_cookies.json")

    playwright = sync_playwright().start()
    browser = playwright.chromium.launch(
        channel="msedge",
        headless=False,
        args=["--disable-blink-features=AutomationControlled", "--no-sandbox"],
    )
    context = browser.new_context(locale="zh-CN", viewport={"width": 1366, "height": 768})
    page = context.new_page()

    # Stealth
    try:
        from playwright_stealth import stealth_sync
        stealth_sync(page)
    except ImportError:
        page.add_init_script(
            "Object.defineProperty(navigator, 'webdriver', {get: () => undefined});"
        )

    page.goto(HOME_URLS[p], wait_until="domcontentloaded", timeout=30000)

    input(f"  [{p}] 请在 Edge 中完成登录，完成后按 Enter 保存 Cookie...")

    cookies = context.cookies()
    os.makedirs(os.path.dirname(cookie_file), exist_ok=True)
    with open(cookie_file, "w", encoding="utf-8") as f:
        json.dump(cookies, f, ensure_ascii=False, indent=2)

    # 检查关键 Cookie
    found = [c["name"] for c in cookies if c["name"] in KEY_COOKIES.get(p, [])]
    if found:
        print(f"  [{p}] ✅ {len(cookies)} 条 Cookie 已保存 (关键: {', '.join(found)})")
    else:
        print(f"  [{p}] ⚠️ {len(cookies)} 条 Cookie 已保存 (未检测到关键Cookie，登录可能未完成)")

    page.close()
    context.close()
    browser.close()
    playwright.stop()
    print()

print("全部完成！现在可以运行采集命令:")
print("  python main.py collect -p zhihu -k '刷单' --max-pages 2")
print("  python main.py collect -p douyin -k '刷单' --max-pages 2")
print("  python main.py collect -p weibo -k '刷单' --max-pages 2")
print("  python main.py collect -p tieba -k '刷单' --max-pages 2")
