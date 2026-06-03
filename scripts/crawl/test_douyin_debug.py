"""抖音简化测试 — 检查 jingxuan 搜索页的SSR + DOM"""
import sys, json, time, random
from pathlib import Path
from urllib.parse import quote
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))
from collectors.spiders.douyin_spider import DouyinSearchSpider

spider = DouyinSearchSpider(headless=True)
try:
    spider.start()

    # Navigate to jingxuan, dismiss dialog, search
    spider._page.goto('https://www.douyin.com/jingxuan', wait_until='domcontentloaded', timeout=15000)
    time.sleep(2)
    spider._page.evaluate("() => { var d = document.getElementById('trust-logout-dialog'); if(d) d.remove(); document.querySelectorAll('[class*=\"mask\"]').forEach(function(e){e.remove()}); }")

    try:
        inp = spider._page.locator('input').first
        inp.click(timeout=5000)
    except:
        spider._page.mouse.click(700, 30)
    time.sleep(1)
    spider._page.keyboard.type('无人直播', delay=150)
    time.sleep(0.3)
    spider._page.keyboard.press('Enter')

    # Wait longer - 15 seconds
    for i in range(8):
        time.sleep(2)
        url = spider._page.url
        title = spider._page.title()
        vids = spider._page.evaluate("() => document.querySelectorAll('a[href*=\"/video/\"]').length")
        body_len = spider._page.evaluate("() => document.body?.innerText?.length || 0")
        print(f"  [{i*2}s] url={url[-60:]} vids={vids} body_len={body_len}")

    # Final check
    url = spider._page.url
    title = spider._page.title()
    body = spider._page.evaluate("() => document.body?.innerText || ''")
    print(f"\nFinal URL: {url}")
    print(f"Body ({len(body)} chars): {body[:500]}")

    # Check for SSR data
    ssr = spider._page.evaluate("""
    () => {
        if (window.__INITIAL_STATE__) return 'INITIAL_STATE: ' + Object.keys(window.__INITIAL_STATE__).join(', ');
        var render = document.querySelector('#RENDER_DATA');
        if (render) return 'RENDER_DATA: ' + render.textContent.substring(0, 200);
        return 'no SSR data found';
    }
    """)
    print(f"SSR: {ssr}")

    # Check for ANY search-related element
    elems = spider._page.evaluate("""
    () => {
        var result = [];
        document.querySelectorAll('[class*=\"search\"]').forEach(function(el) {
            if (el.innerText && el.innerText.length > 20)
                result.push({tag: el.tagName, cls: el.className.substring(0,50), text: el.innerText.substring(0,80)});
        });
        return result.slice(0, 10);
    }
    """)
    print(f"Search-related elements: {len(elems)}")
    for e in elems[:5]:
        print(f"  <{e['tag']}> {e['cls']}: {e['text']}")

finally:
    spider.close()
