# 黑灰产情报分析 Agent

> 字节跳动 AI 全栈挑战赛 · AI 安全系统赛道 | 团队：你说的很队

把散落在 7 个互联网平台的黑灰产文本，**一键自动转化为可查询、可扩线、可复核的结构化情报线索库**。

---

## 整体架构

系统围绕赛题要求的四大模块构建，形成「采集 → 清洗 → 分析 → 输出」的完整闭环：

```
  ① 多源情报采集          ② 数据清洗 Pipeline        ③ 智能分析引擎           ④ 结构化输出与可视化
  ─────────────          ──────────────────        ──────────────          ──────────────────
  7 平台统一采集器          6 步零 LLM 管道            三级风险分类              8 页面 Streamlit 仪表盘
  HTTP API + Playwright   作者感知 SimHash 去重      四级实体抽取              FastAPI RESTful 接口
  + WebSocket             平台专属噪声过滤            黑话归一 + 候选发现         ChatBI 态势问答
  统一 IntelItem 格式      内容角色五分类              证据提取 + 风险评分         异步研判 + 批量处理
  反爬 6 件套              自适应阈值                  知识图谱扩线              MySQL + Neo4j + Milvus
  ─────────────          ──────────────────        ──────────────          ──────────────────
               ↖ AI 钓鱼人物（主动情报，非被动等待） ↗
```

---

## 一、多源情报采集

### 采集覆盖

赛题要求至少 3 类情报源。我们实现了 **7 个平台全覆盖**，远超最低要求：

| 平台 | 品类 | 技术方案 | 速度 | 评论采集 |
|------|:--:|------|:--:|:--:|
| 微博 | 内容社区 | AJAX API 纯 HTTP | ~8条/s | ✅ |
| 知乎 | 内容社区 | 浏览器内 fetch API（绕过 x-zse-96） | ~5条/s | ✅ |
| 贴吧 | 论坛 | JSON API + DOM | ~10条/s | ✅ |
| 小红书 | 内容社区 | v3 持久化浏览器 + SSR 提取 | ~0.5条/s | ✅ |
| 抖音 | 短视频 | X-Bogus 签名 + 浏览器内 fetch | ~0.5条/s | ✅ |
| 闲鱼 | 二手交易 | v3 持久化浏览器 + DOM 解析 | ~0.3条/s | — |
| QQ群 | 社交 IM | NapCatQQ WebSocket + HTTP 双模式 | 实时 + 历史增量拉取 | — |

### 统一数据格式

所有平台产出统一的 `IntelItem` 结构，时间戳使用北京时间（`now_bjt()`）：

> `platform | content_raw | content_type | source_url | author_uid | author_username | group_id | collected_at | like_count | comment_count | share_count | comments | image_urls | tags | metadata`

### 反爬策略（6件套）

UA 池轮换 · webdriver 隐藏 · Cookie 注入 · 随机间隔 · 首页预热 · 验证码检测

### 增量采集

按关键词记录时间戳，持久化 JSON checkpoint，支持断点续采。

---

## 二、数据清洗 Pipeline

赛题要求的去重、噪声过滤、高危内容识别全部在一个 **6 步零 LLM 管道** 中完成，不消耗任何 Token：

```
原始文本
  ┊ Step 1: Emoji 语义翻译      100+ 映射，8 大语义类别
  ┊ Step 2: 平台感知过滤         7 平台专属规则 + 通用噪声 + 误匹配保护
  ┊ Step 3: 文本规范化           Unicode / 全半角 / 零宽字符 / URL 简化
  ┊ Step 4: 作者感知去重 ★      同作者+相似→丢弃 / 不同作者+相似→情报保留
  ┊ Step 5: 噪声评分            12 维度（短文本含情报词自动免罚）
  ┊ Step 6: 优先级标记           高危关键词 → HIGH
```

### 核心创新：作者感知去重

传统 SimHash 看到相同内容就删。但在情报语境中，**同一内容被不同人发布本身就是信号**。我们的方案区分「真正的重复」和「有价值的情报扩散」：

| 场景 | 传统做法 | 我们的做法 |
|------|----------|---------|
| 同一新闻 6 家媒体转发 | 删 5 条 → 情报丢失 | **全部保留**（跨作者 = 议题扩散信号） |
| 同一卖家重复刷广告 | 判重丢弃 | 判重丢弃（同作者 = 真正重复） |
| QQ 群 bot 消息 | 进入分析浪费 LLM | **作者名过滤直接丢弃**（Q群管家等系统账号） |
| 短消息「寻卡商 日跑 5w」 | 因字数少被罚分 | **自动免罚**（检测到情报关键词） |

**自适应阈值**：短文本（<30字）→ 0，中文本 → 1，长文本（≥80字）→ 3。不搞一刀切。

### 平台专属过滤

不同平台的噪声特征完全不同，每个平台有定制规则：

| 平台 | 专属处理 |
|------|---------|
| QQ群 | 系统账号（Q群管家/QQ安全中心）→ 作者名过滤直接丢弃；筹备中 bot 消息模式匹配；[CQ:face] 表情码去除 |
| 微博 | 转发链去除（//@...）；话题 # 保留；O 网页链接清理 |
| 知乎 | 长文模板噪声；感谢/收藏类低质回复 |
| 通用 | 硬广告关键词过滤 + 情报信号词保护（含「淘宝/出租/预付/不封号」时自动跳过广告判定） |

### 内容角色五分类（零 LLM）

> actor（灰产从业者）| victim（受害者）| media（媒体）| police（警方）| unknown（未知）

### 清洗输出

| 状态 | 含义 | 处理 |
|------|------|------|
| CLEANED | 通过 | → 进入研判队列 |
| SIMILAR | 不同作者相似内容 | → 保留（跨作者信号） |
| MEDIA_ONLY | 纯图片/视频占位 | → 保留（待 OCR） |
| DISCARDED | 噪声/同作者重复 | → 不进入后续 |

---

## 三、智能分析引擎

对应赛题 3.1（风险意图分类）+ 3.2（关键实体抽取）+ 黑话归一。

### 风险分类：三级级联 + 自动降级

```
L1 规则层（关键词+正则，毫秒级）
    ↓ 命中即返回，不浪费算力
L2 小模型层（RoBERTa，可训练，scripts/modeling/train_roberta.py）
    ↓ 未命中或模型不可用
L3 LLM 层（DeepSeek，兜底）
    ↓ 连续失败 5 次 → 断路器自动降级到 L1+L2
```

**标签体系**（大类+小类）：诈骗类（电信/网络/金融诈骗）、引流类（色情/赌博/诈骗引流）、作弊类（刷单/考试/游戏作弊）、工具交易类（账号交易/黑卡/工具出售）

### 实体抽取：四级级联

```
L1 正则 → 手机号/微信/QQ/邮箱/URL/域名/IP/银行卡/支付宝/钱包
L2 词典 → 已知黑话（dim_slang_dict）
L3 向量 → Milvus 相似黑话检索（MiniLM 嵌入）
L4 LLM  → 复杂工具名/隐晦黑话/风险标签
```

### 黑话处理：数据飞轮

系统不但识别已有黑话，还能**自动发现新词并沉淀为词典演化入口**：

```
已知黑话命中词典 → 输出标准释义 → 直接入库
疑似新词 → candidate 状态 → 前端「知识库」人工确认 → active（正式词典）→ Milvus 重新索引 → 下次自动识别 ✓
```

形成了「发现 → 候选 → 确认 → 入库 → 索引 → 自动识别」的完整闭环，词典越用越准。

### 证据提取与风险评分

- 证据片段：规则证据 + 实体上下文 + LLM 证据，三通道说明「为什么这么判」
- 风险评分：综合分类置信度、实体数量、黑话数量、证据数量、图谱扩线等 7 因素
- 输出格式严格遵循赛题要求的 JSON 结构

### 知识图谱扩线（Neo4j）

6 类节点（Intel / Account / Contact / Link / Tool / Slang）× 6 类关系，回答三个核心问题：
1. 这个账号/链接以前出现过吗？
2. 它和谁共享联系方式/工具？
3. 能否形成疑似团伙链路？

---

## 四、结构化输出与可视化

对应赛题第 4 部分要求。

### 技术方案

FastAPI（RESTful API）+ Streamlit（8 页面仪表盘）+ MySQL（主库）+ Neo4j（图谱）+ Milvus（向量），全部 Docker Compose 一键部署。

### 前端页面（8 个）

| 页面 | 功能 |
|------|------|
| 🎯 **灰黑产情报分析Agent** | 一键全流程：选平台+关键词 → 自动采集 → 清洗 → 研判 → 多库同步，实时进度 |
| 总览 / ChatBI | 态势总览 + 风险分布趋势 + 自然语言问答（白名单 SQL 模式） |
| 🎣 **钓鱼模拟** | AI 人物流式实时对话 + 角色自定义编辑器 + 自动提取结构化情报 |
| 采集器管理 | 7 平台独立采集，选关键词一键触发 |
| 数据清洗 | 批量清洗预览，展示作者感知去重/角色分类/噪声评分详情 |
| 研判工作台 | 单条情报深度分析：分类/实体/证据/图谱/风险评分 |
| 情报池 | 全量数据按状态筛选，批量提交研判 |
| 知识库 | 实体浏览 + 黑话词典管理 + 候选黑话审核 |

### API 接口

| 方法 | 路径 | 功能 |
|------|------|------|
| GET | `/health` | 健康检查 |
| GET | `/api/stats` | 看板统计 |
| GET/POST | `/api/intel` | 情报查询/筛选 |
| GET | `/api/intel/{id}` | 单条情报详情 |
| GET | `/api/entities` | 实体列表 |
| GET | `/api/entities/{id}/graph` | 实体周边图谱 |
| POST | `/internal/v1/agent/analyze` | 同步研判 |
| POST | `/api/analysis/jobs/batch` | 批量异步研判 |

---

## 亮点创新

### 作者感知去重

重新定义情报场景下的去重逻辑：区分「同一作者重复发布」和「不同作者讨论同一话题」，后者作为情报扩散信号全部保留。

### AI 钓鱼人物（主动情报收集）

不被动等待数据，而是让 AI 伪装成买家/刷手/店主，**主动接触灰产卖家获取一手情报**。3 个 YAML 配置的 AI 人物，7 层安全护栏双向审查，流式对话实时展示，对话完成后 LLM 自动提取结构化情报。支持字段级自定义编辑器。

### 零 LLM 清洗管道

清洗阶段完全不消耗 Token，全部基于规则引擎 + SimHash + Emoji 语义映射（100+ 条目）。平台专属过滤策略（7 平台各不同）+ 情报信号词保护机制。

### 黑话词典数据飞轮

从「发现新词 → 候选状态 → 人工确认 → 入库 → 向量索引 → 自动识别」的完整闭环，词典持续演化。

### 一键全自动流水线

打开页面 → 选平台 → 输入关键词 → 点击按钮 → 采集（实时计数）→ 清洗（逐条进度）→ 研判（内容预览）→ 多库同步 → 完成。严格 ID 串联，采多少洗多少研多少。

---

## 存储架构

| 存储 | 角色 | 说明 |
|------|------|------|
| MySQL | 主业务库 | ODS（原始）→ DWD（清洗+研判+实体）→ DIM（黑话词典）→ ADS（案件聚合），完整分层 |
| Neo4j | 图谱扩线 | 实体节点 + 关系边，支撑团伙关联发现 |
| Milvus | 向量检索 | 黑话词向量（变体发现）+ 情报文本向量（相似检索） |

---

## 快速开始

```bash
# 安装依赖
pip install -r requirements.txt
playwright install chromium

# 启动基础设施（MySQL + Neo4j + Milvus）
docker compose -f docker/docker-compose.yml up -d

# 初始化数据库（首次或重建）
python main.py init-db --reset

# 导入示例数据（7 平台 10,248 条）
python scripts/demo.py load

# 命令行：采集 + 清洗 + 研判
python main.py collect -p weibo -k "刷单" --max-pages 3
python main.py clean -l 500
python main.py analyze -l 200

# 人物钓鱼
python main.py persona list
python main.py persona run -p ecommerce_buyer -t "平台:uid:昵称:描述"

# 启动前端 / API
python main.py ui      # → http://localhost:8600
python main.py api     # → http://localhost:8000
```

---

## 技术栈

| 层次 | 技术 |
|------|------|
| 采集 | HTTP API + Playwright (v3 持久化) + WebSocket (NapCatQQ) |
| 清洗 | SimHash + 正则 + Emoji 语义映射（100+ 条目，零 LLM） |
| 分类 | L1 规则 → L2 RoBERTa → L3 LLM (DeepSeek) |
| 实体 | L1 正则 → L2 词典 → L3 Milvus 向量 (MiniLM) → L4 LLM |
| LLM | DeepSeek API（兼容 OpenAI 接口，可替换为豆包等） |
| 存储 | MySQL + Neo4j + Milvus |
| 服务 | FastAPI + Streamlit |
| 部署 | Docker Compose 一键启动全部基础设施 |

---

## 项目结构

```
├── collectors/         7 平台采集器 + 统一 IntelItem + 注册中心
├── cleaner/            6 步零 LLM 清洗管道
├── analyzer/           状态机 Agent + 三级分类 + 四级实体 + 证据 + 评分
├── persona/            AI 钓鱼人物引擎（YAML 配置 + 流式对话 + 安全护栏）
├── agents/             图谱扩线 + 报告摘要
├── bridges/            NapCatQQ 桥接（QQ 群采集）
├── storage/            MySQL / Neo4j / Milvus 访问层
├── api/                FastAPI RESTful 接口
├── ui/                 Streamlit 8 页面仪表盘
│   └── views/
│       ├── pipeline.py      全自动流水线
│       ├── persona.py       钓鱼模拟（流式对话）
│       ├── collector.py     采集器管理
│       ├── cleaning.py      数据清洗
│       ├── workbench.py     研判工作台
│       ├── intel_pool.py    情报池
│       ├── overview.py      总览 / ChatBI
│       └── knowledge.py     知识库
├── config/             配置 + 风险规则
├── scripts/            demo 脚本 + JSONL 导入 + RoBERTa 训练
├── tests/              单元测试
├── docker/             Docker Compose 编排
├── main.py             CLI 入口
└── README.md
```

---

## 配置

编辑 `.env`（参考 `.env.template`）：

```env
# MySQL
BGI_MYSQL_HOST=localhost:3306
BGI_MYSQL_USER=bagi
BGI_MYSQL_PASSWORD=bagi2026pass

# Neo4j
BGI_NEO4J_URI=bolt://localhost:7687

# LLM（DeepSeek / 豆包 / 其他兼容接口）
BGI_LLM_API_KEY=your_key
BGI_LLM_API_BASE=https://api.deepseek.com/v1
BGI_LLM_MODEL=deepseek-chat
```
