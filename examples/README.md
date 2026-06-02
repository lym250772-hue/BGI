# 示例数据 — 多源采集真实样本

本目录存放从各平台采集到的真实黑灰产相关样本数据，用于分析引擎开发、测试和演示。

## 采集概况

| 文件 | 平台 | 条数 | 关键词 | 采集技术 | 数据特点 |
|------|------|:--:|------|------|------|
| `weibo_sample.json` | 微博 | 19 | 刷单 | AJAX API (`weibo.com/ajax/statuses/search`) | 含转发/评论/点赞数、weibo_id |
| `zhihu_sample.json` | 知乎 | 20 | 刷单 | Playwright API直调 (`/api/v4/search_v3`) | 含回答内容、投票数、话题标签 |
| `xiaohongshu_sample.json` | 小红书 | 20 | 刷单 | Playwright API拦截 + DOM兜底 | 含收藏/评论数、标签、图片列表 |
| `tieba_sample.json` | 贴吧 | 8 | 刷单 | Playwright DOM解析 (`.thread-content-box`) | 含帖子回复、吧名、thread_id |
| `douyin_sample.json` | 抖音 | 5 | 刷单 | Playwright 首页搜索框 + 正则提取 | 含点赞/评论/分享数、时长、hashtags |
| `telegram_sample.json` | Telegram | ⚠️ | — | Telethon（需 API ID/Hash） | 待配置 |

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

> **注意**: 采集需要有效的 Cookie。如果 Cookie 过期，先运行 `python main.py login -p <平台>` 重新登录。
>
> 采集到的是各平台公开可⻅内容，仅供安全研究和竞赛评估使用。
