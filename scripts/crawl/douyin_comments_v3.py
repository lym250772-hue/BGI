"""
抖音评论采集 v3 — 持久化浏览器 + 模拟键盘输入URL + 自然节奏
一次登录，永久复用。不用批次休息，模拟真人浏览节奏。

用法:
  python scripts/crawl/douyin_comments_v3.py
  python scripts/crawl/douyin_comments_v3.py --max 200
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

BROWSER_PROFILE = PROJECT_ROOT / "data" / "browser_profiles" / "douyin"
MAX_POSTS = 200
MIN_DELAY, MAX_DELAY = 5.0, 15.0  # 帖子间高斯延迟


def gauss_delay(mi, ma):
    mid = (mi + ma) / 2
    return max(mi, min(ma, random.gauss(mid, (ma - mi) / 4)))


def human_mouse(page):
    try:
        page.mouse.move(random.randint(200,1200), random.randint(200,700), steps=random.randint(15,30))
    except: pass


def human_scroll(page):
    """模拟人类滚动 - 有时回滚"""
    for _ in range(random.randint(1, 3)):
        try:
            dy = random.randint(100, 400)
            if random.random() < 0.15:
                dy = -random.randint(50, 150)  # 偶尔回滚
            page.evaluate(f"window.scrollBy(0, {dy})")
            time.sleep(random.uniform(0.2, 0.6))
        except: pass


def navigate_like_human(page, url):
    """模拟人类操作：先移动鼠标（模拟找按钮），再导航"""
    try:
        # 模拟操作前的小动作
        human_mouse(page)
        time.sleep(random.uniform(0.3, 0.8))
    except: pass
    # 直接用goto + referer（比键盘输入更可靠）
    page.goto(url, wait_until="domcontentloaded", timeout=25000,
              referer="https://www.douyin.com/")


def collect_comments(page, aweme_id):
    """响应拦截采集评论"""
    comments = []
    captured = []

    def on_resp(response):
        if "/comment/list/" in response.url and f"aweme_id={aweme_id}" in response.url:
            try:
                body = response.json()
                if body.get("comments"):
                    captured.append(body)
            except: pass

    try:
        page.on("response", on_resp)

        url = f"https://www.douyin.com/video/{aweme_id}"
        navigate_like_human(page, url)

        # 模拟观看
        watch_time = gauss_delay(3, 8)
        time.sleep(watch_time)
        human_scroll(page)
        time.sleep(1.5)

        page.remove_listener("response", on_resp)
        if not captured:
            logger.info(f"    ⚠️ 0条 (捕获{len(captured)}个响应)")
            return []

        for c in captured[0].get("comments", []):
            u = c.get("user", {}) or {}
            comments.append({
                "id": str(c.get("cid", "")),
                "author_uid": str(u.get("uid", "")),
                "author_username": u.get("nickname", ""),
                "content": c.get("text", ""),
                "like_count": c.get("digg_count", 0),
                "type": "comment",
                "created_at": str(c.get("create_time", "")),
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

    data_file = PROJECT_ROOT / "examples" / "douyin_sample.json"
    with open(data_file) as f:
        data = json.load(f)

    items = data.get("items", [])
    need_comments = [i for i in items if not i.get("comments") and i.get("post_id")]
    already = sum(1 for i in items if i.get("comments"))
    has_tc = sum(len(i.get("comments", [])) for i in items)
    logger.info(f"总{len(items)}帖 | 已有{already}篇/{has_tc}条 | 可采{len(need_comments)} | 本轮{min(args.max, len(need_comments))}")

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
            # Edge不可用时降级
            del launch_kwargs["channel"]
            context = p.chromium.launch_persistent_context(**launch_kwargs)

        page = context.new_page()
        page.add_init_script("Object.defineProperty(navigator,'webdriver',{get:()=>false});")

        # 检查是否需要登录，轮询等待
        page.goto("https://www.douyin.com/", wait_until="domcontentloaded", timeout=30000)
        time.sleep(2)
        try:
            text = page.evaluate("() => document.body.innerText.substring(0, 1000)")
        except:
            text = ""
        if "验证" in text or "登录" in text or "短信" in text:
            logger.info("📱 请在浏览器窗口登录抖音（等待中...）")
            for _ in range(180):  # 最多等3分钟
                time.sleep(2)
                try:
                    text = page.evaluate("() => document.body.innerText.substring(0, 1000)")
                    if "验证" not in text and "登录" not in text:
                        logger.info("✅ 登录成功!")
                        break
                except:
                    pass
            else:
                logger.warning("⚠️ 登录超时，继续尝试...")

        # 保存cookies（备份）
        cookies = context.cookies()
        cf = PROJECT_ROOT / "data" / "raw" / "douyin_cookies.json"
        with open(cf, "w") as f:
            json.dump(cookies, f, ensure_ascii=False, indent=2, default=str)

        logger.info("🚀 开始采集...")

        for i, item in enumerate(target):
            post_id = item.get("post_id", "")
            title = item.get("title", "")[:25]
            idx = i + 1

            # 偶尔回首页逛逛
            if random.random() < 0.08:
                logger.debug("    🏠 逛首页...")
                navigate_like_human(page, "https://www.douyin.com/")
                page.wait_for_load_state("domcontentloaded", timeout=15000)
                human_scroll(page); human_mouse(page)
                time.sleep(gauss_delay(1, 4))

            logger.info(f"  [{idx}/{len(target)}] {title}...")

            try:
                comments = collect_comments(page, post_id)
                if comments:
                    item["comments"] = comments
                    item["comment_count"] = max(item.get("comment_count", 0), len(comments))
                    enriched += 1
                    logger.info(f"    ✅ {len(comments)}条")
                else:
                    logger.debug(f"    ⚠️ 0条")
            except Exception as e:
                logger.warning(f"    ❌ {e}")

            # 自然间隔，无批处理
            delay = gauss_delay(MIN_DELAY, MAX_DELAY)
            logger.debug(f"    ⏱ {delay:.0f}s")
            time.sleep(delay)

            # 每10条保存
            if (idx) % 10 == 0:
                data["total"] = len(data["items"])
                data["collected_at"] = datetime.now(timezone.utc).isoformat()
                with open(data_file, "w", encoding="utf-8") as f:
                    json.dump(data, f, ensure_ascii=False, indent=2, default=str)
                logger.debug(f"    💾 已保存")

        context.close()

    # 最终保存
    with open(data_file, "w", encoding="utf-8") as f:
        data["total"] = len(data["items"])
        data["collected_at"] = datetime.now(timezone.utc).isoformat()
        json.dump(data, f, ensure_ascii=False, indent=2, default=str)

    with_comment = sum(1 for i in data["items"] if i.get("comments"))
    total_comment = sum(len(i.get("comments", [])) for i in data["items"])
    logger.info(f"✅ {enriched}篇新增 → 累计{with_comment}篇/{total_comment}条 → {data_file.name}")


if __name__ == "__main__":
    main()
