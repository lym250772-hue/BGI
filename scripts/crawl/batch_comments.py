"""
批量评论回填 — 读取已有主帖数据，打开详情页采集评论

用法:
  python scripts/crawl/batch_comments.py douyin     # 仅抖音
  python scripts/crawl/batch_comments.py xiaohongshu # 仅小红书
  python scripts/crawl/batch_comments.py tieba       # 仅贴吧
  python scripts/crawl/batch_comments.py all         # 全部
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

EXAMPLES = PROJECT_ROOT / "examples"
MAX_PER_PLATFORM = 100  # 每个平台最多处理多少篇

# ── 拟人工具 ──
def gauss_delay(mi, ma):
    mid = (mi + ma) / 2
    return max(mi, min(ma, random.gauss(mid, (ma - mi) / 4)))

def human_scroll(page):
    total = random.randint(200, 500)
    steps = random.randint(2, 5)
    for _ in range(steps):
        page.evaluate(f"window.scrollBy({random.randint(-15,15)}, {total//steps + random.randint(-20,30)})")
        time.sleep(random.uniform(0.15, 0.4))

# ── 评论采集 ──
def xhs_comments(page, item):
    nid = item.get("post_id", "")
    xsec = item.get("metadata", {}).get("xsec_token", "")
    if not nid or not xsec: return []
    comments = []
    captured = []
    def on_resp(response):
        if "/comment/page" in response.url and f"note_id={nid}" in response.url:
            try:
                body = response.json()
                if body.get("success"): captured.append(body)
            except: pass
    try:
        page.on("response", on_resp)
        page.goto(f"https://www.xiaohongshu.com/explore/{nid}?xsec_token={xsec}",
                   wait_until="domcontentloaded", timeout=20000)
        time.sleep(gauss_delay(2, 4))
        human_scroll(page); time.sleep(1)
        human_scroll(page); time.sleep(2)
        page.remove_listener("response", on_resp)
        if not captured: return []
        for c in captured[0].get("data", {}).get("comments", []):
            u = c.get("user_info", {}) or {}
            comments.append({"id":str(c.get("id","")),"author_uid":str(u.get("user_id","")),
                "author_username":u.get("nickname",""),"content":c.get("content",""),
                "like_count":c.get("like_count",0),"type":"comment",
                "created_at":str(c.get("create_time","")),"reply_to":""})
            for s in c.get("sub_comments",[]):
                su = s.get("user_info", {}) or {}
                comments.append({"id":str(s.get("id","")),"author_uid":str(su.get("user_id","")),
                    "author_username":su.get("nickname",""),"content":s.get("content",""),
                    "like_count":s.get("like_count",0),"type":"reply",
                    "created_at":str(s.get("create_time","")),"reply_to":""})
        return comments
    except Exception as e:
        logger.debug(f"  xhs {nid}: {e}")
        return []
    finally:
        try: page.remove_listener("response", on_resp)
        except: pass

def dy_comments(page, item):
    aid = item.get("post_id", "")
    if not aid: return []
    comments = []
    captured = []
    def on_resp(response):
        if "/comment/list/" in response.url and f"aweme_id={aid}" in response.url:
            try:
                body = response.json()
                if body.get("comments"): captured.append(body)
            except: pass
    try:
        page.on("response", on_resp)
        page.goto(f"https://www.douyin.com/video/{aid}", wait_until="domcontentloaded",
                   timeout=20000, referer="https://www.douyin.com/")
        time.sleep(gauss_delay(3, 6))
        human_scroll(page); time.sleep(2)
        page.remove_listener("response", on_resp)
        if not captured: return []
        for c in captured[0].get("comments", []):
            u = c.get("user", {}) or {}
            comments.append({"id":str(c.get("cid","")),"author_uid":str(u.get("uid","")),
                "author_username":u.get("nickname",""),"content":c.get("text",""),
                "like_count":c.get("digg_count",0),"type":"comment",
                "created_at":str(c.get("create_time","")),"reply_to":""})
            for r in c.get("reply_comment", []) or []:
                ru = r.get("user", {}) or {}
                comments.append({"id":str(r.get("cid","")),"author_uid":str(ru.get("uid","")),
                    "author_username":ru.get("nickname",""),"content":r.get("text",""),
                    "like_count":r.get("digg_count",0),"type":"reply",
                    "created_at":"","reply_to":u.get("nickname","")})
        return comments
    except Exception as e:
        logger.debug(f"  dy {aid}: {e}")
        return []
    finally:
        try: page.remove_listener("response", on_resp)
        except: pass

def tb_replies(page, item):
    tid = item.get("post_id", "")
    if not tid: return []
    from collectors.comment_collector import fetch_tieba_replies
    return fetch_tieba_replies(page, tid, max_pages=1)

# ── 主流程 ──
def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("platform", choices=["douyin","xiaohongshu","tieba","all"])
    parser.add_argument("--max", type=int, default=MAX_PER_PLATFORM, help="每平台最多处理篇数")
    args = parser.parse_args()

    platforms = ["douyin","xiaohongshu","tieba"] if args.platform == "all" else [args.platform]

    for plat in platforms:
        data_file = EXAMPLES / f"{plat}_sample.json"
        if not data_file.exists():
            logger.warning(f"{plat}: 数据文件不存在")
            continue

        with open(data_file) as f:
            data = json.load(f)

        items = data.get("items", [])
        need_comments = [i for i in items if not i.get("comments") and i.get("post_id")]
        logger.info(f"{plat}: {len(items)}条主帖, {len(need_comments)}条无评论, 将处理{min(args.max, len(need_comments))}条")

        if not need_comments:
            continue

        collector = {"xiaohongshu": xhs_comments, "douyin": dy_comments, "tieba": tb_replies}[plat]

        # 加载 Cookies
        cf = PROJECT_ROOT / "data" / "raw" / f"{plat}_cookies.json"
        cookie_data = json.load(open(cf)) if cf.exists() else []

        with sync_playwright() as p:
            launch_args = ["--disable-blink-features=AutomationControlled", "--no-sandbox"]
            browser = None
            # 抖音必须可见浏览器
            if plat == "douyin":
                try: browser = p.chromium.launch(headless=False, channel="chrome", args=launch_args)
                except: browser = p.chromium.launch(headless=False, channel="msedge", args=launch_args)
            else:
                browser = p.chromium.launch(headless=True, args=launch_args)

            ctx = browser.new_context(locale="zh-CN", viewport={"width":1440,"height":900})
            page = ctx.new_page()
            page.add_init_script("Object.defineProperty(navigator,'webdriver',{get:()=>false});")

            clean = [{"name":c["name"],"value":str(c["value"]),"domain":c.get("domain",""),"path":c.get("path","/")}
                     for c in cookie_data if c.get("name") and c.get("domain")]
            if clean: ctx.add_cookies(clean)

            enriched = 0
            for i, item in enumerate(need_comments[:args.max]):
                post_id = item.get("post_id","")[:20]
                logger.info(f"  [{i+1}/{min(args.max,len(need_comments))}] {plat}:{post_id}...")
                try:
                    comments = collector(page, item)
                    if comments:
                        item["comments"] = comments
                        item["comment_count"] = max(item.get("comment_count", 0), len(comments))
                        enriched += 1
                        logger.info(f"    ✅ {len(comments)}条评论")
                except Exception as e:
                    logger.debug(f"    ❌ {e}")

                # 每5条暂停较久
                if (i+1) % 5 == 0:
                    pause = gauss_delay(8, 18)
                    logger.info(f"    ⏸ 休息 {pause:.0f}s (不切换页面)")
                    time.sleep(pause)
                else:
                    time.sleep(gauss_delay(3, 7))

            browser.close()

        # 保存
        data["total"] = len(data["items"])
        data["collected_at"] = datetime.now(timezone.utc).isoformat()
        with open(data_file, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2, default=str)

        with_comment = sum(1 for i in data["items"] if i.get("comments"))
        total_comment = sum(len(i.get("comments", [])) for i in data["items"])
        logger.info(f"{plat}: ✅ {enriched}篇新增评论, 累计{with_comment}篇/{total_comment}条评论 → {data_file.name}")

if __name__ == "__main__":
    main()
