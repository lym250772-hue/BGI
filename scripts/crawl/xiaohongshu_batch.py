"""小红书分批采集 — 等用户手动过验证后再采集"""
import sys, json, time, random
from pathlib import Path
from datetime import datetime, timezone

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
from playwright.sync_api import sync_playwright

ALL_KEYWORDS = "714高炮,AB贷,上车,下车,云手机,人脸,代下,代理IP,众包,八件套,养号,出号,刷单,千粉,卡商,反卤,发卡,可开播,号商,四件套,大肉,引流,打码,报单,挂机,接码,搬砖,撞库,数字人,料商,无人直播,无损套,日结,模拟器,水房,洗号,狗推,猫池,白户,破盾,羊头,羊腿,群控,薅羊毛,融车,跑分,车手,黄牛"
OUTPUT = PROJECT_ROOT / "examples" / "xiaohongshu_sample.json"

def human_delay(bmin, bmax):
    mid = (bmin + bmax) / 2
    return max(bmin, min(bmax, random.gauss(mid, (bmax - bmin) / 4)))

def human_scroll(page):
    total = random.randint(200, 500)
    steps = random.randint(2, 5)
    for _ in range(steps):
        page.evaluate(f"window.scrollBy({random.randint(-15,15)}, {total//steps + random.randint(-20,30)})")
        time.sleep(random.uniform(0.15, 0.4))

def load():
    if OUTPUT.exists():
        with open(OUTPUT) as f: return json.load(f)
    return {"platform":"xiaohongshu","collected_at":"","keywords":[],"total":0,"items":[]}

def save(data):
    data["total"] = len(data["items"])
    data["collected_at"] = datetime.now(timezone.utc).isoformat()
    with open(OUTPUT,"w",encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2, default=str)

all_kw = [k for k in ALL_KEYWORDS.split(",") if k.strip()]
data = load()
seen = set(i.get("keyword","") for i in data["items"])
remaining = [k for k in all_kw if k not in seen]
print(f"已有: {len(seen)}词 {len(data['items'])}条 | 待采: {len(remaining)}词")

with sync_playwright() as p:
    browser = p.chromium.launch(headless=False,
                                 args=["--disable-blink-features=AutomationControlled","--no-sandbox"])
    ctx = browser.new_context(locale="zh-CN", viewport={"width":1440,"height":900})
    page = ctx.new_page()
    page.add_init_script("Object.defineProperty(navigator,'webdriver',{get:()=>false});")

    # ── 手动登录 + 过验证 ──
    print("\n" + "=" * 60)
    print("📱 请在浏览器中完成以下操作：")
    print("   1. 打开 xiaohongshu.com 并登录")
    print("   2. 如有验证码/滑块，手动完成")
    print("   3. 搜索 '刷单' 确认能看到结果")
    print("   4. 回到终端按 Enter 开始采集")
    print("=" * 60)
    page.goto("https://www.xiaohongshu.com", wait_until="domcontentloaded", timeout=30000)
    input("\n✅ 确认可以正常搜索后按 Enter...")

    # ── 保存新 Cookie ──
    cookies = ctx.cookies()
    with open(PROJECT_ROOT / "data" / "raw" / "xiaohongshu_cookies.json", "w", encoding="utf-8") as f:
        json.dump(cookies, f, ensure_ascii=False, indent=2, default=str)
    print(f"已保存 {len(cookies)} 条 Cookie")

    # ── 分批采集 ──
    for i in range(0, len(remaining), 2):
        batch = remaining[i:i+2]
        pause = human_delay(12, 25)
        print(f"\n📦 {i//2+1}: {batch}  (等待{pause:.0f}s...)")
        time.sleep(pause)

        for kw in batch:
            try:
                page.goto(f"https://www.xiaohongshu.com/search_result?keyword={kw}&sort=general",
                           wait_until="domcontentloaded", timeout=20000)
                time.sleep(human_delay(4, 8))
                for _ in range(random.randint(2, 4)):
                    human_scroll(page)
                    time.sleep(human_delay(0.5, 1.5))

                # 检查是否还在验证页
                title = page.title()
                if "验证" in title or "captcha" in title.lower():
                    print(f"  ❌ [{kw}] 触发验证！请在浏览器中手动通过，然后按 Enter...")
                    input()
                    page.goto(f"https://www.xiaohongshu.com/search_result?keyword={kw}&sort=general",
                               wait_until="domcontentloaded", timeout=20000)
                    time.sleep(human_delay(4, 8))

                raw = page.evaluate('''
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
                    }));
                }
                ''')

                for r in raw:
                    if not r.get("id"): continue
                    title_t = r.get("displayTitle","")
                    desc = r.get("desc","")
                    user = r.get("user",{})
                    interact = r.get("interactInfo",{})
                    parts = []
                    if title_t: parts.append(f"【标题】{title_t}")
                    if desc and desc != title_t: parts.append(f"【正文】{desc}")
                    data["items"].append({
                        "platform":"xiaohongshu","post_id":r["id"],
                        "content_raw":"\n".join(parts) if parts else "【无文本内容】",
                        "content_type":"image" if r.get("imageList") else "text",
                        "source_url":f'https://www.xiaohongshu.com/explore/{r["id"]}?xsec_token={r.get("xsecToken","")}',
                        "author_uid":str(user.get("userId","")),
                        "author_username":user.get("nickname",user.get("nickName","")),
                        "like_count":int(interact.get("likedCount",0)),
                        "comment_count":int(interact.get("commentCount",0)),
                        "collect_count":int(interact.get("collectedCount",0)),
                        "comments":[],"tags":r.get("tagList",[]),
                        "image_urls":r.get("imageList",[]),
                        "collected_at":datetime.now(timezone.utc).isoformat(),
                        "keyword":kw,
                        "metadata":{"note_id":r["id"],"xsec_token":r.get("xsecToken",""),
                                     "has_image":bool(r.get("imageList"))},
                    })

                print(f"  [{kw}] {len(raw)}条")
                time.sleep(human_delay(6, 12))
            except Exception as e:
                print(f"  [{kw}] ERROR: {e}")

        save(data)
        print(f"  ✅ 累计{len(data['items'])}条")

        # 回首页休息
        page.goto("https://www.xiaohongshu.com", wait_until="domcontentloaded", timeout=15000)
        time.sleep(human_delay(10, 18))
        for _ in range(random.randint(1, 2)):
            human_scroll(page)
            time.sleep(human_delay(1, 2))

    browser.close()

print(f"\n🎉 完成: {len(data['items'])}条 → {OUTPUT}")
