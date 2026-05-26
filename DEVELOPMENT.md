# BGI 开发指南

## v0.6 更新（2026-05-25）

| 模块 | 变更 |
|------|------|
| 贴吧 Spider | 新增 `collectors/spiders/tieba_spider.py` — Playwright 贴吧关键词搜索 Spider，Cookie 登录、Referer 绕过、搜索结果+帖子详情+回复采集 |
| 贴吧采集器 | 新增 `collectors/tieba_collector.py` — 实现 BaseCollector 接口，将 ParsedTiebaItem 转换为 IntelItem |
| 知乎 Spider | 新增 `collectors/spiders/zhihu_spider.py` — Playwright + JS Cookie 注入 + DOM 解析搜索 Spider，支持回答/评论采集 |
| 知乎采集器 | 新增 `collectors/zhihu_collector.py` — 实现 BaseCollector 接口 |
| 微博反爬增强 | `weibo_spider.py` 新增 UA 池（5个随机轮换）、Cookie 统一 `_load_cookies()` 管理、`--no-sandbox` 参数 |
| Cookie 管理 | `.env.template` 新增 BGI_WEIBO/TIEBA/ZHIHU_COOKIES 配置模板，settings.py 新增对应字段 |
| CLI 扩展 | `main.py` collect 命令新增 `--keywords/-k`、`--max-pages`、`--fetch-replies/--no-fetch-replies` 参数 |
| 采集注册 | `registry.py` 贴吧/知乎改为专用采集器（替换 WebCollector stub） |
| 采集测试 | 新增 `test_tieba_search.py` / `test_zhihu_search.py`，三平台端到端测试验证通过 |
| 三平台反爬对齐 | UA 池 + webdriver 隐藏 + Cookie 注入 + 随机间隔 + 首页预热 + 验证码检测，6 项策略三平台统一 |

### 三平台采集测试结果（2026-05-25 实测）

| 平台 | 采集量/页 | 数据质量 |
|------|:---------:|------|
| 贴吧 | 4~50条 | 帖吧名、用户名、回复数、正文、表情检测、图片检测 |
| 知乎 | 10条 | 问题+摘要+完整回答（含赞数/评论数）、话题标签 |
| 微博 | 20条 | 用户名、UID、时间、内容类型、长文/图片/视频检测（字段最完整） |
| Telegram | - | API ID/Hash 未配置，待补充 |

### 反爬策略对照

| 策略 | 贴吧 | 知乎 | 微博 |
|------|:--:|:--:|:--:|
| UA 池（5个） | ✅ | ✅ | ✅ |
| webdriver 隐藏 | ✅ | ✅ | ✅ |
| Cookie 注入 | ✅ BDUSS | ✅ JS(z_c0) | ✅ SUB |
| 首页预热 | ✅ | ✅ | ✅ |
| 请求间隔 | 1.5~5s | 3~6s | 2.5~5.5s |
| 增量采集 | ✅ | ✅ | ✅ |
| 验证码/重定向检测 | ✅ 标题检测 | ✅ | ✅ 重定向检测 |

---

## v0.5 更新（2026-05-23）

| 模块 | 变更 |
|------|------|
| 微博采集 | 新增 `collectors/weibo_collector.py` — Playwright 微博关键词搜索采集器，支持 Cookie 登录、翻页、HTML 解析 |
| Spider 模块 | 新增 `collectors/spiders/weibo_spider.py` — 通用微博搜索 Spider，可独立使用或通过 WeiboCollector 调用 |
| Milvus 批量 | `milvus_store.py` 新增 `insert_slang_batch()` 方法，支持批量插入黑话向量 |
| 采集注册 | `registry.py` 新增 weibo 平台注册，支持 `--keywords` 和 `--max-pages-per-keyword` 参数 |

---

## v0.4 架构更新（2026-05-22）

| 模块 | 变更 |
|------|------|
| 安全去激活 | 新增 `analyzer/defanger.py` — URL/IP/Email 去激活化安全展示 |
| 多模态处理 | 新增 `cleaner/media_processor.py` — 图片 OCR + 音频 ASR + 视频帧提取 |
| LLM 降级 | `engine.py` 重写 — tenacity 指数退避重试 + 断路器（5 次连续失败切换 L1+L2） |
| HITL 闭环 | `mysql_store.py` 新增 `annotation_log` 表 + 黑话/分类人工修正自动同步 |
| Neo4j v0.4 Schema | 5 种节点标签 + 4 种关系类型 + 共享联系人团伙检测 |
| Mock 数据 | 新增 `scripts/generate_mock_data.py` — 18 套模板覆盖全部意图标签 |
| 测试 | 37 个测试全部通过（新增 10 个） |

---

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
| `__init__.py` | 导出 `BaseCollector` / `IntelItem` / `TelegramCollector` / `WebCollector` / `WeiboCollector` / `TiebaCollector` / `ZhihuCollector` |
| `base.py` | `IntelItem` 数据类（12 个字段）+ `BaseCollector` 抽象基类 |
| `telegram_collector.py` | Telethon 实现：遍历 TG 群消息，提取文本/图片/视频，计算 media hash |
| `web_collector.py` | Scrapy + Playwright 实现：通用网页采集 |
| `weibo_collector.py` | Playwright 实现：微博关键词搜索采集器，支持 `keywords` / `max_pages_per_keyword` / `headless` 参数 |
| `tieba_collector.py` | Playwright 实现：贴吧关键词搜索采集器，将 ParsedTiebaItem 转换为 IntelItem，回复数据序列化为 metadata.replies |
| `zhihu_collector.py` | Playwright 实现：知乎关键词搜索采集器，将 ParsedZhihuItem 转换为 IntelItem，回答/评论数据序列化为 metadata |
| `registry.py` | 平台 → 采集器工厂函数映射表（telegram / weibo / tieba / zhihu / xiaohongshu / forum） |
| `spiders/__init__.py` | 导出 `WeiboSearchSpider` / `TiebaSpider` / `ZhihuSearchSpider` |
| `spiders/weibo_spider.py` | 微博关键词搜索 Spider（Playwright）：UA 池轮换 / Cookie 注入登录 / HTML 卡片解析 / 结构化字段提取（ParsedWeiboItem） |
| `spiders/tieba_spider.py` | 贴吧关键词搜索 Spider（Playwright）：BDUSS Cookie 登录 / Referer 绕过 / 搜索结果 + 帖子详情 + 回复采集 / 表情提取（ParsedTiebaItem + ParsedReply） |
| `spiders/zhihu_spider.py` | 知乎关键词搜索 Spider（Playwright）：JS Cookie 注入 / reload / DOM 解析 SearchResult-Card / 回答 + 评论采集（ParsedZhihuItem + ParssedZhihuComment） |

### `cleaner/` —— 数据清洗层

| 文件 | 说明 |
|------|------|
| `__init__.py` | 导出 `CleaningPipeline` / `MediaProcessor` / `media_processor` |
| `pipeline.py` | `CleaningPipeline` 类：normalize → compute_simhash → is_noise → mark_priority → process |
| `simhash_py.py` | 纯 Python SimHash 64 位指纹实现（中文 bigram + 英文 unigram tokenizer + MD5 哈希加权） |
| `media_processor.py` | 多模态处理：图片 OCR（PaddleOCR 中英文）、视频帧提取+OCR、音频/视频语音转文字（faster-whisper）。懒加载模型，未安装时优雅降级 |

### `analyzer/` —— 分析引擎层

| 文件 | 说明 |
|------|------|
| `__init__.py` | 导出 `IntentClassifier` / `EntityExtractor` / `AnalysisEngine` / `defanger` |
| `classifier.py` | `IntentClassifier`：L1 关键词（20 条 regex）→ L2 RoBERTa（预留）→ L3 LLM API 三级分类。支持 `skip_llm=True` 降级模式 |
| `entity_extractor.py` | `EntityExtractor`：L1 正则（9 种实体类型）→ L2 词典 → L3 Milvus Embedding → L4 LLM 四层级联。新增 `extract_l1_l2_only()` 降级方法 |
| `engine.py` | `AnalysisEngine` 单例：classify → extract → MySQL → Neo4j sync → Milvus embed 全流程编排。内置 **LLM 降级机制**：tenacity 指数退避重试（3 次）+ 断路器（连续 5 次失败自动切换 L1+L2），支持手动 `reset_circuit()` 恢复 |
| `defanger.py` | 安全去激活：URL → `hxxp[://]evil[.]com`、IP → `192[.]168[.]1[.]1`、Email → `bad@phish[.]com`。支持 `defang_text()` 全文本处理 + `refang()` 逆向还原。幂等安全，多次调用不重复加壳 |

### `storage/` —— 存储层

| 文件 | 说明 |
|------|------|
| `__init__.py` | 注释文件（"Storage layer – imports are lazy to allow offline testing"） |
| `mysql_store.py` | `MySQLStore`：6 表 CRUD、daily_stats、list_raw（支持状态/优先级/平台过滤）。**v0.4 新增**：`annotation_log` 表 + `log_annotation()` / `sync_slang_correction()` / `sync_classification_correction()` / `get_pending_annotations()` HITL 闭环反馈方法 |
| `neo4j_store.py` | `Neo4jStore`：**v0.4 精化 Schema** — 5 种节点标签（Intel / Account / Tool / Contact / Link）+ 4 种关系类型（MENTIONS / PROMOTES / USES_CONTACT / CO_OCCURS）。共享联系人团伙发现（`discover_gangs()` / `get_gang_members()`）、pyvis 图数据导出（`get_refined_graph()`）、最短路径查询。向后兼容旧 Entity + EXTRACTED_FROM 模式 |
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
| `pages/intel_list.py` | 情报列表：四维筛选（关键词/平台/风险/优先级）+ 数据表格（显示时自动 defang 恶意链接） |
| `pages/entities.py` | 实体库：按类型 Tab + 统计卡片（URL/IP 类实体自动 defang 显示） |
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
| `test_classifier.py` | 分类器 7 个测试：账号交易/刷单/贷款/赌博关键词命中、未命中、级联策略、`skip_llm` 降级模式 |
| `test_entity_extractor.py` | 实体抽取 8 个测试：手机号/微信/QQ/URL 正则提取、多实体、词典匹配、空文本、`extract_l1_l2_only` 降级方法 |
| `test_defanger.py` | 安全去激活 8 个测试：URL/IP/Email 单独去激活、全文本混合去激活、幂等性验证、逆向还原、空输入边界 |
| `test_weibo_search.py` | 微博搜索采集测试脚本：命令行直接运行，支持自定义关键词和翻页数，输出结构化解析结果 |
| `test_tieba_search.py` | 贴吧搜索采集测试脚本：支持自定义关键词、翻页数、`--no-replies` 开关，输出帖子和回复内容预览 |
| `test_zhihu_search.py` | 知乎搜索采集测试脚本：支持自定义关键词、翻页数、`--no-answers`（快速模式）、`--comments` 开关，输出问题和回答详情 |

### `data/` —— 数据目录

| 路径 | 说明 |
|------|------|
| `slang_dict/seed_slang.json` | 49 条种子黑话（来自 ThreatHunter + 手工标注），7 个分类 |
| `raw/` | 原始采集数据存储（空，运行采集器后生成） |
| `cleaned/` | 清洗后数据存储（空） |
| `models/` | 微调模型文件目录（空，用于存放 RoBERTa checkpoint） |

### `scripts/` —— 工具脚本

| 文件 | 说明 |
|------|------|
| `generate_mock_data.py` | Mock 数据生成器：18 套模板覆盖全部 7 种意图标签，可复现随机种子，支持 `--dry-run` / `--no-neo4j`。用法：`python scripts/generate_mock_data.py -n 200 --seed 42` |
| `import_seed_slang.py` | 种子黑话导入：将 CSV/JSON 格式的黑话批量写入 MySQL `slang_dict` 并嵌入 Milvus。内置 15 条种子数据。用法：`python scripts/import_seed_slang.py --file data/slang.csv` |
| `train_roberta.py` | RoBERTa 微调占位脚本：等待标注数据后用于训练 L2 分类器。用法：`python scripts/train_roberta.py --data data/labeled_intel.csv --epochs 3` |

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

**v0.4 精化 Schema：**

```
节点（5 种标签）：
  Intel     — 情报条目（raw_id 唯一约束）
  Account   — 账号类实体（wechat / qq / alipay）
  Tool      — 工具类实体（外挂 / 脚本 / 接码平台）
  Contact   — 联系方式（phone / email / bank_card）
  Link      — 链接类实体（url / domain / ip）
  （保留旧 Entity 标签用于向后兼容）

关系（4 种类型）：
  MENTIONS    — Intel → Account / Contact（情报提及账号或联系方式）
  PROMOTES    — Intel → Link / Tool（情报推广链接或工具）
  USES_CONTACT — Account → Contact（账号使用某联系方式）
  CO_OCCURS   — Account → Account / Entity → Entity（共享联系人团伙发现）
  （保留旧 EXTRACTED_FROM 用于向后兼容）

团伙检测查询：
  (Account A)-[:USES_CONTACT]->(Contact X)<-[:USES_CONTACT]-(Account B)
  → (Account A)-[:CO_OCCURS]-(Account B)

约束（8 条）：
  Entity.uuid + Intel.raw_id 唯一
  Account.value / Tool.value / Contact.value / Link.value 唯一
  + 3 个精化标签索引
```

### Milvus

```
slang_embeddings  — 384 维黑话向量（COSINE / IVF_FLAT）
intel_embeddings  — 384 维情报向量（COSINE / IVF_FLAT）
```

---

## 开发约定

1. **存储层懒加载** — `engine.py` 和 `entity_extractor.py` 使用 `_mysql()` / `_neo4j()` / `_milvus()` 函数延迟导入，确保离线测试不需要数据库连接
2. **测试独立** — 所有 37 个测试不依赖数据库、不依赖网络，`python -m pytest tests/` 秒级完成
3. **配置集中** — 所有配置项在 `config/settings.py`，通过 `.env` 文件覆盖
4. **环境隔离** — `.env` 不入库，`.env.template` 作为模板
5. **中英混合** — 代码标识符英文，注释/文档中文为主
