# 示例数据 — 多源采集真实样本

本目录存放从各平台采集到的真实黑灰产相关样本数据，用于分析引擎开发、测试和演示。

## 采集概况（2026-06-08 v4.2 最终版）

| 文件 | 平台 | 类型 | 条目 | 评论 | 采集技术 |
|------|------|:--:|:--:|:--:|------|
| `weibo_sample.json` | 微博 | 内容 | 1,768 | 2,461 | AJAX API ~8/s |
| `zhihu_sample.json` | 知乎 | 内容 | 1,607 | 10,326 | HTTP API ~3-5/s |
| `xiaohongshu_sample.json` | 小红书 | 内容 | 2,556 | 2,986 | SSR + v3持久化浏览器 |
| `douyin_sample.json` | 抖音 | 内容 | 1,167 | 1,267 | X-Bogus + v3持久化浏览器 |
| `tieba_sample.json` | 贴吧 | 内容 | 1,141 | 876 | JSON API ~10/s + DOM回复 |
| `xianyu_sample.json` 🆕 | 闲鱼 | 二手/众包 | 1,389 | — | v3持久化浏览器 + DOM |
| `qq_group_sample.json` 🆕 | QQ群 | 社交IM | 620 | — | NapCatQQ WebSocket |
| ~~`telegram_sample.json`~~ | Telegram | — | — | — | 已停用 |

> **合计**: **10,248条目 / 17,916评论** / 7品类 / 48黑话关键词

### 48个黑话关键词
```
714高炮, AB贷, 上车, 下车, 云手机, 人脸, 代下, 代理IP, 众包, 八件套,
养号, 出号, 刷单, 千粉, 卡商, 反卤, 发卡, 可开播, 号商, 四件套,
大肉, 引流, 打码, 报单, 挂机, 接码, 搬砖, 撞库, 数字人, 料商,
无人直播, 无损套, 日结, 模拟器, 水房, 洗号, 狗推, 猫池, 白户,
破盾, 羊头, 羊腿, 群控, 薅羊毛, 融车, 跑分, 车手, 黄牛
```

## 数据格式

所有平台统一使用 IntelItem 格式。详见 `collectors/base.py` 和 `collectors/normalizer.py`。

```json
{
  "platform": "xianyu",
  "content_raw": "【标题】抖音涨粉服务 真人粉不掉...",
  "source_url": "https://www.goofish.com/item?id=xxx",
  "author_uid": "user123", "author_username": "涨粉专家",
  "price": 50.0, "seller_rating": "信用极好", "location": "浙江",
  "like_count": 10, "comment_count": 3,
  "tags": ["涨粉"], "image_urls": ["https://..."],
  "metadata": {"item_id": "xxx", "keyword": "涨粉", "price": 50.0}
}
```

QQ群消息使用相同格式，`group_id` 存储群号，`metadata` 含群名/发送者等信息。

## 采集命令

```bash
# 内容平台（HTTP快速采集）
python scripts/collect_examples.py -k "刷单,接码" --platforms weibo,zhihu,tieba --max-pages 5

# 小红书/抖音（v3持久化浏览器）
python scripts/collect_examples.py -k "刷单" --platforms xiaohongshu,douyin --max-pages 3

# 闲鱼（v3持久化浏览器，需首次登录）
python main.py login-xianyu
python scripts/collect_examples.py -k "账号交易,涨粉" --platforms xianyu --max-pages 2

# QQ群（需NapCatQQ）
python scripts/qq_fetch_history.py --count 500                                 # 独立历史拉取脚本
python main.py collect -p qq_group --mode listen --duration 60                 # 仅监听
python main.py collect -p qq_group --mode fetch --fetch-count 200              # 仅拉历史
python main.py collect -p qq_group --mode both --fetch-count 300 --duration 30 # 混合模式(推荐)

# 全量黑话关键词采集
python scripts/collect_xianyu_full.py

# 评论采集
python scripts/crawl/xiaohongshu_comments_v3.py --max 200
python scripts/crawl/douyin_comments_v3.py --max 200
```
