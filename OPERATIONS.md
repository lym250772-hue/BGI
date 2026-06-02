# BGI 操作手册 — 数据采集与清洗

> 本文档面向数据采集层和清洗层的日常操作，供队友快速上手。

## 1. 环境准备

### Docker 基础设施

```bash
cd BGI/docker
docker compose up -d          # 启动 MySQL + Neo4j + Milvus + etcd + MinIO
docker compose ps              # 检查状态
```

### Python 依赖

```bash
pip install -r requirements.txt
```

### 平台登录（一键交互式，推荐）

**不需要手动复制 Cookie！** 运行下面命令会自动弹出浏览器，手动登录后按 Enter 即可：

```bash
python main.py login -p weibo        # 微博
python main.py login -p zhihu        # 知乎
python main.py login -p tieba        # 贴吧
python main.py login -p xiaohongshu  # 小红书
python main.py login -p douyin       # 抖音
python main.py login -p all          # 依次登录全部平台
```

Cookie 自动保存到 `data/raw/{platform}_cookies.json`，下次采集自动复用。

> **备用手动方式（仅在交互式登录不可用时使用）：**  
> 1. Edge/Chrome 安装 EditThisCookie 扩展  
> 2. 登录目标平台 → 点击扩展图标 → Export → 复制 JSON  
> 3. 保存到 `data/raw/{platform}_cookies.json`

## 2. 数据采集

### 知乎 (稳定)

```bash
# 快速模式 (不含回答, ~20 条/秒)
python main.py collect -p zhihu -k "刷单,接码,出号" --max-pages 3 --no-incremental --no-fetch-replies

# 全量模式 (含回答+评论, ~3 条/秒)
python main.py collect -p zhihu -k "刷单" --max-pages 5 --no-incremental

# 批量关键词 (从文件读取)
python main.py collect -p zhihu --keyword-file data/grey_keywords.json --max-pages 5 --no-incremental

# 无限翻页 (自动采到底)
python main.py collect -p zhihu -k "刷单" --max-pages 0 --no-incremental
```

### 贴吧 (不稳定, 反爬变动中)

```bash
python main.py collect -p tieba -k "刷单" --max-pages 3 --no-incremental
```

### 小红书 (API拦截 + DOM兜底)

```bash
python main.py collect -p xiaohongshu -k "刷单,接码" --max-pages 3 --no-incremental
```

### 抖音 (API直调 + SSR数据 + DOM三路解析)

```bash
python main.py collect -p douyin -k "无人直播,刷单" --max-pages 2 --no-incremental
```

### 命令行参数

| 参数 | 默认 | 说明 |
|------|:----:|------|
| `-p, --platform` | telegram | 平台: zhihu / tieba / weibo |
| `-k, --keywords` | — | 逗号分隔关键词 |
| `--keyword-file` | — | JSON 关键词文件路径 |
| `--max-pages` | 10 | 每词翻页数 (0=无限) |
| `--max-items` | 0 | 每词上限 (0=不限) |
| `--no-fetch-replies` | — | 不采回答/评论 (加速) |
| `--no-incremental` | — | 全量模式 (默认) |
| `--incremental` | — | 增量模式 (只采新内容) |
| `--batch-size` | 100 | 批量入库大小 |

## 3. 数据清洗

```bash
# 清洗所有 RAW_COLLECTED 数据
python main.py clean -l 5000
```

### 保留逻辑

```
输入 → HTML 清洗 → SimHash 去重 → 噪声过滤 → 风险判定

保留条件 (满足任一):
  ✅ 命中 37 个高危关键词 (刷单/诈骗/接码/博彩/外挂...)
  ✅ 含可追溯实体 (微信/QQ/手机/URL/群号/下载链接)

丢弃条件 (同时满足):
  ❌ 未命中高危关键词
  ❌ 无可追溯实体
```

### 保留率参考

约 55% 的数据被保留（取决于关键词命中率）。

## 4. 数据存储结构

### MySQL 表

| 表 | 内容 | 说明 |
|------|------|------|
| `ods_raw_intel` | 原始采集数据 | 证据原件, 不可覆盖 |
| `dwd_clean_intel` | 清洗结果 | 去重+优先级+过滤理由 |
| `dwd_entity` | 抽取实体 | 待分析引擎填充 |

### 评论区关联

```
ods_raw_intel (父帖)
├── id = 94
├── content_raw = "刷单被骗..."
└── metadata = {
      "answers": [{
        "content": "99%的刷单是诈骗...",
        "author_username": "知乎用户",
        "comments": [{
          "author_username": "评论者",
          "content": "我也被骗过..."
        }]
      }]
    }
```

### 给下游的查询

```python
from storage.mysql_store import mysql

# 获取清洗后的高危数据
items = mysql.list_raw(status='CLEANED', limit=100)
# 每条: id, clean_text, source_platform, clean_simhash, priority, metadata

# 提取评论/回复
import json
for item in items:
    meta = json.loads(item['metadata']) if isinstance(item['metadata'], str) else item['metadata']
    replies = meta.get('replies', [])  # 贴吧
    answers = meta.get('answers', [])  # 知乎
```

## 5. 关键词管理

关键词文件: `data/grey_keywords.json`

```json
{
  "quick_keywords": ["刷单", "接码", "出号", ...],
  "keywords": {
    "诈骗类": ["刷单", "刷单返利", ...],
    "引流类": ["接码", "接码平台", ...],
    ...
  }
}
```

新增关键词后直接运行采集即可，不需要改代码。

## 6. 常见问题

| 问题 | 解决 |
|------|------|
| Cookie 过期 | 重新登录平台 → Export EditThisCookie → 覆盖 JSON 文件 |
| 知乎 403 | 等 5 分钟再试，请求太频繁 |
| 贴吧安全验证 | Cookie 可能过期，或 IP 被限 |
| 清洗后数据少 | 检查关键词是否命中 `HIGH_RISK_KEYWORDS` |
| Docker 容器挂了 | `docker compose up -d` |
| MySQL 连不上 | 确认 Docker 已启动 |

## 7. 测试

```bash
python -m pytest tests/ -v    # 37 tests, 全部通过
```
