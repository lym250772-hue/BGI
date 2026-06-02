# BGI 完整操作流程

> 从零到可演示的完整步骤（采集 → 清洗 → 分析 → 展示）
> 最后更新: 2026-06-03

---

## 环境检查

```bash
cd "E:\pythonProject\2605 灰黑产Agent比赛\BGI"
python --version        # >= 3.11
pip install -r requirements.txt
docker ps               # bagi_mysql, bagi_neo4j, bagi_milvus 等
```

## Step 1: 启动基础设施

```bash
docker compose -f docker/docker-compose.yml up -d
```

## Step 2: 初始化数据库

```bash
python main.py init-db
```

## Step 3: 登录各平台

```bash
python login_edge.py weibo zhihu tieba xiaohongshu douyin
```

浏览器弹出 → 手动扫码 → 终端按 Enter → Cookie 保存到 `data/raw/`。

## Step 4: 采集数据

```bash
# 批量采集（推荐）
python scripts/collect_examples.py --max-pages 5 -k "刷单,接码,跑分,账号出售,代付"

# 或单平台
python main.py collect -p weibo -k "刷单,接码,跑分" --max-pages 5
python main.py collect -p zhihu -k "刷单,接码,跑分" --max-pages 5
python main.py collect -p xiaohongshu -k "刷单,接码" --max-pages 3
python main.py collect -p douyin -k "刷单,接码" --max-pages 3
python main.py collect -p tieba -k "刷单" --max-pages 2
```

## Step 5: 清洗去重

```bash
python main.py clean -l 500
```

HTML归一化 → SimHash去重 → 噪声过滤 → 优先级标记 → 写入 `dwd_clean_intel`。

## Step 6: 分析引擎

```bash
python main.py analyze -l 200
```

L1关键词 → L1.5 Metadata → L2 RoBERTa → L3 LLM → 实体抽取 → 证据提取 → 风险评分 → 黑话归一 → 入库。

> L3 LLM 需要 `.env` 中 `BGI_LLM_API_KEY`。无 Key 自动降级 L1+L2。

## Step 7: 启动 Dashboard

```bash
python main.py ui
```

http://localhost:8501

---

## 快速演示

```bash
python main.py ui
# 总览/ChatBI → 情报池 → 研判工作台 → 知识库 → 系统状态
```

---

## 命令参考

```bash
python main.py init-db              # 初始化数据库
python main.py collect -p <平台> -k "关键词" --max-pages 5  # 采集
python main.py clean -l 500         # 清洗
python main.py analyze -l 200       # 分析
python main.py ui                   # Dashboard
python main.py api                  # FastAPI

python login_edge.py <平台>         # 交互登录
python scripts/collect_examples.py  # 批量样本采集
python -m pytest tests/ -v          # 测试
```

---

## 示例数据

`examples/` 目录含 5 平台 1,076 条真实黑灰产样本：

| 平台 | 条数 | 特点 |
|------|:--:|------|
| 微博 | 380 | 含评论 |
| 知乎 | 375 | 含答案+评论 |
| 小红书 | 180 | 含图片列表 |
| 抖音 | 123 | 含封面+图片 |
| 贴吧 | 18 | 含回复 |
