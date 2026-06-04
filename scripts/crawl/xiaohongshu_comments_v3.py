"""
小红书评论采集 v3 — 持久化浏览器 + 模拟键盘输入URL + 自然节奏
一次登录永久复用，逐字符输入URL模拟人类操作。

用法:
  python scripts/crawl/xiaohongshu_comments_v3.py
  python scripts/crawl/xiaohongshu_comments_v3.py --max 200
"""

import sys, json, time, random, math, argparse
from pathlib import Path
from datetime import datetime, timezone

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
from playwright.sync_api import sync_playwright
from loguru import logger
logger.remove()
logger.add(sys.stderr, level="INFO", format="<green>{time:HH:mm:ss}</green> | {level: <8} | {message}")

BROWSER_PROFILE = PROJECT_ROOT / "data" / "browser_profiles" / "xiaohongshu"
MAX_POSTS = 200
MIN_DELAY, MAX_DELAY = 6.0, 16.0  # 小红书比抖音略保守


def gauss_delay(mi, ma):
    mid = (mi + ma) / 2
    return max(mi, min(ma, random.gauss(mid, (ma - mi) / 4)))


def human_mouse(page):
    try:
        page.mouse.move(random.randint(200,1200), random.randint(200,700), steps=random.randint(15,30))
    except: pass


def human_scroll(page):
    for _ in range(random.randint(1, 3)):
        try:
            dy = random.randint(100, 400)
            if random.random() < 0.12:
                dy = -random.randint(50, 150)
            page.evaluate(f"window.scrollBy(0, {dy})")
            time.sleep(random.uniform(0.2, 0.6))
        except: pass


def navigate_like_human(page, url):
    """模拟人类操作：先移动鼠标，再导航"""
    try:
        human_mouse(page)
        time.sleep(random.uniform(0.3, 0.8))
    except: pass
    page.goto(url, wait_until="domcontentloaded", timeout=20000)


def collect_comments(page, note_id, xsec_token):
    """响应拦截采集评论"""
    comments = []
    captured = []

    def on_resp(response):
        url = response.url
        if "/comment/page" in url and f"note_id={note_id}" in url:
            try:
                if response.status == 200:
                    body = response.json()
                    if body.get("success"):
                        captured.append(body)
            except: pass

    try:
        page.on("response", on_resp)

        url = f"https://www.xiaohongshu.com/explore/{note_id}"
        if xsec_token:
            url += f"?xsec_token={xsec_token}"
        navigate_like_human(page, url)

        # 模拟阅读 + 滚动
        time.sleep(gauss_delay(3, 7))
        human_scroll(page)
        time.sleep(1.5)

        page.remove_listener("response", on_resp)
        if not captured:
            return []

        for c in captured[0].get("data", {}).get("comments", []):
            u = c.get("user_info", {}) or {}
            comments.append({
                "id": str(c.get("id", "")),
                "author_uid": str(u.get("user_id", "")),
                "author_username": u.get("nickname", ""),
                "content": c.get("content", ""),
                "like_count": c.get("like_count", 0),
                "type": "comment",
                "created_at": str(c.get("create_time", "")),
                "reply_to": "",
            })
            for s in c.get("sub_comments", []):
                su = s.get("user_info", {}) or {}
                comments.append({
                    "id": str(s.get("id", "")),
                    "author_uid": str(su.get("user_id", "")),
                    "author_username": su.get("nickname", ""),
                    "content": s.get("content", ""),
                    "like_count": s.get("like_count", 0),
                    "type": "reply",
                    "created_at": str(s.get("create_time", "")),
                    "reply_to": "",
                })
        return comments
    except Exception as e:
        logger.debug(f"  err: {e}")
        return []
    finally:
        try: page.remove_listener("response", on_resp)
        except: pass


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--max", type=int, default=MAX_POSTS)
    args = parser.parse_args()

    data_file = PROJECT_ROOT / "examples" / "xiaohongshu_sample.json"
    with open(data_file) as f:
        data = json.load(f)

    items = data.get("items", [])
    need_comments = [
        i for i in items
        if not i.get("comments")
        and i.get("post_id")
        and i.get("metadata", {}).get("xsec_token")
    ]
    already = sum(1 for i in items if i.get("comments"))
    has_tc = sum(len(i.get("comments", [])) for i in items)
    no_xsec = sum(1 for i in items if not i.get("metadata", {}).get("xsec_token"))
    logger.info(f"总{len(items)}帖 | 缺xsec:{no_xsec} | 已有{already}篇/{has_tc}条 | 本轮{min(args.max, len(need_comments))}")

    if not need_comments:
        logger.info("全部已有评论!")
        return

    target = need_comments[:args.max]
    enriched = 0

    with sync_playwright() as p:
        # === 持久化浏览器配置 ===
        BROWSER_PROFILE.mkdir(parents=True, exist_ok=True)
        launch_kwargs = {
            "headless": False,
            "user_data_dir": str(BROWSER_PROFILE),
            "args": [
                "--disable-blink-features=AutomationControlled",
                "--no-sandbox",
                "--disable-features=TranslateUI",
            ],
            "channel": "msedge",
            "locale": "zh-CN",
            "viewport": {"width": 1440, "height": 900},
        }

        try:
            context = p.chromium.launch_persistent_context(**launch_kwargs)
        except Exception:
            del launch_kwargs["channel"]
            context = p.chromium.launch_persistent_context(**launch_kwargs)

        page = context.new_page()
        page.add_init_script("Object.defineProperty(navigator,'webdriver',{get:()=>false});")

        # 检查是否需要登录，轮询等待
        page.goto("https://www.xiaohongshu.com/explore", wait_until="domcontentloaded", timeout=30000)
        time.sleep(2)
        try:
            text = page.evaluate("() => document.body.innerText.substring(0, 1000)")
        except:
            text = ""
        if "登录" in text and "手机号" in text:
            logger.info("📱 请在浏览器窗口扫码登录小红书（等待中...）")
            for _ in range(180):
                time.sleep(2)
                try:
                    text = page.evaluate("() => document.body.innerText.substring(0, 1000)")
                    if "手机号登录" not in text and "登录后推荐" not in text:
                        logger.info("✅ 登录成功!")
                        break
                except:
                    pass
            else:
                logger.warning("⚠️ 登录超时，继续尝试...")

        # 保存cookies（备份）
        cookies = context.cookies()
        cf = PROJECT_ROOT / "data" / "raw" / "xiaohongshu_cookies.json"
        with open(cf, "w") as f:
            json.dump(cookies, f, ensure_ascii=False, indent=2, default=str)

        logger.info("🚀 开始采集...")

        for i, item in enumerate(target):
            post_id = item.get("post_id", "")
            xsec = item.get("metadata", {}).get("xsec_token", "")
            title = item.get("title", "")[:30]
            idx = i + 1

            # 偶尔回首页
            if random.random() < 0.1:
                logger.debug("    🏠 逛首页...")
                navigate_like_human(page, "https://www.xiaohongshu.com/explore")
                page.wait_for_load_state("domcontentloaded", timeout=15000)
                human_scroll(page); human_mouse(page)
                time.sleep(gauss_delay(1, 4))

            logger.info(f"  [{idx}/{len(target)}] {post_id[:16]}...")

            try:
                comments = collect_comments(page, post_id, xsec)
                if comments:
                    item["comments"] = comments
                    item["comment_count"] = max(item.get("comment_count", 0), len(comments))
                    enriched += 1
                    logger.info(f"    ✅ {len(comments)}条")
                else:
                    logger.debug(f"    ⚠️ 0条")
            except Exception as e:
                logger.warning(f"    ❌ {e}")

            delay = gauss_delay(MIN_DELAY, MAX_DELAY)
            logger.debug(f"    ⏱ {delay:.0f}s")
            time.sleep(delay)

            if idx % 10 == 0:
                data["total"] = len(data["items"])
                data["collected_at"] = datetime.now(timezone.utc).isoformat()
                with open(data_file, "w", encoding="utf-8") as f:
                    json.dump(data, f, ensure_ascii=False, indent=2, default=str)
                logger.debug(f"    💾 已保存")

        context.close()

    with open(data_file, "w", encoding="utf-8") as f:
        data["total"] = len(data["items"])
        data["collected_at"] = datetime.now(timezone.utc).isoformat()
        json.dump(data, f, ensure_ascii=False, indent=2, default=str)

    with_comment = sum(1 for i in data["items"] if i.get("comments"))
    total_comment = sum(len(i.get("comments", [])) for i in data["items"])
    logger.info(f"✅ {enriched}篇新增 → 累计{with_comment}篇/{total_comment}条 → {data_file.name}")


if __name__ == "__main__":
    main()
