"""抖音可见浏览器采集 v3 — 主帖 + 评论"""
import sys, json, time, random, argparse
from pathlib import Path
from datetime import datetime, timezone

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
from playwright.sync_api import sync_playwright
from loguru import logger
logger.remove()
logger.add(sys.stderr, level="INFO", format="<green>{time:HH:mm:ss}</green> | <level>{level: <8}</level> | {message}")

def load_tokens():
    tf = PROJECT_ROOT / "data" / "raw" / "douyin_tokens.json"
    if tf.exists():
        with open(tf) as f: return json.load(f)
    return {}

def inject_cookies(context):
    cf = PROJECT_ROOT / "data" / "raw" / "douyin_cookies.json"
    if cf.exists():
        with open(cf) as f: cookies = json.load(f)
        clean = [{"name": c.get("name",""), "value": str(c.get("value","")),
                  "domain": c.get("domain",""), "path": c.get("path","/")}
                 for c in cookies if c.get("name") and c.get("domain")]
        if clean: context.add_cookies(clean)
        return True
    return False

def search_api(page, keyword, page_num=1):
    sys.path.insert(0, str(PROJECT_ROOT))
    from collectors.spiders.douyin_spider import generate_xbogus
    tokens = load_tokens()
    params = [
        ("device_platform", "webapp"), ("aid", "6383"), ("channel", "channel_pc_web"),
        ("search_channel", "aweme_general"), ("sort_type", "0"), ("publish_time", "0"),
        ("keyword", keyword), ("search_source", "normal_search"),
        ("query_correct_type", "1"), ("is_filter_search", "0"), ("from_group_id", ""),
        ("offset", str((page_num-1)*10)), ("count", "15"),
        ("pc_client_type", "1"), ("version_code", "190600"), ("version_name", "19.6.0"),
        ("cookie_enabled", "true"),
    ]
    if tokens.get("msToken"): params.append(("msToken", tokens["msToken"]))
    if tokens.get("webid"): params.append(("webid", tokens["webid"]))
    qs = "&".join(f"{k}={v}" for k, v in params)
    qs += f"&X-Bogus={generate_xbogus(qs)}"
    url = f"https://www.douyin.com/aweme/v1/web/general/search/single/?{qs}"

    result = page.evaluate(f"""
    async () => {{
        const ctrl = new AbortController();
        setTimeout(() => ctrl.abort(), 12000);
        try {{
            const r = await fetch('{url}', {{method:'GET',credentials:'include',headers:{{'Accept':'application/json'}},signal:ctrl.signal}});
            return await r.json();
        }} catch(e) {{ return {{error:e.message}}; }}
    }}
    """)
    if result.get("error"):
        logger.warning(f"  API: {result['error']}")
        return [], result.get("search_nil_info", {})

    data = result.get("data", [])
    nil = result.get("search_nil_info", {})
    items = []
    for d in data:
        if d.get("type") != 1: continue
        a = d.get("aweme_info", d)
        aid = str(a.get("aweme_id", ""))
        if not aid: continue
        author = a.get("author", {}) or {}
        stats = a.get("statistics", {}) or {}
        video = a.get("video", {}) or {}
        cover = (video.get("cover", {}) or {}).get("url_list", [""])[0] if video else ""
        images = []
        for img in (a.get("images", []) or []):
            urls = img.get("url_list", [])
            if urls: images.append(urls[0])
        items.append({
            "platform": "douyin", "post_id": aid,
            "content_raw": f"【描述】{a.get('desc','')}",
            "content_type": "image" if images else "video",
            "source_url": f"https://www.douyin.com/video/{aid}",
            "author_uid": str(author.get("uid", "")),
            "author_username": author.get("nickname", ""),
            "like_count": stats.get("digg_count", 0),
            "comment_count": stats.get("comment_count", 0),
            "share_count": stats.get("share_count", 0),
            "comments": [], "tags": [],
            "image_urls": images, "video_cover_url": cover,
            "collected_at": datetime.now(timezone.utc).isoformat(),
            "keyword": keyword,
            "metadata": {"aweme_id": aid, "has_image": bool(images)},
        })
    return items, nil

def collect_comments(page, aweme_id, max_comment_pages=2):
    """拦截评论 API（打开视频页→滚动→截获响应）"""
    comments = []
    for pn in range(max_comment_pages):
        captured = []
        def on_resp(response):
            if "/comment/list/" in response.url and f"aweme_id={aweme_id}" in response.url:
                try:
                    body = response.json()
                    if body.get("comments"): captured.append(body)
                except: pass
        try:
            page.on("response", on_resp)
            if pn == 0:
                page.goto(f"https://www.douyin.com/video/{aweme_id}",
                          wait_until="domcontentloaded", timeout=20000,
                          referer="https://www.douyin.com/")
                time.sleep(4)
                page.evaluate("window.scrollBy(0, 800)")
                time.sleep(3)
            else:
                page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                time.sleep(3)
            page.remove_listener("response", on_resp)
            if not captured: break
            for c in captured[0].get("comments", []):
                user = c.get("user", {}) or {}
                comments.append({
                    "id": str(c.get("cid", "")), "author_uid": str(user.get("uid", "")),
                    "author_username": user.get("nickname", ""),
                    "content": c.get("text", ""), "like_count": c.get("digg_count", 0),
                    "reply_to": "", "created_at": str(c.get("create_time", "")),
                    "type": "comment",
                })
                for r in (c.get("reply_comment", []) or []):
                    ru = r.get("user", {}) or {}
                    comments.append({
                        "id": str(r.get("cid", "")), "author_uid": str(ru.get("uid", "")),
                        "author_username": ru.get("nickname", ""),
                        "content": r.get("text", ""), "like_count": r.get("digg_count", 0),
                        "reply_to": user.get("nickname", ""), "created_at": "",
                        "type": "reply",
                    })
            if len(captured[0].get("comments", [])) < 20: break
            time.sleep(random.uniform(1, 2))
        except Exception as e:
            logger.debug(f"  评论第{pn+1}页失败: {e}")
            break
        finally:
            try: page.remove_listener("response", on_resp)
            except: pass
    return comments

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--keywords", "-k", default="刷单,无人直播,账号出售")
    parser.add_argument("--max-pages", type=int, default=2)
    parser.add_argument("--with-comments", action="store_true", help="采集主帖后继续采集评论")
    parser.add_argument("--max-comment-items", type=int, default=10, help="最多为多少条帖子采集评论")
    parser.add_argument("--output", default=str(PROJECT_ROOT / "examples" / "douyin_sample.json"))
    args = parser.parse_args()
    keywords = [k.strip() for k in args.keywords.split(",") if k.strip()]

    with sync_playwright() as p:
        try:
            browser = p.chromium.launch(headless=False, channel="chrome",
                                         args=["--disable-blink-features=AutomationControlled"])
        except:
            browser = p.chromium.launch(headless=False, channel="msedge",
                                         args=["--disable-blink-features=AutomationControlled"])
        ctx = browser.new_context(locale="zh-CN", viewport={"width": 1440, "height": 900})
        page = ctx.new_page()
        page.add_init_script("Object.defineProperty(navigator, 'webdriver', {get: () => false});")
        inject_cookies(ctx)
        page.goto("https://www.douyin.com/jingxuan", wait_until="domcontentloaded", timeout=20000)
        time.sleep(3)

        print("\n" + "=" * 60)
        print("📱 采集进行中...")
        print(f"   关键词: {keywords}  评论: {'✅' if args.with_comments else '❌'}")
        print("=" * 60 + "\n")

        all_items = []
        for kw in keywords:
            for pg in range(1, args.max_pages + 1):
                items, nil = search_api(page, kw, pg)
                nil_type = nil.get("search_nil_item", "")
                if nil_type:
                    logger.warning(f"  [{kw}] 第{pg}页 nil={nil_type}")
                    if nil_type == "hit_shark": break
                all_items.extend(items)
                if not items: break
                time.sleep(random.uniform(2, 4))

        # 评论采集
        if args.with_comments and all_items:
            logger.info(f"开始采集评论 (最多 {args.max_comment_items} 条帖子)...")
            enriched = 0
            for item in all_items[:args.max_comment_items]:
                aid = item.get("post_id", "")
                if not aid: continue
                comments = collect_comments(page, aid)
                if comments:
                    item["comments"] = comments
                    item["comment_count"] = max(item.get("comment_count", 0), len(comments))
                    enriched += 1
                time.sleep(random.uniform(1, 3))
            logger.info(f"评论采集完成: {enriched}/{min(len(all_items), args.max_comment_items)}")

        browser.close()

    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    with open(out, "w", encoding="utf-8") as f:
        json.dump({"platform": "douyin", "collected_at": datetime.now(timezone.utc).isoformat(),
                    "keywords": keywords, "total": len(all_items), "items": all_items},
                  f, ensure_ascii=False, indent=2, default=str)
    logger.info(f"✅ {len(all_items)} 条 → {out}")


if __name__ == "__main__":
    main()
