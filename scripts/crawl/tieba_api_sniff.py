"""
贴吧搜索 API 抓包脚本 — 拦截页面内部 API 调用，找出可用的 JSON 接口。
"""
import json
import sys
import time
from pathlib import Path

# 添加项目根目录
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from playwright.sync_api import sync_playwright


def main():
    # 加载 Cookie
    cookie_file = Path(__file__).resolve().parent.parent.parent / "data" / "raw" / "tieba_cookies.json"
    cookies = []
    if cookie_file.exists():
        with open(cookie_file, encoding="utf-8") as f:
            cookies = json.load(f)
        # Playwright 需要标准格式
        cookies = [
            {
                "name": c.get("name", ""),
                "value": str(c.get("value", "")),
                "domain": c.get("domain", ".baidu.com"),
                "path": c.get("path", "/"),
            }
            for c in cookies
            if c.get("name")
        ]
        print(f"✅ 已加载 {len(cookies)} 条 Cookie")
    else:
        print("⚠️ 无 Cookie 文件，可能无法获取结果")

    captured_apis = []  # 收集所有拦截到的 API 请求

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            viewport={"width": 1920, "height": 1080},
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        )
        if cookies:
            context.add_cookies(cookies)

        page = context.new_page()

        # ── 拦截网络请求 ──────────────────────────────────────────────────
        def on_response(response):
            url = response.url
            content_type = response.headers.get("content-type", "")
            status = response.status

            # 只关注可能包含数据的请求
            interesting = False
            if "tieba.baidu.com" in url or "tbapi.baidu.com" in url:
                if status == 200 and ("json" in content_type or "javascript" in content_type):
                    interesting = True
                # 也关注 XHR 请求
                if response.request.method == "POST" and "tieba" in url:
                    interesting = True

            if not interesting:
                return

            try:
                body = response.text()
                if len(body) > 50:
                    captured_apis.append({
                        "url": url[:200],
                        "method": response.request.method,
                        "content_type": content_type[:100],
                        "body_preview": body[:500],
                        "body_len": len(body),
                    })
            except Exception:
                pass

        page.on("response", on_response)

        # ── 执行搜索 ─────────────────────────────────────────────────────
        keyword = "刷单"
        search_url = f"https://tieba.baidu.com/f/search/res?ie=utf-8&kw=&qw={keyword}&pn=0"

        print(f"🔍 搜索: {keyword}")
        page.goto(search_url, wait_until="networkidle", timeout=30000)
        time.sleep(3)  # 等待 React 渲染完成 + 内部 API 调用

        # 滚动触发更多请求
        page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
        time.sleep(2)

        browser.close()

    # ── 分析结果 ─────────────────────────────────────────────────────────
    print(f"\n{'='*60}")
    print(f"📡 共拦截到 {len(captured_apis)} 个可疑 API 请求")
    print(f"{'='*60}")

    json_apis = []
    for api in captured_apis:
        url = api["url"]
        body = api["body_preview"]

        # 分类
        if api["content_type"] and "json" in api["content_type"]:
            label = "✅ JSON"
            json_apis.append(api)
        elif body.strip().startswith("{") or body.strip().startswith("["):
            label = "⚠️ 疑似JSON"
            json_apis.append(api)
        elif "callback" in url or "jsonp" in url:
            label = "📦 JSONP"
            json_apis.append(api)
        else:
            label = "❓ 其他"

        print(f"\n--- {label} [{api['method']}] (len={api['body_len']}) ---")
        print(f"URL: {api['url']}")
        print(f"Preview: {body[:300]}")

    # ── 如果是 JSON，尝试提取搜索 API ──────────────────────────────────
    print(f"\n{'='*60}")
    print(f"🎯 可用的 JSON API 候选 ({len(json_apis)} 个):")
    print(f"{'='*60}")

    search_candidates = []
    for api in json_apis:
        url = api["url"]
        body = api["body_preview"]
        # 检查是否包含搜索结果
        for keyword_check in ["thread", "post", "content", "title", "search", "result", "forum", "list"]:
            if keyword_check in body.lower() or keyword_check in url.lower():
                search_candidates.append(api)
                break

    if search_candidates:
        for api in search_candidates:
            print(f"\n🔑 {api['url']}")
            print(f"   方法: {api['method']}")
            print(f"   大小: {api['body_len']} bytes")
            try:
                data = json.loads(api["body_preview"])
                print(f"   结构: {json.dumps(list(data.keys()) if isinstance(data, dict) else f'array[{len(data)}]', ensure_ascii=False)}")
            except Exception:
                print(f"   预览: {api['body_preview'][:200]}")
    else:
        print("未找到明显的搜索 API，打印所有 JSON 响应:")
        for api in json_apis:
            print(f"\n{api['url']}")
            print(f"  {api['body_preview'][:300]}")

    # 保存到文件
    output = Path(__file__).resolve().parent.parent.parent / "data" / "raw" / "tieba_api_sniff.json"
    with open(output, "w", encoding="utf-8") as f:
        json.dump(captured_apis, f, ensure_ascii=False, indent=2, default=str)
    print(f"\n📁 完整结果已保存: {output}")


if __name__ == "__main__":
    main()
