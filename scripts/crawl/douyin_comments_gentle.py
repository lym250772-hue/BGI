"""
抖音评论慢速采集 — 可见浏览器 + 极低频率 + 拟人行为
每 5 个视频休息 45-90 秒，视频间隔 6-14 秒高斯分布

用法:
  python scripts/crawl/douyin_comments_gentle.py
  python scripts/crawl/douyin_comments_gentle.py --max 50
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

MAX_POSTS = 80
BATCH_SIZE = 5            # 每批5个视频
BATCH_REST = (45, 90)     # 每批后休息 45-90 秒
POST_DELAY = (6, 14)      # 视频间隔 6-14 秒（高斯分布，均值~10s）


def gauss_delay(mi, ma):
    mid = (mi + ma) / 2
    return max(mi, min(ma, random.gauss(mid, (ma - mi) / 4)))


def human_mouse(page):
    try:
        page.mouse.move(
            random.randint(200, 1200),
            random.randint(200, 700),
            steps=random.randint(15, 30)
        )
    except:
        pass


def human_scroll(page):
    total = random.randint(200, 500)
    steps = random.randint(2, 5)
    for _ in range(steps):
        page.evaluate(f"window.scrollBy({random.randint(-15,15)}, {total//steps + random.randint(-20,30)})")
        time.sleep(random.uniform(0.15, 0.4))


def wait_for_login(page, timeout=120):
    """等待用户在可见浏览器中登录"""
    logger.info("⏳ 请在浏览器中登录抖音...")
    start = time.time()
    while time.time() - start < timeout:
        try:
            cookies = page.context.cookies()
            for c in cookies:
                if c.get("name") in ("sso_uid_tt", "sessionid_ss") and c.get("value"):
                    logger.info("✅ 检测到登录状态")
                    return True
        except:
            pass
        time.sleep(2)
    logger.warning("⚠️ 超时，未检测到登录，尝试继续...")
    return False


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
            except:
                pass

    try:
        page.on("response", on_resp)
        page.goto(f"https://www.douyin.com/video/{aweme_id}",
                  wait_until="domcontentloaded", timeout=25000,
                  referer="https://www.douyin.com/")
        time.sleep(gauss_delay(4, 7))
        human_scroll(page)
        page.remove_listener("response", on_resp)

        if not captured:
            return []

        for c in captured[0].get("comments", []):
            u = c.get("user", {}) or {}
            comments.append({
                "id": str(c.get("cid", "")),
                "author_uid": str(u.get("uid", "")),
                "author_username": u.get("nickname", ""),
                "content": c.get("text", ""),
                "like_count": c.get("digg_count", 0),
                "reply_count": c.get("reply_comment_total", 0),
                "type": "comment",
                "created_at": str(c.get("create_time", "")),
                "reply_to": "",
            })
        return comments
    except Exception as e:
        logger.debug(f"  err {aweme_id[:20]}: {e}")
        return []
    finally:
        try:
            page.remove_listener("response", on_resp)
        except:
            pass


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--max", type=int, default=MAX_POSTS)
    args = parser.parse_args()

    # 加载数据
    data_file = PROJECT_ROOT / "examples" / "douyin_sample.json"
    with open(data_file) as f:
        data = json.load(f)

    items = data.get("items", [])
    need_comments = [i for i in items if not i.get("comments") and i.get("post_id")]
    already_has = sum(1 for i in items if i.get("comments"))
    has_comments_count = sum(len(i.get("comments", [])) for i in items)
    logger.info(f"总 {len(items)} 帖, 已有评论: {already_has}篇/{has_comments_count}条")
    logger.info(f"待采集: {len(need_comments)} 篇, 本轮处理 {min(args.max, len(need_comments))} 篇")

    if not need_comments:
        logger.info("所有帖子已有评论!")
        return

    target = need_comments[:args.max]
    enriched = 0

    with sync_playwright() as p:
        # 可见浏览器
        launch_args = [
            "--disable-blink-features=AutomationControlled",
            "--no-sandbox",
            "--disable-features=TranslateUI",
        ]

        # 优先 Edge，其次 Chrome
        try:
            browser = p.chromium.launch(headless=False, channel="chrome", args=launch_args)
        except:
            browser = p.chromium.launch(headless=False, channel="msedge", args=launch_args)

        ctx = browser.new_context(
            locale="zh-CN",
            viewport={"width": 1440, "height": 900},
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
        )
        page = ctx.new_page()
        page.add_init_script("Object.defineProperty(navigator,'webdriver',{get:()=>false});")

        # 先导航到抖音首页，等用户登录
        page.goto("https://www.douyin.com/", wait_until="domcontentloaded", timeout=30000)
        wait_for_login(page, timeout=120)

        # 保存 cookies
        cookies = ctx.cookies()
        cookie_file = PROJECT_ROOT / "data" / "raw" / "douyin_cookies.json"
        cookie_file.parent.mkdir(parents=True, exist_ok=True)
        with open(cookie_file, "w") as f:
            json.dump(cookies, f, ensure_ascii=False, indent=2, default=str)
        logger.info(f"💾 Cookies 已保存到 {cookie_file}")

        # 开始采集
        for batch_start in range(0, len(target), BATCH_SIZE):
            batch = target[batch_start:batch_start + BATCH_SIZE]
            batch_num = batch_start // BATCH_SIZE + 1
            total_batches = (len(target) + BATCH_SIZE - 1) // BATCH_SIZE

            for i, item in enumerate(batch):
                idx = batch_start + i + 1
                post_id = item.get("post_id", "")[:20]
                title = item.get("title", "")[:25]

                # 偶尔回首页
                if random.random() < 0.15:
                    page.goto("https://www.douyin.com/", wait_until="domcontentloaded", timeout=15000)
                    human_mouse(page)
                    time.sleep(gauss_delay(1, 3))

                logger.info(f"  [{idx}/{len(target)}] {title}...")

                try:
                    comments = collect_comments(page, item.get("post_id", ""))
                    if comments:
                        item["comments"] = comments
                        item["comment_count"] = max(item.get("comment_count", 0), len(comments))
                        enriched += 1
                        logger.info(f"    ✅ {len(comments)}条")
                    else:
                        logger.debug(f"    ⚠️ 无评论")
                except Exception as e:
                    logger.warning(f"    ❌ {e}")

                # 视频间延迟
                if i < len(batch) - 1 or batch_start + BATCH_SIZE < len(target):
                    delay = gauss_delay(*POST_DELAY)
                    logger.debug(f"    ⏱ {delay:.0f}s")
                    time.sleep(delay)

            # 批次间休息
            is_last_batch = (batch_start + BATCH_SIZE) >= len(target)
            if not is_last_batch:
                rest = random.randint(*BATCH_REST)
                logger.info(f"  --- {batch_num}/{total_batches}批 ✅, 休息 {rest}s (~{rest//60}分钟) ---")
                human_mouse(page)
                for remaining in range(rest, 0, -15):
                    time.sleep(min(15, remaining))
                    if random.random() < 0.2:
                        human_mouse(page)

            # 每批保存
            data["total"] = len(data["items"])
            data["collected_at"] = datetime.now(timezone.utc).isoformat()
            with open(data_file, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2, default=str)

        browser.close()

    with_comment = sum(1 for i in data["items"] if i.get("comments"))
    total_comment = sum(len(i.get("comments", [])) for i in data["items"])
    logger.info(f"✅ 本轮 {enriched}篇新增 → 累计 {with_comment}篇/{total_comment}条 → {data_file.name}")


if __name__ == "__main__":
    main()
