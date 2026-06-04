"""小红书评论调试 v2 — 处理页面重定向"""
import sys, json, time, asyncio
from pathlib import Path
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
from playwright.sync_api import sync_playwright

data = json.load(open(PROJECT_ROOT / "examples" / "xiaohongshu_sample.json"))
item = next(i for i in data["items"] if i.get("metadata", {}).get("xsec_token"))
nid = item["post_id"]
xsec = item["metadata"]["xsec_token"]
print(f"测试: {nid} 标题: {item.get('title','')[:40]}")

with sync_playwright() as p:
    browser = p.chromium.launch(headless=False,
        args=["--disable-blink-features=AutomationControlled", "--no-sandbox"])
    ctx = browser.new_context(locale="zh-CN", viewport={"width":1440,"height":900})
    page = ctx.new_page()

    # 加载 cookies
    cf = PROJECT_ROOT / "data" / "raw" / "xiaohongshu_cookies.json"
    if cf.exists():
        cookies = json.load(open(cf))
        clean = [{"name":c["name"],"value":str(c["value"]),"domain":c.get("domain",""),"path":c.get("path","/")} for c in cookies if c.get("name") and c.get("domain")]
        if clean: ctx.add_cookies(clean)

    # 收集所有API请求
    api_calls = []
    def on_resp(response):
        url = response.url
        if any(k in url for k in ["comment", "api/sns", "note"]):
            api_calls.append(f"{response.status} {url[:150]}")
    page.on("response", on_resp)

    # Step 1: 打开首页检查登录
    print("\n=== Step 1: 检查登录 ===")
    page.goto("https://www.xiaohongshu.com/explore", wait_until="domcontentloaded", timeout=20000)
    time.sleep(3)

    # 检查页面内容判断登录
    html_snippet = page.evaluate("() => document.body.innerText.substring(0, 500)")
    print(f"页面内容: {html_snippet[:200]}")

    # Step 2: 打开笔记
    print(f"\n=== Step 2: 打开笔记 ===")
    url = f"https://www.xiaohongshu.com/explore/{nid}?xsec_token={xsec}"
    print(f"URL: {url[:120]}")

    try:
        page.goto(url, wait_until="domcontentloaded", timeout=25000)
    except Exception as e:
        print(f"goto异常: {e}")

    time.sleep(5)

    # 检查最终URL（可能重定向了）
    final_url = page.url
    print(f"最终URL: {final_url[:150]}")
    if "login" in final_url:
        print("❌ 被重定向到登录页！cookies无效")
    elif nid in final_url:
        print("✅ 成功打开笔记页")
    else:
        print(f"⚠️ URL变了: {final_url[:120]}")

    # 查看页面内容
    try:
        body = page.evaluate("() => document.body.innerText.substring(0, 500)")
        print(f"页面内容: {body[:300]}")
    except Exception as e:
        print(f"读取内容失败: {e}")

    # Step 3: 尝试滚动
    print(f"\n=== Step 3: 滚动触发评论 ===")
    for i in range(3):
        try:
            page.evaluate("window.scrollBy(0, 800)")
            time.sleep(2)
        except Exception as e:
            print(f"滚动{i}失败: {e}")
            break

    # Step 4: 查看捕获的API
    print(f"\n=== 捕获的API ({len(api_calls)}条) ===")
    for a in api_calls:
        print(f"  {a}")

    # Step 5: 手动fetch
    print(f"\n=== Step 5: 手动fetch评论API ===")
    try:
        result = page.evaluate("""
        async (note_id) => {
            try {
                const r = await fetch('/api/sns/web/v2/comment/page?note_id=' + note_id + '&cursor=&top_comment_id=&image_formats=jpg,webp,avif');
                const t = await r.text();
                return 'OK ' + r.status + ': ' + t.substring(0, 800);
            } catch(e) {
                return 'ERROR: ' + e.message;
            }
        }
        """, nid)
        print(f"结果: {result}")
    except Exception as e:
        print(f"Fetch失败: {e}")

    input("\n按Enter关闭浏览器...")
    browser.close()
