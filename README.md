# BGI — 黑灰产情报分析 Agent

BGI 是一套面向黑灰产情报场景的**全链路自动化分析系统**，覆盖数据采集、智能清洗、风险研判、实体抽取、知识图谱和可视化展示的完整闭环。项目参加字节跳动 AI 全栈挑战赛（AI 安全系统赛道）。

**核心定位**：把散落在多个互联网平台的黑灰产相关文本，自动转化为可查询、可扩线、可复核的结构化情报线索库。

---

## 1. 项目概述

### 1.1 解决什么问题

黑灰产情报分散在微博、知乎、小红书、抖音、贴吧、闲鱼、QQ群等多个平台，格式各异、噪声混杂。安全分析人员面临三个核心痛点：

| 痛点 | 传统方式 | BGI 方案 |
|------|---------|---------|
| **采集分散** | 逐平台手动搜索、截图留存 | 7平台统一采集器，产出标准化 IntelItem 格式 |
| **噪声干扰** | 大量广告、重复内容需人工筛选 | 6步零LLM清洗管道，作者感知去重，平台专属噪声过滤 |
| **分析耗时** | 逐条阅读、手工提取实体和关联 | 三级分类 + 四级实体抽取 + 图谱扩线，全自动完成 |
| **主动情报缺失** | 只能被动等待公开信息 | AI 钓鱼人物主动接触灰产卖家，获取一手情报 |

### 1.2 完整链路

```
┌──────────────┐    ┌──────────────┐    ┌──────────────┐    ┌──────────────┐
│  数据采集层   │ →  │  数据清洗层   │ →  │  智能研判层   │ →  │  展示与交互   │
│              │    │              │    │              │    │              │
│ 7平台采集器   │    │ 作者感知去重   │    │ 三级风险分类   │    │ 8页面仪表盘   │
│ 统一IntelItem │    │ 平台噪声过滤   │    │ 四级实体抽取   │    │ 一键全流程    │
│ AI钓鱼人物    │    │ 内容角色分类   │    │ 黑话归一发现   │    │ 流式对话模拟  │
│ 北京时间戳    │    │ Emoji语义翻译 │    │ 证据+风险评分  │    │ ChatBI 问答   │
└──────────────┘    └──────────────┘    └──────────────┘    └──────────────┘
                              │
                      ┌───────┴───────┐
                      │   存储与知识层  │
                      │ MySQL Neo4j    │
                      │ Milvus Doris   │
                      └───────────────┘
```

### 1.3 关键数字

| 指标 | 数值 |
|------|:----:|
| 采集平台 | 7 个 |
| 样本数据 | 10,248 条 |
| Python 文件 | ~120 个 |
| Streamlit 页面 | 8 个 |
| 黑话词典 | 48 个关键词 |
| AI 钓鱼人物 | 3 个 Profile |
| 数据流水线 | 采→洗→研→库 全自动 |

---

## 2. 系统架构

### 2.1 技术栈

| 层次 | 技术 | 说明 |
|------|------|------|
| 数据采集 | HTTP API + Playwright + WebSocket | 纯HTTP(微博/知乎)、持久化浏览器(小红书/闲鱼/抖音)、WebSocket(QQ群) |
| 文本清洗 | Python (SimHash + 正则 + Emoji映射) | 零LLM调用，6步管道 |
| 风险分类 | L1关键词 → L2 RoBERTa → L3 LLM (DeepSeek) | 三级级联，自动降级 |
| 实体抽取 | 正则 → 词典 → Milvus向量 → LLM | 四级级联 |
| 存储 | MySQL + Neo4j + Milvus + Doris | ODS/DWD/DIM/ADS 分层 |
| 服务 | FastAPI + Streamlit | RESTful API + 仪表盘 |
| 部署 | Docker Compose | 一键启动全部基础设施 |

### 2.2 数据流转

```
原始数据 (各平台文本)
    │
    ▼
ods_raw_intel         状态: RAW_COLLECTED
    │
    ├─ 清洗通过 ──→  状态: CLEANED     ──→ 进入研判队列
    ├─ 媒体占位 ──→  状态: MEDIA_ONLY   ──→ 保留待OCR/ASR
    ├─ 相似内容 ──→  状态: SIMILAR      ──→ 保留(跨作者情报信号)
    └─ 噪声/重复 ──→ 状态: DISCARDED    ──→ 不进入后续
         │
         ▼
dwd_clean_intel       清洗结果：clean_text + simhash + 内容角色
         │
         ▼
研判引擎 (state_machine)
    ├─ classify          风险分类 (L1→L2→L3)
    ├─ extract_entities  实体抽取 (正则→词典→向量→LLM)
    ├─ graph_expand      图谱扩线 (Neo4j)
    ├─ slang_normalize   黑话归一 + 候选发现
    ├─ extract_evidence  证据片段提取
    ├─ risk_score        风险评分
    └─ generate_report   摘要与处置建议
         │
         ▼
多库同步: MySQL(dwd_intel_analysis + dwd_entity) + Neo4j + Milvus + Doris
         │
         ▼
前端展示: 情报池 / 研判工作台 / 知识库 / ChatBI / 系统状态
```

---

## 3. 模块详解

### 3.1 数据采集层 (`collectors/`)

**7 平台全覆盖**，统一输出 `IntelItem` 格式：

| 平台 | 品类 | 采集技术 | 速度 | 评论采集 |
|------|:--:|------|:--:|:--:|
| 微博 | 内容社区 | AJAX API (纯HTTP) | ~8条/s | ✅ |
| 知乎 | 内容社区 | 浏览器内 fetch API | ~5条/s | ✅ |
| 贴吧 | 论坛 | JSON API + DOM | ~10条/s | ✅ |
| 小红书 | 内容社区 | v3持久化浏览器 + SSR提取 | ~0.5条/s | ✅ |
| 抖音 | 短视频 | X-Bogus签名 + 浏览器内fetch | ~0.5条/s | ✅ |
| 闲鱼 | 二手交易 | v3持久化浏览器 + DOM解析 | ~0.3条/s | — |
| QQ群 | 社交IM | NapCatQQ WebSocket + HTTP | 实时/批量 | — |

**统一 IntelItem 格式**（`collectors/base.py`）：

```
platform | content_raw | content_type | source_url | author_uid | author_username
group_id | collected_at(北京时间) | like_count | comment_count | share_count
comments | image_urls | tags | price | location | metadata
```

**设计亮点**：
- 所有平台采集时间统一使用北京时间（`now_bjt()`）
- 反爬6件套：UA池 + webdriver隐藏 + Cookie注入 + 随机间隔 + 首页预热 + 验证码检测
- 增量采集：按关键词记录时间戳，断点续采
- QQ群双模式：被动监听(WebSocket) + 主动拉取历史消息(HTTP)

### 3.2 主动情报收集 (`persona/`)

**AI 钓鱼人物引擎** — 不是被动等待数据，而是主动伪装身份接触灰产卖家：

| 人物 | 身份 | 目标 |
|------|------|------|
| 🛒 电商卖家小张 | 刚开淘宝店的个体户 | 接触涨粉/刷单/解封服务卖家 |
| 🎓 大学生小李 | 想找兼职的学生 | 接触刷单/水军招募团队 |
| 📱 自媒体王姐 | 账号被封的自媒体人 | 接触账号解封/交易服务 |

每个人物配置为 YAML 文件，包含完整的行为设定：

```
identity (身份) → conversation_style (对话风格) → safety (安全护栏) → intelligence_goals (情报目标)
```

**安全护栏（7层）**：
- 禁止真实支付、禁止透露真实身份、禁止鼓励违法行为
- 外出/入站消息双向审查
- 4类退出条件（要求先付款、要求提供证件、要求加私聊、涉及违法内容）
- 违规触发后自动使用安全兜底消息

**技术实现**：
- 流式生成器模式（`run_conversation_stream`），对话逐轮实时刷新
- 支持角色字段级自定义覆盖（`profile_override`），不影响原始 YAML
- 对话完成后 LLM 自动提取结构化情报（服务/定价/支付方式/联系方式/风险指标）

### 3.3 数据清洗层 (`cleaner/`)

**6步零LLM管道**，核心创新是**作者感知去重**：

```
原始文本
  ├─ Step 0: Emoji语义翻译   100+映射，8大类别，追加式翻译
  ├─ Step 1: 平台感知过滤     7平台专属规则 + 通用噪声 + 误匹配检测
  ├─ Step 2: 文本规范化       HTML/Unicode/零宽字符/全半角/URL简化
  ├─ Step 3: 作者感知去重 ⭐  同作者+相似=丢弃 | 不同作者+相似=情报保留
  │          自适应阈值: <30字→0, ≥80字→3
  ├─ Step 4: 噪声评分         12维度(0-1)，短文本含情报词免罚
  └─ Step 5: 优先级标记       高危关键词→HIGH
```

**作者感知去重 vs 传统去重**：

| 场景 | 传统SimHash | BGI 作者感知 |
|------|:----------:|:----------:|
| 同一新闻6家媒体转发 | 删5条 → 情报丢失 | **全部保留**（跨作者=情报信号） |
| 同一卖家重复发广告 | 判重丢弃 | 判重丢弃（同作者=真正重复） |
| QQ群 [image] 消息 | 判噪声丢弃 | **MEDIA_ONLY**（保留待OCR） |
| 短消息含情报词 | 因"文本短"罚分 | **免罚**（检测到情报关键词） |

**内容角色五分类**（零LLM）：

```
actor(灰产从业者) | victim(受害者) | media(媒体) | police(警方) | unknown(未知)
```

**平台专属过滤**：

| 平台 | 特殊处理 |
|------|---------|
| QQ群 | Q群管家/QQ安全中心等系统账号消息直接丢弃(作者名过滤) |
| QQ群 | [CQ:face]表情码去除、筹备中bot消息模式匹配 |
| 微博 | 转发链去除、话题#保留 |
| 通用 | 硬广告关键词过滤 + 情报信号词保护(淘宝/出租/预付/不封号/风控/上号) |

### 3.4 智能研判层 (`analyzer/`)

研判引擎基于**状态机 Agent**，按序执行，根据中间结果动态决策：

```
Step 1: classify         风险分类 (L1关键词→L2 RoBERTa→L3 LLM)
Step 2: extract_entities 实体抽取 (正则→词典→Milvus向量→LLM)
Step 3: decide_tools     工具决策 (根据已有结果决定后续步骤)
Step 4: graph_expand     图谱扩线 (有可扩线实体才执行)
Step 5: slang_normalize  黑话归一 + 新黑话候选发现
Step 6: extract_evidence 证据片段提取
Step 7: risk_score       综合风险评分
Step 8: generate_report  摘要与处置建议
Step 9: persist          多库同步写入
```

**风险分类三级级联**：
- L1 规则层：从 `config/risk_rules.yaml` 加载关键词/正则/组合规则
- L2 小模型层：RoBERTa 文本分类（可训练，`scripts/modeling/train_roberta.py`）
- L3 LLM层：前两层无法判断时调用 DeepSeek，支持自动降级

**实体抽取四级级联**：
- L1 正则：手机号/微信/QQ/邮箱/URL/域名/IP/银行卡/支付宝/虚拟币钱包
- L2 词典：MySQL `dim_slang_dict` 已知黑话
- L3 向量：Milvus 相似黑话检索
- L4 LLM：复杂工具名/风险标签/隐晦黑话

**黑话处理**：
- 已知黑话命中 `dim_slang_dict` → 输出标准释义
- 疑似新黑话由 embedding/LLM 发现 → 写入候选状态 → 前端"知识库"待人工确认
- 形成"发现 → 候选 → 确认 → 入库"的数据飞轮

### 3.5 知识图谱 (`storage/neo4j_store.py`)

Neo4j 保存实体和关系，用于扩线发现：

**6类节点**：Intel(情报) | Account(账号) | Contact(联系方式) | Link(链接) | Tool(工具) | Slang(黑话)

**5类关系**：USES_ACCOUNT | USES_CONTACT | PROMOTES_LINK | PROMOTES_TOOL | USES_SLANG | CO_OCCURS

图谱扩线回答三个核心问题：
1. 当前账号/链接以前是否出现过？
2. 是否和其他账号共享联系方式/链接/工具？
3. 能否形成疑似团伙或作恶链路？

### 3.6 多库存储

| 存储 | 角色 | 内容 |
|------|------|------|
| **MySQL** | 主业务库 | ods_raw_intel(原始) → dwd_clean_intel(清洗) → dwd_intel_analysis(研判) → dwd_entity(实体) → dim_slang_dict(黑话词典) → analysis_job(任务) |
| **Neo4j** | 图谱扩线 | 实体节点 + 关系边，支持团伙关联发现 |
| **Milvus** | 向量检索 | slang_embeddings(黑话相似) + intel_embeddings(情报相似) |
| **Doris** | OLAP聚合 | intel_analysis_wide(宽表)，ChatBI 数据底座 |

Doris/Milvus 不可用时自动降级，不影响核心流程。

---

## 4. 前端界面 (`ui/`)

启动：`python main.py ui` → http://localhost:8600

**8 个页面，按推荐演示顺序排列**：

| # | 页面 | 路由 | 核心功能 |
|:--:|------|------|------|
| 1 | 🎯 **灰黑产情报分析Agent** | `?page=pipeline` | **一键全流程**：选平台+关键词→自动采集(实时计数)→清洗(逐条进度)→研判(内容预览)→多库同步。严格ID串联，只处理当次采集数据 |
| 2 | 总览 / ChatBI | `?page=overview` | 数据概览、风险分布趋势、自然语言态势问答 |
| 3 | 🎣 **钓鱼模拟** | `?page=persona` | **流式实时对话**：3个AI人物可选+角色自定义编辑+6场景预设，对话气泡逐轮刷新，自动提取结构化情报 |
| 4 | 采集器管理 | `?page=collector` | 7平台卡片，独立选择关键词和页数，一键触发采集，实时日志 |
| 5 | 数据清洗 | `?page=cleaning` | 批量清洗+前后预览，展示作者感知去重/角色分类/噪声评分详情 |
| 6 | 研判工作台 | `?page=workbench` | 查看单条情报的分类/实体/证据/黑话/风险评分/图谱扩线 |
| 7 | 情报池 | `?page=intel_pool` | 全量情报列表，按状态筛选(待清洗/待研判/已研判/已丢弃)，批量提交 |
| 8 | 知识库 | `?page=knowledge` | 实体库浏览、黑话词典管理、候选黑话审核、图谱扩线入口 |
| 9 | 系统状态 | `?page=system` | MySQL/Neo4j/Milvus/Doris 实时连接状态 |

**页面设计原则**：
- 全流程页面（情报分析Agent）整合完整链路，用于比赛开场演示（2分钟）
- 钓鱼模拟页面展示主动情报收集能力，体现系统差异化
- 其余页面拆分展示各环节细节，方便评委深入了解

**ChatBI 轻量问答**：

采用"白名单问题 → 固定SQL"模式，避免 LLM 自由生成 SQL 的风险。支持：风险分布、平台高危排行、热门黑话、高危样本、待研判队列等。

---

## 5. 命令速查

```bash
cd BGI/

# 环境
pip install -r requirements.txt
playwright install chromium

# 基础设施
docker compose -f docker/docker-compose.yml up -d

# 初始化（答辩推荐 --reset 清空重建）
python main.py init-db --reset

# 导入示例数据（7平台 10,248条）
python scripts/demo.py load

# ===== 采集 =====
python main.py collect -p weibo -k "刷单" --max-pages 5        # 微博 ~8条/s
python main.py collect -p zhihu -k "刷单,接码" --max-pages 5    # 知乎 ~5条/s
python main.py collect -p xiaohongshu -k "刷单" --max-pages 3   # 小红书
python main.py collect -p douyin -k "刷单" --max-pages 3        # 抖音
python main.py collect -p tieba -k "刷单" --max-pages 2         # 贴吧
python main.py login-xianyu                                      # 闲鱼首次登录
python main.py collect -p xianyu -k "账号交易" --max-pages 2    # 闲鱼
python main.py collect -p qq_group --mode both --duration 60     # QQ群

# ===== 清洗 + 研判 =====
python main.py clean -l 500         # 清洗（或通过UI操作）
python main.py analyze -l 200       # 研判（或通过UI提交）

# ===== 人物钓鱼 =====
python main.py persona list                                               # 列出人物
python main.py persona run -p ecommerce_buyer -t "xianyu:uid:name:context" # 单目标
python main.py persona run-batch -p ecommerce_buyer -f targets.json        # 批量

# ===== 服务 =====
python main.py ui                    # Streamlit → http://localhost:8600
python main.py api --port 8000       # FastAPI  → http://localhost:8000

# ===== 一键演示 =====
python scripts/demo.py full          # Docker→建表→导数据→采集→UI
```

---

## 6. API 接口

启动：`python main.py api`

| 方法 | 路径 | 作用 |
|------|------|------|
| GET | `/health` | 健康检查 |
| GET | `/api/stats` | 看板统计数据 |
| GET | `/api/intel` | 情报列表(支持筛选和分页) |
| GET | `/api/intel/{raw_id}` | 单条情报详情 |
| GET | `/api/entities` | 实体列表 |
| GET | `/api/entities/{entity_id}/graph` | 实体周边图谱 |
| GET | `/api/slang` | 黑话词典 |
| POST | `/internal/v1/agent/analyze` | 同步研判 |
| POST | `/api/analysis/jobs` | 异步提交研判任务 |
| POST | `/api/analysis/jobs/batch` | 批量提交研判 |
| GET | `/api/analysis/jobs/{job_id}` | 查询任务进度 |

---

## 7. 配置

编辑 `.env` 文件（参考 `.env.template`）：

```env
# MySQL
BGI_MYSQL_HOST=localhost
BGI_MYSQL_PORT=3306
BGI_MYSQL_USER=bagi
BGI_MYSQL_PASSWORD=bagi2026pass
BGI_MYSQL_DATABASE=bagi_intel

# Neo4j
BGI_NEO4J_URI=bolt://localhost:7687
BGI_NEO4J_USER=neo4j
BGI_NEO4J_PASSWORD=bagi2026neo4j

# Milvus
BGI_MILVUS_HOST=localhost
BGI_MILVUS_PORT=19530

# LLM (DeepSeek 或其他兼容接口)
BGI_LLM_API_KEY=your_api_key
BGI_LLM_API_BASE=https://api.deepseek.com/v1
BGI_LLM_MODEL=deepseek-chat

# Doris (可选，不可用自动降级)
BGI_DORIS_ENABLED=true
BGI_DORIS_HOST=localhost
BGI_DORIS_PORT=9030
```

---

## 8. 数据库设计

### MySQL 核心表

| 表 | 层级 | 用途 |
|------|:--:|------|
| `ods_raw_intel` | ODS | 原始情报，7平台统一格式，包含处理状态 |
| `dwd_clean_intel` | DWD | 清洗结果：clean_text、simhash、内容角色、去重状态 |
| `dwd_intel_analysis` | DWD | 研判结果：风险分类、评分、证据、摘要、版本控制 |
| `dwd_entity` | DWD | 实体库：账号/联系方式/链接/黑话/工具，含抽取方式和置信度 |
| `dwd_entity_relation` | DWD | 实体关系：共现和推断关系 |
| `dim_slang_dict` | DIM | 黑话词典：active/candidate/deprecated 状态 |
| `ads_risk_case` | ADS | 风险案件聚合 |
| `agent_report` | ADS | Agent 摘要+证据+处置建议归档 |
| `annotation_log` | — | 人工修正日志(HITL闭环) |
| `analysis_job` | — | 异步研判任务状态 |

### Neo4j 图模型

```
(Intel)-[:USES_ACCOUNT]->(Account)
(Intel)-[:USES_CONTACT]->(Contact)
(Intel)-[:PROMOTES_LINK]->(Link)
(Intel)-[:PROMOTES_TOOL]->(Tool)
(Intel)-[:USES_SLANG]->(Slang)
(实体A)-[:CO_OCCURS]->(实体B)   // 共享出现
```

### Milvus 集合

- `slang_embeddings`：黑话词向量（MiniLM），用于变体黑话发现
- `intel_embeddings`：情报文本向量，用于相似情报检索

---

## 9. 项目目录

```
BGI/
├── agents/         图谱扩线、报告摘要等 Agent 辅助模块
├── analyzer/       风险分类、实体抽取、证据提取、风险评分、状态机、异步worker
├── api/            FastAPI RESTful 接口
├── bridges/        NapCatQQ WebSocket 桥接(QQ群采集)
├── cleaner/        Emoji翻译 + 平台过滤 + 作者感知去重 + 噪声评分 + 内容角色分类
├── collectors/     7平台采集器(10 Spider + 7 Collector + 注册中心)
├── config/         配置与风险规则(risk_rules.yaml)
├── data/           模型、黑话词典、示例数据
├── docker/         Docker Compose(MySQL/Neo4j/Milvus/Doris)
├── persona/        AI钓鱼人物引擎(YAML配置+流式对话+安全护栏)
├── scripts/
│   ├── demo.py     一键演示脚本
│   ├── importers/  JSONL数据导入
│   └── modeling/   RoBERTa训练脚本
├── services/       业务服务层
├── storage/        MySQL/Neo4j/Milvus/Doris 访问层(懒加载单例)
├── tests/          单元测试
├── ui/             Streamlit 前端
│   └── views/
│       ├── pipeline.py      🎯 全自动流水线
│       ├── persona.py       🎣 钓鱼模拟(流式实时对话)
│       ├── collector.py     采集器管理
│       ├── cleaning.py      数据清洗
│       ├── workbench.py     研判工作台
│       ├── intel_pool.py    情报池
│       ├── overview.py      总览/ChatBI
│       ├── knowledge.py     知识库
│       └── system_status.py 系统状态
├── main.py          CLI 入口(click命令组)
├── schema.py        共享枚举与数据结构
└── README.md        项目说明文档
```

---

## 10. 比赛演示建议（12分钟）

| 时间 | 环节 | 页面 | 操作 |
|:--:|------|------|------|
| 0-2min | **开场：全流程** | 情报分析Agent | 选微博+"刷单"→一键启动→实时展示采集→清洗→研判→入库全过程 |
| 2-4min | **主动情报** | 钓鱼模拟 | 选"电商卖家小张"+预设"刷单服务"场景→流式对话→提取结构化情报 |
| 4-5min | **数据纵览** | 情报池 | 展示7平台数据已统一入库，按状态筛选 |
| 5-7min | **深度研判** | 研判工作台 | 打开一条高危情报，展示分类/实体/证据/黑话/图谱 |
| 7-8min | **数据飞轮** | 知识库 | 展示候选黑话→人工确认→词典更新闭环 |
| 8-9min | **态势问答** | 总览/ChatBI | "哪个平台高危最多""最近热门黑话" |
| 9-10min | **自定义展示** | 钓鱼模拟 | 展示角色自定义编辑，证明系统灵活性 |
| 10-11min | **工程完整性** | 系统状态 | MySQL/Neo4j/Milvus/Doris 全部在线 |
| 11-12min | **收尾** | 情报分析Agent | 回到全流程页面，总结"采→洗→研→库"闭环 |

---

## 11. 当前不足与后续规划

| 问题 | 建议 |
|------|------|
| L2 RoBERTa 模型需GPU训练 | 使用 4090 训练，验证集 F1 写入答辩材料 |
| MEDIA_ONLY 消息缺乏OCR处理 | 接入 PaddleOCR 管道处理图片类消息 |
| 候选黑话需更强的HITL流程 | 前端"通过/驳回/编辑释义"后自动刷新词典和Milvus |
| 图谱扩线在小样本时冲击力有限 | 准备共享微信/手机号/域名的演示数据 |
| 评测指标体系待完善 | 增加分类准确率、实体抽取准确率、平均研判耗时、LLM调用比例 |

---

## 12. 一句话

**BGI 将黑灰产情报从"逐平台手动搜索→逐条阅读→手工摘录"的传统模式，升级为"一键采集→自动清洗→智能研判→图谱扩线→多库沉淀"的全自动闭环。**
