"""小红书可见浏览器采集 — 解决 CAPTCHA 问题"""
import sys, json, time, random, argparse
from pathlib import Path
from datetime import datetime, timezone

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
from playwright.sync_api import sync_playwright
from loguru import logger
logger.remove()
logger.add(sys.stderr, level="INFO", format="<green>{time:HH:mm:ss}</green> | <level>{level: <8}</level> | {message}")

def inject_cookies(context):
    cf = PROJECT_ROOT / "data" / "raw" / "xiaohongshu_cookies.json"
    if cf.exists():
        with open(cf) as f: cookies = json.load(f)
        clean = [{"name": c.get("name",""), "value": str(c.get("value","")),
                  "domain": c.get("domain",""), "path": c.get("path","/")}
                 for c in cookies if c.get("name") and c.get("domain")]
        if clean: context.add_cookies(clean); logger.info(f"已注入 {len(clean)} Cookie")

def search_and_extract(page, keyword, max_pages=2):
    """搜索并提取 SSR 数据"""
    all_items = []
    for pg in range(1, max_pages + 1):
        try:
            page.goto(f"https://www.xiaohongshu.com/search_result?keyword={keyword}&sort=general&page={pg}",
                       wait_until="domcontentloaded", timeout=20000)
            time.sleep(random.uniform(3, 5))

            # Random scroll
            for _ in range(random.randint(1, 3)):
                page.evaluate(f"window.scrollBy(0, {random.randint(200, 600)})")
                time.sleep(random.uniform(0.5, 1.5))

            items = page.evaluate('''
            () => {
                var feeds = window.__INITIAL_STATE__?.search?.feeds?._rawValue || [];
                return feeds.filter(f => f.modelType === "note" && f.noteCard).map(f => ({
                    id: f.id, xsecToken: f.xsecToken || '',
                    displayTitle: f.noteCard.displayTitle || '',
                    desc: f.noteCard.desc || '',
                    type: f.noteCard.type || '',
                    user: f.noteCard.user || {},
                    interactInfo: f.noteCard.interactInfo || {},
                    imageList: (f.noteCard.imageList || []).map(img => {
                        var urls = img.url ? [img.url] : (img.infoList || []).map(i => i.url);
                        return urls[0] || '';
                    }).filter(Boolean),
                    tagList: (f.noteCard.tagList || []).map(t => t.name || ''),
                    time: f.noteCard.time || 0,
                }));
            }
            ''')

            for r in items:
                if not r.get("id"): continue
                title = r.get("displayTitle", "")
                desc = r.get("desc", "")
                user = r.get("user", {})
                interact = r.get("interactInfo", {})

                parts = []
                if title: parts.append(f"【标题】{title}")
                if desc and desc != title: parts.append(f"【正文】{desc}")

                all_items.append({
                    "platform": "xiaohongshu", "post_id": r["id"],
                    "content_raw": "\n".join(parts) if parts else "【无文本内容】",
                    "content_type": "image" if r.get("imageList") else "text",
                    "source_url": f'https://www.xiaohongshu.com/explore/{r["id"]}?xsec_token={r.get("xsecToken","")}',
                    "author_uid": str(user.get("userId", "")),
                    "author_username": user.get("nickname", user.get("nickName", "")),
                    "like_count": int(interact.get("likedCount", 0)),
                    "comment_count": int(interact.get("commentCount", 0)),
                    "collect_count": int(interact.get("collectedCount", 0)),
                    "comments": [], "tags": r.get("tagList", []),
                    "image_urls": r.get("imageList", []),
                    "collected_at": datetime.now(timezone.utc).isoformat(),
                    "keyword": keyword,
                    "metadata": {"note_id": r["id"], "xsec_token": r.get("xsecToken", ""),
                                 "has_image": bool(r.get("imageList"))},
                })

            if len(items) < 10: break
            time.sleep(random.uniform(4, 7))
        except Exception as e:
            logger.error(f"  第{pg}页失败: {e}")
            break
    return all_items

def collect_comments(page, note_id, xsec_token, max_pages=2):
    """响应拦截评论"""
    comments = []
    for pn in range(max_pages):
        captured = []
        def on_resp(response):
            if "/comment/page" in response.url and f"note_id={note_id}" in response.url:
                try:
                    body = response.json()
                    if body.get("success"): captured.append(body)
                except: pass
        try:
            page.on("response", on_resp)
            if pn == 0:
                page.goto(f"https://www.xiaohongshu.com/explore/{note_id}?xsec_token={xsec_token}",
                           wait_until="domcontentloaded", timeout=20000)
                time.sleep(3)
                page.evaluate("window.scrollBy(0, 1500)")
                time.sleep(3)
            else:
                page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                time.sleep(3)
            page.remove_listener("response", on_resp)
            if not captured: break
            for c in captured[0].get("data", {}).get("comments", []):
                user = c.get("user_info", {}) or {}
                comments.append({
                    "id": str(c.get("id","")), "author_uid": str(user.get("user_id","")),
                    "author_username": user.get("nickname",""), "content": c.get("content",""),
                    "like_count": c.get("like_count",0), "reply_to": "", "type": "comment",
                    "created_at": str(c.get("create_time","")),
                })
                for s in c.get("sub_comments", []):
                    su = s.get("user_info", {}) or {}
                    comments.append({
                        "id": str(s.get("id","")), "author_uid": str(su.get("user_id","")),
                        "author_username": su.get("nickname",""), "content": s.get("content",""),
                        "like_count": s.get("like_count",0), "type": "reply",
                        "created_at": str(s.get("create_time","")),
                    })
            if len(captured[0].get("data",{}).get("comments",[])) < 10: break
            time.sleep(random.uniform(1, 2))
        except Exception as e:
            logger.debug(f"  评论{pn+1}失败: {e}")
            break
        finally:
            try: page.remove_listener("response", on_resp)
            except: pass
    return comments

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--keywords", "-k", default="刷单,接码,跑分,引流,养号,出号,号商,卡商,打码,挂机,搬砖,洗号,狗推,料商,无人直播,薅羊毛,撞库,融车,代下,代理IP")
    parser.add_argument("--max-pages", type=int, default=2)
    parser.add_argument("--with-comments", action="store_true")
    parser.add_argument("--max-comment-items", type=int, default=30)
    parser.add_argument("--output", default=str(PROJECT_ROOT / "examples" / "xiaohongshu_sample.json"))
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

        print("\n" + "=" * 60)
        print(f"📱 小红书采集  关键词: {len(keywords)}个  评论: {'✅' if args.with_comments else '❌'}")
        print("   如有验证码请在浏览器中手动完成")
        print("=" * 60 + "\n")

        all_items = []
        for kw in keywords:
            items = search_and_extract(page, kw, args.max_pages)
            logger.info(f"[{kw}] {len(items)}条")
            all_items.extend(items)
            time.sleep(random.uniform(3, 6))

        # 评论
        if args.with_comments and all_items:
            logger.info(f"评论采集 (最多{args.max_comment_items}条帖子)...")
            enriched = 0
            for item in all_items[:args.max_comment_items]:
                nid = item.get("post_id", "")
                xsec = item.get("metadata", {}).get("xsec_token", "")
                if not nid: continue
                cs = collect_comments(page, nid, xsec)
                if cs:
                    item["comments"] = cs
                    item["comment_count"] = max(item.get("comment_count", 0), len(cs))
                    enriched += 1
                time.sleep(random.uniform(1, 2))
            logger.info(f"评论完成: {enriched}篇")

        browser.close()

    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    with open(out, "w", encoding="utf-8") as f:
        json.dump({"platform": "xiaohongshu", "collected_at": datetime.now(timezone.utc).isoformat(),
                    "keywords": keywords, "total": len(all_items), "items": all_items},
                  f, ensure_ascii=False, indent=2, default=str)
    logger.info(f"✅ {len(all_items)}条 → {out}")

if __name__ == "__main__":
    main()
