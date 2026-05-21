# BGI 开发指南

## 协作开发设置

### 1. 仓库管理员配置

项目使用 GitHub 仓库：https://github.com/lym250772-hue/BGI

**将协作者设为管理员：**
1. 打开 https://github.com/lym250772-hue/BGI/settings/access
2. 点击 「Add people」
3. 输入协作者 GitHub 用户名
4. 角色选择 **Admin**（管理员）
5. 对方接受邀请后即拥有完整仓库权限（push / merge / settings）

### 2. 双方同步开发环境

```bash
# 双方均执行
git clone git@github.com:lym250772-hue/BGI.git
cd BGI

# 启动基础设施
cd docker && docker compose up -d && cd ..

# 安装依赖
pip install -r requirements.txt

# 配置环境变量（各自填写 API Key）
cp .env.template .env
# 编辑 .env 填入 BGI_LLM_API_KEY

# 初始化数据库
python main.py init-db
```

### 3. Git 协作流程

```bash
# 每日开始工作前
git pull origin master

# 创建功能分支
git checkout -b feature/xxx

# 开发 & 提交
git add -A
git commit -m "feat: description"

# 推送分支
git push -u origin feature/xxx

# 在 GitHub 创建 Pull Request → Code Review → Merge
```

### 分支命名规范

| 前缀 | 用途 | 示例 |
|------|------|------|
| `feature/` | 新功能 | `feature/slang-detection` |
| `fix/` | Bug 修复 | `fix/mysql-connection` |
| `refactor/` | 重构 | `refactor/classifier-cascade` |
| `docs/` | 文档 | `docs/api-spec` |

### Commit 规范

```
feat: 添加 RoBERTa 分类器微调脚本
fix: 修复 SimHash 去重阈值计算
refactor: 重构实体抽取级联逻辑
docs: 更新 API 文档
test: 添加分类器边界用例
```

**注意：** 不要提交 `.env` 文件（已加入 .gitignore）。不要提交 `data/raw/`、`data/cleaned/` 中的采集数据。

---

## 项目目录 & 文件说明

### 根目录

| 文件 | 说明 |
|------|------|
| `main.py` | Click CLI 入口，6 个命令：`init-db` / `collect` / `clean` / `analyze` / `run` / `ui` |
| `schema.py` | 全局数据模型与常量：7 个枚举类型、4 个 Pydantic Model、风险关键词列表、子标签映射 |
| `requirements.txt` | Python 依赖清单（已排除 simhash-py，使用纯 Python 回退方案） |
| `.env.template` | 环境变量模板，实际使用需复制为 `.env` |
| `.env` | 实际环境变量（不纳入版本控制） |
| `.gitignore` | Git 忽略规则 |
| `README.md` | 项目概览与快速开始指南 |
| `DEVELOPMENT.md` | 本文件——开发规范与协作指南 |

### `config/` —— 全局配置

| 文件 | 说明 |
|------|------|
| `__init__.py` | 包标识（空文件） |
| `settings.py` | Pydantic Settings：MySQL / Neo4j / Milvus 连接配置，LLM API 配置，采集/清洗/分类阈值，路径配置 |

### `schema.py` —— 数据模型

7 个枚举：
- `Platform`（8 个平台）
- `ContentType`（text / image / gif / video / audio）
- `Priority`（normal / high / critical）
- `IntelStatus`（pending / cleaned / analyzed / discarded）
- `IntentLabel`（7 大类：诈骗/引流/作弊/账号黑产/内容违规/工具交易/直播违规）
- `EntityType`（11 种实体类型）
- `ClassificationMethod` / `ExtractionMethod`
- `SUBLABEL_MAP`：7 → 20 子类映射
- `HIGH_RISK_KEYWORDS`：37 个高危关键词
- 4 个 Pydantic Model：`RawIntel` / `ClassificationResult` / `ExtractedEntity` / `CheatScript`

### `collectors/` —— 数据采集层

| 文件 | 说明 |
|------|------|
| `__init__.py` | 包标识（空文件） |
| `base.py` | `IntelItem` 数据类（12 个字段）+ `BaseCollector` 抽象基类 |
| `telegram_collector.py` | Telethon 实现：遍历 TG 群消息，提取文本/图片/视频，计算 media hash |
| `web_collector.py` | Scrapy + Playwright 实现：通用网页采集 |
| `registry.py` | 平台 → 采集器工厂函数映射表 |

### `cleaner/` —— 数据清洗层

| 文件 | 说明 |
|------|------|
| `__init__.py` | 包标识（空文件） |
| `pipeline.py` | `CleaningPipeline` 类：normalize → compute_simhash → is_noise → mark_priority → process |
| `simhash_py.py` | 纯 Python SimHash 64 位指纹实现（中文 bigram + 英文 unigram tokenizer + MD5 哈希加权） |

### `analyzer/` —— 分析引擎层

| 文件 | 说明 |
|------|------|
| `__init__.py` | 导出 `IntentClassifier` / `EntityExtractor` / `AnalysisEngine` |
| `classifier.py` | `IntentClassifier`：L1 关键词（16 条 regex）→ L2 RoBERTa（预留）→ L3 LLM API 三级分类 |
| `entity_extractor.py` | `EntityExtractor`：L1 正则（8 种）→ L2 词典 → L3 Milvus Embedding → L4 LLM 四层级联 |
| `engine.py` | `AnalysisEngine` 单例：classify → extract → MySQL → Neo4j sync → Milvus embed 全流程编排 |

### `storage/` —— 存储层

| 文件 | 说明 |
|------|------|
| `__init__.py` | 注释文件（"Storage layer – imports are lazy to allow offline testing"） |
| `mysql_store.py` | `MySQLStore`：6 表 CRUD、daily_stats、list_raw（支持状态/优先级/平台过滤） |
| `neo4j_store.py` | `Neo4jStore`：节点 upsert、关系创建、co-occurrence 边、团伙发现（共享实体模式）、最短路径 |
| `milvus_store.py` | `MilvusStore`：slang_embeddings + intel_embeddings 两个集合，COSINE 相似度检索 |

### `api/` —— API 服务层

| 文件 | 说明 |
|------|------|
| `__init__.py` | 包标识（空文件） |
| `server.py` | FastAPI 应用：CORS 中间件 + `/api/stats` `/api/intel` `/api/entities` `/api/entities/{id}/graph` `/api/slang` `/api/cheat-scripts` `/health` |

### `ui/` —— 可视化仪表盘

| 文件 | 说明 |
|------|------|
| `__init__.py` | 包标识（空文件） |
| `app.py` | Streamlit 主入口：主题注入、侧边栏导航、页面路由 |
| `theme.py` | 莫兰迪配色系统：色板常量、CSS 模板、工具函数 |
| `pages/__init__.py` | 包标识（空文件） |
| `pages/dashboard.py` | 仪表盘：KPI 卡片、风险分布柱状图、最近情报、系统状态 |
| `pages/intel_list.py` | 情报列表：四维筛选（关键词/平台/风险/优先级）+ 数据表格 |
| `pages/entities.py` | 实体库：按类型 Tab + 统计卡片 |
| `pages/graph.py` | 知识图谱：Neo4j 查询 + pyvis 力导向图 |
| `pages/cheat_scripts.py` | 作弊剧本：LLM 生成滥用链路 + 工具 + 对抗建议 |
| `pages/slang_dict.py` | 黑话词典：搜索 + 分类筛选 + 数据表格 |

### `docker/` —— 容器编排

| 文件 | 说明 |
|------|------|
| `docker-compose.yml` | 6 容器定义：MySQL 8.0 / Neo4j 5.20 / Milvus 2.4 / etcd / MinIO / Attu |
| `mysql_init/01_schema.sql` | MySQL 初始化 DDL：6 张业务表，utf8mb4，中文注释 |

### `tests/` —— 单元测试

| 文件 | 说明 |
|------|------|
| `__init__.py` | 包标识（空文件） |
| `test_cleaner.py` | 清洗管道 14 个测试：HTML 剥离、空白折叠、SimHash 确定性、海明距离、噪声检测、优先级标记、全流程 |
| `test_classifier.py` | 分类器 6 个测试：账号交易/刷单/贷款/赌博关键词命中、未命中、级联策略 |
| `test_entity_extractor.py` | 实体抽取 7 个测试：手机号/微信/QQ/URL 正则提取、多实体、词典匹配、空文本 |

### `data/` —— 数据目录

| 路径 | 说明 |
|------|------|
| `slang_dict/seed_slang.json` | 49 条种子黑话（来自 ThreatHunter + 手工标注），7 个分类 |
| `raw/` | 原始采集数据存储（空，运行采集器后生成） |
| `cleaned/` | 清洗后数据存储（空） |
| `models/` | 微调模型文件目录（空，用于存放 RoBERTa checkpoint） |

### `scripts/` —— 工具脚本

预留目录，用于数据迁移、模型训练、批量导入等辅助脚本。

---

## 数据库初始化结构

### MySQL (bagi_intel)

```
raw_data          — 原始情报（主表）
analysis_results  — 分类结果
entities          — 抽取实体
slang_dict        — 黑话词典（种子数据：49 条）
cheat_scripts     — 作弊剧本
annotation_log    — 人工标注日志
```

### Neo4j

```
节点：Intel（情报）、Entity（实体）
关系：EXTRACTED_FROM（实体←情报）、CO_OCCURS（实体共现）
约束：Entity.uuid 唯一、Intel.raw_id 唯一
```

### Milvus

```
slang_embeddings  — 384 维黑话向量（COSINE / IVF_FLAT）
intel_embeddings  — 384 维情报向量（COSINE / IVF_FLAT）
```

---

## 开发约定

1. **存储层懒加载** — `engine.py` 和 `entity_extractor.py` 使用 `_mysql()` / `_neo4j()` / `_milvus()` 函数延迟导入，确保离线测试不需要数据库连接
2. **测试独立** — 所有 27 个测试不依赖数据库、不依赖网络，`python -m pytest tests/` 秒级完成
3. **配置集中** — 所有配置项在 `config/settings.py`，通过 `.env` 文件覆盖
4. **环境隔离** — `.env` 不入库，`.env.template` 作为模板
5. **中英混合** — 代码标识符英文，注释/文档中文为主
