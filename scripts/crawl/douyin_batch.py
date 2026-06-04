"""抖音分批采集 — 拟人化操作避免验证码"""
import sys, json, time, random, math
from pathlib import Path
from datetime import datetime, timezone

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
from playwright.sync_api import sync_playwright

ALL_KEYWORDS = "714高炮,AB贷,上车,下车,云手机,人脸,代下,代理IP,众包,八件套,养号,出号,刷单,千粉,卡商,反卤,发卡,可开播,号商,四件套,大肉,引流,打码,报单,挂机,接码,搬砖,撞库,数字人,料商,无人直播,无损套,日结,模拟器,水房,洗号,狗推,猫池,白户,破盾,羊头,羊腿,群控,薅羊毛,融车,跑分,车手,黄牛"
OUTPUT = PROJECT_ROOT / "examples" / "douyin_sample.json"

# ── 拟人化工具 ──────────────────────────────────────────────────────────

def human_delay(base_min=1.0, base_max=3.0):
    """带高斯分布的随机延迟"""
    mid = (base_min + base_max) / 2
    std = (base_max - base_min) / 4
    delay = random.gauss(mid, std)
    return max(base_min, min(base_max, delay))

def human_scroll(page):
    """非直线滚动：分多步、变速、带随机偏移"""
    total = random.randint(300, 800)
    steps = random.randint(3, 7)
    for s in range(steps):
        step = total // steps + random.randint(-30, 50)
        # 微微水平偏移模拟手指不稳定
        x_offset = random.randint(-20, 20)
        page.evaluate(f"window.scrollBy({x_offset}, {step})")
        time.sleep(random.uniform(0.15, 0.5))
    # 偶尔回滚一点（模拟人看到感兴趣的内容回看）
    if random.random() < 0.2:
        page.evaluate(f"window.scrollBy(0, {random.randint(-100, -30)})")
        time.sleep(random.uniform(0.3, 0.8))

def human_mouse_move(page, x, y):
    """贝塞尔曲线鼠标移动"""
    start_x, start_y = random.randint(100, 500), random.randint(100, 400)
    steps = random.randint(20, 40)
    cx1, cy1 = start_x + random.randint(-100, 200), start_y + random.randint(-100, 200)
    cx2, cy2 = x + random.randint(-100, 100), y + random.randint(-100, 100)
    for i in range(steps):
        t = i / steps
        px = (1-t)**3*start_x + 3*(1-t)**2*t*cx1 + 3*(1-t)*t**2*cx2 + t**3*x
        py = (1-t)**3*start_y + 3*(1-t)**2*t*cy1 + 3*(1-t)*t**2*cy2 + t**3*y
        page.mouse.move(px, py)
        time.sleep(random.uniform(0.003, 0.012))

def human_type(page, text):
    """模拟拼音输入：每个字符带随机延迟，偶尔打错回退"""
    for ch in text:
        time.sleep(random.uniform(0.08, 0.25))
        page.keyboard.type(ch, delay=random.randint(50, 150))
        # 1% 概率打错一个字然后删除
        if random.random() < 0.01:
            time.sleep(random.uniform(0.2, 0.5))
            page.keyboard.press("Backspace")
            time.sleep(random.uniform(0.1, 0.3))
            page.keyboard.type(ch, delay=random.randint(60, 180))

# ── 数据管理 ──────────────────────────────────────────────────────────

def load():
    if OUTPUT.exists():
        with open(OUTPUT) as f: return json.load(f)
    return {"platform":"douyin","collected_at":"","keywords":[],"total":0,"items":[]}

def save(data):
    data["total"] = len(data["items"])
    data["collected_at"] = datetime.now(timezone.utc).isoformat()
    with open(OUTPUT, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2, default=str)

# ── 搜索采集 ──────────────────────────────────────────────────────────

def search_batch(page, keywords, tokens, max_pages=2):
    from collectors.spiders.douyin_spider import generate_xbogus
    items = []

    for kw in keywords:
        # 关键词间较长休息
        pause = human_delay(8, 18)
        print(f"  ⏸ 休息 {pause:.0f}s...")
        time.sleep(pause)

        for pg in range(1, max_pages + 1):
            try:
                params = [
                    ("device_platform","webapp"),("aid","6383"),("channel","channel_pc_web"),
                    ("search_channel","aweme_general"),("sort_type","0"),("publish_time","0"),
                    ("keyword",kw),("search_source","normal_search"),
                    ("query_correct_type","1"),("is_filter_search","0"),("from_group_id",""),
                    ("offset",str((pg-1)*10)),("count","15"),
                    ("pc_client_type","1"),("version_code","190600"),("version_name","19.6.0"),
                    ("cookie_enabled","true"),
                ]
                if tokens.get("msToken"): params.append(("msToken",tokens["msToken"]))
                if tokens.get("webid"): params.append(("webid",tokens["webid"]))
                qs = "&".join(f"{k}={v}" for k,v in params)
                qs += f"&X-Bogus={generate_xbogus(qs)}"
                url = f"https://www.douyin.com/aweme/v1/web/general/search/single/?{qs}"

                result = page.evaluate(f"""
                async () => {{
                    const ctrl = new AbortController();
                    setTimeout(() => ctrl.abort(), 15000);
                    try {{
                        const r = await fetch('{url}',{{method:'GET',credentials:'include',headers:{{'Accept':'application/json'}},signal:ctrl.signal}});
                        return await r.json();
                    }} catch(e) {{ return {{error:e.message}}; }}
                }}
                """)
                if result.get("error"):
                    print(f"  [{kw}] p{pg}: {result['error'][:50]}")
                    break

                for d in result.get("data",[]):
                    if d.get("type") != 1: continue
                    a = d.get("aweme_info", d)
                    aid = str(a.get("aweme_id",""))
                    if not aid: continue
                    author = a.get("author",{}) or {}
                    stats = a.get("statistics",{}) or {}
                    video = a.get("video",{}) or {}
                    cover = (video.get("cover",{}) or {}).get("url_list",[""])[0]
                    images = []
                    for img in (a.get("images",[]) or []):
                        urls = img.get("url_list",[])
                        if urls: images.append(urls[0])
                    items.append({
                        "platform":"douyin","post_id":aid,
                        "content_raw":f"【描述】{a.get('desc','')}",
                        "content_type":"image" if images else "video",
                        "source_url":f"https://www.douyin.com/video/{aid}",
                        "author_uid":str(author.get("uid","")),
                        "author_username":author.get("nickname",""),
                        "like_count":stats.get("digg_count",0),
                        "comment_count":stats.get("comment_count",0),
                        "share_count":stats.get("share_count",0),
                        "comments":[],"tags":[],
                        "image_urls":images,"video_cover_url":cover,
                        "collected_at":datetime.now(timezone.utc).isoformat(),
                        "keyword":kw,
                        "metadata":{"aweme_id":aid},
                    })
                # 翻页间隔
                time.sleep(human_delay(4, 8))
            except Exception as e:
                print(f"  [{kw}] ERROR: {e}")
                break

    return items


# ── 主流程 ──────────────────────────────────────────────────────────

all_kw = [k.strip() for k in ALL_KEYWORDS.split(",") if k.strip()]
data = load()
seen_kw = set(i["keyword"] for i in data["items"])
remaining = [k for k in all_kw if k not in seen_kw]
print(f"已有: {len(seen_kw)} 关键词, {len(data['items'])} 条 | 待采: {len(remaining)}")

tokens = {}
tf = PROJECT_ROOT / "data" / "raw" / "douyin_tokens.json"
if tf.exists():
    with open(tf) as f: tokens = json.load(f)

cf = PROJECT_ROOT / "data" / "raw" / "douyin_cookies.json"
cookie_data = json.load(open(cf)) if cf.exists() else []

print("🚀 启动浏览器...")
with sync_playwright() as p:
    try:
        browser = p.chromium.launch(headless=False, channel="chrome",
                                     args=["--disable-blink-features=AutomationControlled","--disable-dev-shm-usage"])
    except:
        browser = p.chromium.launch(headless=False, channel="msedge",
                                     args=["--disable-blink-features=AutomationControlled"])
    ctx = browser.new_context(locale="zh-CN", viewport={"width":1440,"height":900})
    page = ctx.new_page()
    page.add_init_script("Object.defineProperty(navigator,'webdriver',{get:()=>false});")

    clean = [{"name":c["name"],"value":str(c["value"]),"domain":c.get("domain",""),"path":c.get("path","/")}
             for c in cookie_data if c.get("name") and c.get("domain")]
    if clean: ctx.add_cookies(clean)

    # 先打开首页建立会话
    page.goto("https://www.douyin.com/jingxuan", wait_until="domcontentloaded", timeout=20000)
    time.sleep(human_delay(3, 6))
    page.evaluate("() => { var d=document.getElementById('trust-logout-dialog'); if(d) d.remove(); }")

    # 随机浏览首页（模拟真实用户）
    for _ in range(random.randint(2, 4)):
        human_scroll(page)
        time.sleep(human_delay(1, 3))

    BATCH_SIZE = 3
    for i in range(0, len(remaining), BATCH_SIZE):
        batch = remaining[i:i+BATCH_SIZE]
        print(f"\n📦 批次 {i//BATCH_SIZE+1} ({len(batch)}词): {batch}")
        new_items = search_batch(page, batch, tokens, max_pages=2)
        data["items"].extend(new_items)
        data["keywords"] = list(set(data["keywords"]) | set(batch))
        save(data)
        print(f"  ✅ 本批{len(new_items)}条 | 累计{len(data['items'])}条")

        # 每批后随机浏览首页
        page.goto("https://www.douyin.com/jingxuan", wait_until="domcontentloaded", timeout=15000)
        time.sleep(human_delay(5, 10))
        for _ in range(random.randint(1, 3)):
            human_scroll(page)
            time.sleep(human_delay(1, 3))

    browser.close()

print(f"\n🎉 完成: {len(data['items'])}条 → {OUTPUT}")
