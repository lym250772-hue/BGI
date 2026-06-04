"""
小红书评论慢速采集 v2 — 强制扫码登录，修复假登录检测
每 2 个笔记休息 60-120 秒，笔记间隔 8-16 秒高斯分布

用法:
  python scripts/crawl/xiaohongshu_comments_gentle.py
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

MAX_POSTS = 100
BATCH_SIZE = 4
BATCH_REST = (30, 60)
POST_DELAY = (5, 10)


def gauss_delay(mi, ma):
    mid = (mi + ma) / 2
    return max(mi, min(ma, random.gauss(mid, (ma - mi) / 4)))


def human_mouse(page):
    try:
        page.mouse.move(random.randint(200,1200), random.randint(200,700), steps=random.randint(15,30))
    except: pass


def human_scroll(page):
    total = random.randint(300, 600)
    steps = random.randint(2, 5)
    for _ in range(steps):
        try:
            page.evaluate(f"window.scrollBy({random.randint(-15,15)}, {total//steps + random.randint(-20,30)})")
            time.sleep(random.uniform(0.2, 0.5))
        except: pass


def is_logged_in(page):
    """真正检测登录：看页面有没有'登录'文字"""
    try:
        text = page.evaluate("() => document.body.innerText.substring(0, 2000)")
        # 如果页面没有"登录后推荐"、"手机号登录"等未登录提示，就是已登录
        if "登录后推荐" in text or "手机号登录" in text:
            return False
        # 检查是否有用户名（登录后会显示）
        if "马上登录" in text:
            return False
        return True
    except:
        return False


def wait_for_login(page, timeout=300):
    """等待用户在可见浏览器中扫码登录小红书"""
    logger.info("📱 请在浏览器中【扫码登录】小红书 (微信/小红书App扫码)")
    logger.info(f"   等待时间: {timeout}秒...")
    start = time.time()
    last_status = False
    while time.time() - start < timeout:
        try:
            logged = is_logged_in(page)
            if logged:
                if not last_status:
                    logger.info("✅ 检测到登录成功!")
                return True
            last_status = logged
        except:
            pass
        time.sleep(3)

        # 每30秒提醒
        elapsed = int(time.time() - start)
        if elapsed > 0 and elapsed % 30 == 0 and elapsed < timeout - 10:
            logger.info(f"   已等待 {elapsed}秒, 请扫码登录...")
    return False


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
            except:
                pass

    try:
        page.on("response", on_resp)
        url = f"https://www.xiaohongshu.com/explore/{note_id}"
        if xsec_token:
            url += f"?xsec_token={xsec_token}"
        page.goto(url, wait_until="domcontentloaded", timeout=20000)
        time.sleep(gauss_delay(3, 6))
        human_scroll(page)
        time.sleep(1.5)
        human_scroll(page)
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
    no_xsec = sum(1 for i in items if not i.get("metadata", {}).get("xsec_token"))
    logger.info(f"总 {len(items)} 帖 | 缺xsec: {no_xsec}篇 | 可采: {len(need_comments)}篇 | 本轮: {min(args.max, len(need_comments))}")

    if not need_comments:
        logger.info("没有可采集的帖子!")
        return

    target = need_comments[:args.max]
    enriched = 0

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False,
            args=["--disable-blink-features=AutomationControlled", "--no-sandbox"])
        ctx = browser.new_context(locale="zh-CN", viewport={"width": 1440, "height": 900})
        page = ctx.new_page()
        page.add_init_script("Object.defineProperty(navigator,'webdriver',{get:()=>false});")

        # 打开小红书首页
        page.goto("https://www.xiaohongshu.com/explore", wait_until="domcontentloaded", timeout=30000)

        # 强制等登录
        if not is_logged_in(page):
            logged = wait_for_login(page, timeout=300)
            if not logged:
                logger.warning("未登录，评论可能抓不到。继续尝试...")
        else:
            logger.info("✅ 已登录")

        # 保存 cookies
        cookies = ctx.cookies()
        cookie_file = PROJECT_ROOT / "data" / "raw" / "xiaohongshu_cookies.json"
        cookie_file.parent.mkdir(parents=True, exist_ok=True)
        with open(cookie_file, "w") as f:
            json.dump(cookies, f, ensure_ascii=False, indent=2, default=str)
        logger.info(f"💾 Cookies 已保存")

        # 开始采集
        for batch_start in range(0, len(target), BATCH_SIZE):
            batch = target[batch_start:batch_start + BATCH_SIZE]
            batch_num = batch_start // BATCH_SIZE + 1
            total_batches = (len(target) + BATCH_SIZE - 1) // BATCH_SIZE

            for i, item in enumerate(batch):
                idx = batch_start + i + 1
                post_id = item.get("post_id", "")
                xsec = item.get("metadata", {}).get("xsec_token", "")
                title = item.get("title", "")[:30]

                if random.random() < 0.2:
                    try:
                        page.goto("https://www.xiaohongshu.com/explore", wait_until="domcontentloaded", timeout=15000)
                        human_mouse(page)
                        time.sleep(gauss_delay(2, 4))
                    except: pass

                logger.info(f"  [{idx}/{len(target)}] {post_id[:16]}...")

                try:
                    comments = collect_comments(page, post_id, xsec)
                    if comments:
                        item["comments"] = comments
                        item["comment_count"] = max(item.get("comment_count", 0), len(comments))
                        enriched += 1
                        logger.info(f"    ✅ {len(comments)}条")
                    else:
                        logger.info(f"    ⚠️ 0条")
                except Exception as e:
                    logger.warning(f"    ❌ {e}")

                if i < len(batch) - 1 or batch_start + BATCH_SIZE < len(target):
                    delay = gauss_delay(*POST_DELAY)
                    time.sleep(delay)

            is_last_batch = (batch_start + BATCH_SIZE) >= len(target)
            if not is_last_batch:
                rest = random.randint(*BATCH_REST)
                logger.info(f"  --- {batch_num}/{total_batches}批 ✅, 休息 {rest}s ---")
                try:
                    page.goto("https://www.xiaohongshu.com/explore", wait_until="domcontentloaded", timeout=15000)
                except: pass
                for remaining in range(rest, 0, -15):
                    time.sleep(min(15, remaining))
                    if random.random() < 0.15:
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
