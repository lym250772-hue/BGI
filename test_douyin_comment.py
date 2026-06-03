"""测试抖音视频详情页和评论"""
import json, os, time, sys
sys.stdout.reconfigure(encoding='utf-8')
from playwright.sync_api import sync_playwright
from config.settings import settings

cookie_file = os.path.join(settings.raw_data_dir.as_posix(), 'douyin_cookies.json')
with open(cookie_file) as f:
    cookies = json.load(f)

with sync_playwright() as p:
    browser = p.chromium.launch(channel='msedge', headless=True,
        args=['--no-sandbox', '--disable-blink-features=AutomationControlled', '--incognito'])
    context = browser.new_context(
        user_agent='Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36',
        locale='zh-CN', viewport={'width': 1440, 'height': 900},
    )
    cc = [{'name': c.get('name',''), 'value': str(c.get('value','')),
           'domain': c.get('domain',''), 'path': c.get('path','/')} for c in cookies if c.get('name')]
    context.add_cookies(cc)
    page = context.new_page()
    page.add_init_script("Object.defineProperty(navigator, 'webdriver', {get: () => false});")

    # 首页
    page.goto('https://www.douyin.com/', wait_until='domcontentloaded', timeout=15000)
    time.sleep(3)
    print('1. Home:', page.title())

    # JS 移除遮罩
    page.evaluate("() => { document.querySelectorAll('[class*=\"mask\"], [class*=\"overlay\"]').forEach(function(m) { m.remove(); }); }")

    # 搜索
    page.mouse.click(500, 300)
    time.sleep(0.5)
    try:
        page.locator('input').first.click(timeout=5000)
    except:
        page.mouse.click(700, 30)
    time.sleep(0.3)
    page.keyboard.type('刷单', delay=100)
    time.sleep(0.3)
    page.keyboard.press('Enter')
    time.sleep(6)
    print('2. Search:', page.title())

    # 方法1: 直接点击带 @ 的 div（视频卡片）
    found = page.evaluate("""
        () => {
            var divs = document.querySelectorAll('div');
            for (var i = 0; i < divs.length; i++) {
                var d = divs[i];
                var t = d.innerText || '';
                if (t.includes('@') && t.length > 30 && t.length < 300 && !t.includes('搜索')) {
                    // 找这个div里的第一个可点击子元素或者自己
                    d.click();
                    return t.substring(0, 80);
                }
            }
            return '';
        }
    """)
    print('3. Click result:', found[:80] if found else 'NOT FOUND')
    time.sleep(5)
    print('4. After click - URL:', page.url[:120])
    print('   Title:', page.title())

    # 检查有没有视频详情或评论
    body = page.evaluate("() => document.body.innerText")
    print('5. Body length:', len(body))
    if '评论' in body:
        idx = body.find('评论')
        print('   Comment section:', body[idx:idx+400].replace('\n', ' | '))
    elif '视频' in body:
        idx = body.find('视频')
        print('   Video section:', body[idx:idx+300].replace('\n', ' | '))
    else:
        print('   Body:', body[:300].replace('\n', ' | '))

    browser.close()
