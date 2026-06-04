# 示例数据 — 多源采集真实样本

本目录存放从各平台采集到的真实黑灰产相关样本数据，用于分析引擎开发、测试和演示。

## 采集概况（2026-06-03 最终版）

| 文件 | 平台 | 条数 | 关键词 | 采集技术 | 评论 |
|------|------|:--:|------|------|:--:|
| `weibo_sample.json` | 微博 | **1,768** | 48黑话词 | AJAX API | ✅ |
| `zhihu_sample.json` | 知乎 | **1,607** | 48黑话词 | HTTP API | ✅ |
| `xiaohongshu_sample.json` | 小红书 | **2,556** | 48黑话词 | SSR提取 + 可见浏览器 | ✅ |
| `douyin_sample.json` | 抖音 | **1,167** | 48黑话词 | 可见浏览器+X-Bogus API | ✅ |
| `tieba_sample.json` | 贴吧 | **1,141** | 48黑话词 | JSON API (~10条/秒) | 🔲 |
| `telegram_sample.json` | Telegram | — | — | Telethon（需 API ID/Hash） | — |

> **合计**: **8,239 条** / ~21MB / 5 平台 / 48 黑话关键词全覆盖

### 48个黑话关键词
```
714高炮, AB贷, 上车, 下车, 云手机, 人脸, 代下, 代理IP, 众包, 八件套,
养号, 出号, 刷单, 千粉, 卡商, 反卤, 发卡, 可开播, 号商, 四件套,
大肉, 引流, 打码, 报单, 挂机, 接码, 搬砖, 撞库, 数字人, 料商,
无人直播, 无损套, 日结, 模拟器, 水房, 洗号, 狗推, 猫池, 白户,
破盾, 羊头, 羊腿, 群控, 薅羊毛, 融车, 跑分, 车手, 黄牛
```

## 数据格式

所有平台统一使用 IntelItem 格式，含 `comments` 评论数组。详见 `collectors/base.py` 和 `collectors/normalizer.py`。

```json
{
  "platform": "xiaohongshu",
  "post_id": "67b7216c0000000009014ba3",
  "content_raw": "【标题】香港拆单任务真相曝光...",
  "source_url": "https://www.xiaohongshu.com/explore/...?xsec_token=...",
  "author_username": "香港警察",
  "like_count": 121, "comment_count": 112,
  "comments": [{"id":"...", "author_username":"...", "content":"...", "type":"comment"}],
  "tags": ["刷单"], "image_urls": ["https://..."],
  "metadata": {"note_id": "...", "xsec_token": "...", "has_image": true}
}
```

## 采集命令

```bash
# 微博+知乎+贴吧（快速 HTTP）
python scripts/collect_examples.py -k "关键词" --platforms weibo,zhihu,tieba --max-pages 5

# 小红书（可见浏览器，需手动过验证码）
python scripts/crawl/xiaohongshu_batch.py

# 抖音（可见浏览器，需 msToken）
python scripts/crawl/douyin_batch.py

# 带评论采集
python scripts/collect_examples.py --platforms xiaohongshu --with-comments
python scripts/crawl/douyin_visible_collect.py -k "关键词" --with-comments
```
