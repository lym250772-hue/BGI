"""测试抖音搜索 — 首页搜索框 → 搜索页 → DOM提取"""
import json, os, time, sys
sys.stdout.reconfigure(encoding='utf-8')

from playwright.sync_api import sync_playwright
from config.settings import settings
from urllib.parse import quote

cookie_file = os.path.join(settings.raw_data_dir.as_posix(), 'douyin_cookies.json')
with open(cookie_file) as f:
    cookies = json.load(f)

with sync_playwright() as p:
    browser = p.chromium.launch(
        channel='msedge', headless=True,
        args=['--no-sandbox', '--disable-blink-features=AutomationControlled', '--incognito'],
    )
    context = browser.new_context(
        user_agent='Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36',
        locale='zh-CN', viewport={'width': 1440, 'height': 900},
    )
    clean_cookies = []
    for c in cookies:
        if c.get('name'):
            cc = {'name': c['name'], 'value': str(c['value']),
                  'domain': c.get('domain', ''), 'path': c.get('path', '/')}
            if c.get('expirationDate'):
                cc['expires'] = float(c['expirationDate'])
            clean_cookies.append(cc)
    context.add_cookies(clean_cookies)

    page = context.new_page()
    page.add_init_script(
        "Object.defineProperty(navigator, 'webdriver', {get: () => false});"
    )

    # 首页
    page.goto('https://www.douyin.com/', wait_until='domcontentloaded', timeout=15000)
    time.sleep(3)
    print('1. Home:', page.title())

    # JS 移除遮罩
    page.evaluate("""
        () => {
            document.querySelectorAll(
                'div[class*="mask"], div[class*="overlay"], div[class*="dialog"], div[class*="modal"]'
            ).forEach(function(m) { m.remove(); });
        }
    """)

    # 键盘操作
    page.mouse.click(500, 300)
    time.sleep(0.5)
    search_input = page.locator('input').first
    try:
        search_input.click(timeout=5000)
    except:
        page.mouse.click(700, 30)
        time.sleep(0.5)

    # 搜索关键词改为从命令行参数获取
    keyword = sys.argv[1] if len(sys.argv) > 1 else '刷单'

    page.keyboard.type(keyword, delay=100)
    time.sleep(0.5)
    page.keyboard.press('Enter')
    time.sleep(6)

    print(f'2. URL: {page.url[:120]}')
    print(f'   Title: {page.title()}')
    # 方式1: 等待特定选择器
    try:
        page.wait_for_selector('a[href*="video"]', timeout=15000)
        print('   Found video links!')
    except:
        print('   Timeout waiting for video links')

    # 方式2: 滚动触发懒加载
    for i in range(3):
        page.evaluate('window.scrollTo(0, document.body.scrollHeight)')
        time.sleep(2)

    # 方式3: 等待 body 内容增长
    for i in range(10):
        body_len = page.evaluate('() => document.body.innerText.length')
        if body_len > 200:
            break
        time.sleep(1)

    # 检查 DOM
    dom_info = page.evaluate("""
        () => {
            return {
                bodyLen: document.body.innerText.length,
                bodyText: document.body.innerText.substring(0, 800),
                allLinks: document.querySelectorAll('a').length,
                videoLinks: document.querySelectorAll('a[href*=\"video\"]').length,
                sampleHrefs: Array.from(document.querySelectorAll('a')).slice(0, 15).map(a => a.href.substring(0, 100)),
            };
        }
    """)
    for k, v in dom_info.items():
        print(f'   {k}: {v}')

    # 搜索结果通过 JS 渲染，无 a href 链接。从 body text 正则提取
    body_text = page.evaluate('() => document.body.innerText')

    import re
    # 提取搜索结果模式: 时长 + 点赞数 + 描述 + @作者 + 日期
    # 格式: "01:48\n4965\ns单罚款规则...\n@后生电商...\n· 2025年3月26日"
    pattern = re.compile(
        r'(\d{2}:\d{2})\s*\n\s*([\d.]+[亿万]?)\s*\n\s*(.+?)\s*\n\s*@(.+?)\s*\n\s*·\s*(.+?)(?=\n\d{2}:\d{2}|\n相关搜索|\n\s*$)',
        re.DOTALL
    )
    matches = pattern.findall(body_text)

    print(f'\nRESULTS: {len(matches)} items')
    for i, m in enumerate(matches[:10]):
        duration, likes, desc, author, date = m
        desc = desc.replace('\n', ' ').strip()[:100]
        author = author.strip()
        print(f'{i+1}. [{duration}] {desc}')
        print(f'   👍{likes}  @{author}  ·{date.strip()[:20]}')
        print()

    # 也提取"相关搜索"词
    related = re.findall(r'相关搜索\n(.+?)(?=\n\d{2}:\d{2}|\n\s*$)', body_text, re.DOTALL)
    if related:
        print(f'相关搜索: {related[0][:200]}')

    browser.close()
