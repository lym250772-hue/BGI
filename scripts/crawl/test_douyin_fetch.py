"""快速测试 douyin fetch API"""
import sys, json, time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))
from collectors.spiders.douyin_spider import DouyinSearchSpider, generate_xbogus

spider = DouyinSearchSpider(headless=True)
try:
    spider.start()
    print(f"msToken: {spider._msToken[:40]}...")
    print(f"webid: {spider._webid}")

    params = [
        ('device_platform', 'webapp'), ('aid', '6383'), ('channel', 'channel_pc_web'),
        ('search_channel', 'aweme_general'), ('sort_type', '0'), ('publish_time', '0'),
        ('keyword', '无人直播'), ('search_source', 'normal_search'),
        ('query_correct_type', '1'), ('is_filter_search', '0'), ('from_group_id', ''),
        ('offset', '0'), ('count', '5'),
        ('pc_client_type', '1'), ('version_code', '190600'), ('version_name', '19.6.0'),
        ('cookie_enabled', 'true'),
    ]
    if spider._msToken: params.append(('msToken', spider._msToken))
    if spider._webid: params.append(('webid', spider._webid))

    query = '&'.join(f'{k}={v}' for k, v in params)
    xb = generate_xbogus(query)
    full_url = f'https://www.douyin.com/aweme/v1/web/general/search/single/?{query}&X-Bogus={xb}'

    js = f"""
    async () => {{
        const controller = new AbortController();
        setTimeout(() => controller.abort(), 10000);
        try {{
            const resp = await fetch('{full_url}', {{
                method: 'GET', credentials: 'include',
                headers: {{ 'Accept': 'application/json' }},
                signal: controller.signal,
            }});
            const text = await resp.text();
            return {{ ok: resp.ok, status: resp.status, text: text.substring(0, 800) }};
        }} catch(e) {{
            return {{ error: true, message: e.message }};
        }}
    }}
    """
    print("Calling fetch...")
    result = spider._page.evaluate(js)
    print(json.dumps(result, ensure_ascii=False, indent=2))

finally:
    spider.close()
