# 示例数据 — 多源采集真实样本

本目录存放从各平台采集到的真实黑灰产相关样本数据，用于分析引擎开发、测试和演示。

## 采集概况

| 文件 | 平台 | 条数 | 关键词 | 采集技术 | 数据特点 |
|------|------|:--:|------|------|------|
| `weibo_sample.json` | 微博 | 380 | 刷单/接码/跑分/账号出售/代付 | AJAX API | 含评论(71条)、转发/点赞数 |
| `zhihu_sample.json` | 知乎 | 375 | 刷单/接码/跑分/账号出售/代付 | 纯HTTP API | 含答案(145条)+评论(96条)、话题标签 |
| `xiaohongshu_sample.json` | 小红书 | 180 | 刷单/接码/跑分 | Playwright API拦截+DOM | 含图片列表、收藏/评论数、标签 |
| `douyin_sample.json` | 抖音 | 123 | 刷单/接码/跑分 | Playwright 首页搜索+正则 | 含图片列表、视频封面、点赞/分享数 |
| `tieba_sample.json` | 贴吧 | 18 | 刷单/接码/跑分 | Playwright DOM解析 | 含帖子回复、吧名、thread_id |
| `telegram_sample.json` | Telegram | — | — | Telethon（需 API ID/Hash） | 待配置 |

> **合计**: 1,076 条 / 1.4MB / 5 平台

## 数据格式

每条数据遵循 `IntelItem` 格式（`collectors/base.py`），核心字段：

```json
{
  "platform": "weibo",
  "content_raw": "原始正文内容...",
  "content_type": "text",
  "source_url": "https://weibo.com/...",
  "author_uid": "作者UID",
  "author_username": "作者昵称",
  "collected_at": "2026-06-02T22:19:xx",
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
