# 示例数据 — 多源采集真实样本

本目录存放从各平台采集到的真实黑灰产相关样本数据，用于分析引擎开发、测试和演示。

## 采集概况

| 文件 | 平台 | 条数 | 关键词 | 采集技术 | 数据特点 |
|------|------|:--:|------|------|------|
| `weibo_sample.json` | 微博 | 173 | 刷单/接码/账号出售 | AJAX API | 含评论、转发/点赞数 |
| `zhihu_sample.json` | 知乎 | 169 | 刷单/接码/账号出售 | 纯HTTP API | 含答案+评论、话题标签 |
| `tieba_sample.json` | 贴吧 | **171** 🚀 | 刷单/接码/账号出售 | **JSON API (~10条/秒)** | 含图片、吧名、回复数 |
| `xiaohongshu_sample.json` | 小红书 | **188** 🆕 | 刷单/接码/账号出售 | **SSR提取 (window.__INITIAL_STATE__)** | 含图片、互动数据 |
| `douyin_sample.json` | 抖音 | ⚠️ Spider待修 | — | Playwright 首页搜索+正则 | 含图片列表、视频封面、点赞/分享数 |
| `telegram_sample.json` | Telegram | — | — | Telethon（需 API ID/Hash） | 待配置 |

> **合计**: 701 条 / ~1.5MB / 4 平台（2026-06-03 更新，统一 IntelItem 格式）
> 小红书从 API拦截改为 SSR 提取（window.__INITIAL_STATE__），解决登录后内容为空的问题
> 抖音需 `python login_edge.py douyin` + Spider修复

## 🆕 贴吧 API 突破

贴吧已从 Playwright DOM 解析（0.03条/秒）升级为纯 HTTP JSON API（~10条/秒），
本次采集 166 条仅用 ~15 秒（旧方案需 ~90 分钟）。
新 Spider: `collectors/spiders/tieba_api_spider.py`
测试脚本: `python scripts/crawl/test_tieba_api.py`

## 数据格式

**所有平台统一使用 `IntelItem` 格式**（`collectors/base.py` + `collectors/normalizer.py`）。

### 统一字段结构

```json
{
  "platform": "weibo",
  "post_id": "5305700962275305",
  "content_raw": "原始正文内容...",
  "content_type": "text",
  "source_url": "https://weibo.com/...",
  "author_uid": "作者UID",
  "author_username": "作者昵称",
  "collected_at": "2026-06-03T04:34:xx",
  "like_count": 0,
  "comment_count": 0,
  "share_count": 0,
  "collect_count": 0,
  "comments": [
    {
      "id": "评论ID",
      "author_uid": "",
      "author_username": "评论者",
      "content": "评论内容",
      "like_count": 0,
      "reply_to": "",
      "created_at": "",
      "type": "comment"
    }
  ],
  "tags": ["标签1", "标签2"],
  "image_urls": ["https://img1.jpg"],
  "video_cover_url": "",
  "metadata": { /* 平台特定字段 */ }
}
```

### 各平台映射

| 统一字段 | 微博 | 知乎 | 贴吧 | 小红书 | 抖音 |
|------|------|------|------|------|------|
| `post_id` | weibo_id | answer_id | thread_id | note_id | aweme_id |
| `like_count` | attitudes_count | voteup_count | like_num | like_count | like_count |
| `comment_count` | comments_count | comment_count | reply_count | comment_count | comment_count |
| `comments` | ✅ 评论 | ✅ 答案+评论 | 🔲 预留 | 🔲 预留 | 🔲 预留 |
| `tags` | — | topics | [bar_name] | tags | hashtags |
| `image_urls` | — | image_list | image_urls | image_list | image_list |

> 🔲 预留 = 评论采集暂未实现，字段已留好供后续接入
  "keyword": "刷单",
  "metadata": { "weibo_id": "...", "reposts_count": 0, ... }
}
```

## 重新采集

```bash
# 单平台
python scripts/collect_examples.py --platforms weibo --max-pages 2 -k "刷单"

# 全平台（需先 docker compose up -d 启动基础设施）
python scripts/collect_examples.py --max-pages 2

# 自定义关键词
python scripts/collect_examples.py -k "接码,跑分,账号出售" --max-pages 1
```

> **注意**: 采集需要有效的 Cookie。如果 Cookie 过期，运行 `python login_edge.py <平台>` 重新登录（如 `python login_edge.py tieba`）。
>
> 采集到的是各平台公开可⻅内容，仅供安全研究和竞赛评估使用。
