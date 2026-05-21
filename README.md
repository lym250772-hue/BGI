# BGI — 黑灰产情报分析 Agent

端到端自动化黑灰产情报采集、清洗、分类、实体抽取与分析系统——面向字节跳动 AI 全栈挑战赛（AI 安全系统赛道）。

## 核心能力

- **多源采集** — Telegram 群组 / 贴吧 / 微博 / 知乎 / 小红书 / 论坛 多渠道情报采集
- **智能清洗** — SimHash 去重 + HTML 清洗 + 噪声过滤 + 优先级标记
- **三级分类** — L1 关键词规则 → L2 RoBERTa 微调 → L3 LLM 推理（7 大类 20 子类）
- **实体抽取** — 正则 → 词典 → Embedding 向量检索 → LLM 结构化抽取四层级联
- **知识图谱** — Neo4j 构建实体关系网络，支持关联分析 & 团伙发现
- **作弊剧本** — LLM 自动生成滥用链路分析与对抗策略
- **可视化仪表盘** — Streamlit 莫兰迪配色专业 Dashboard

## 技术栈

| 层 | 技术 |
|---|---|
| 采集 | Telethon / Scrapy / Playwright |
| 清洗 | SimHash / jieba / scikit-learn |
| 分类 | Transformers (RoBERTa) / OpenAI API |
| 实体 | Regex + Milvus 向量检索 + LLM |
| 存储 | MySQL 8.0（业务数据）+ Neo4j 5.20（知识图谱）+ Milvus 2.4（向量） |
| 服务 | FastAPI + Streamlit |
| 部署 | Docker Compose（6 个容器） |

## 快速开始

### 1. 环境要求

- Docker Desktop (MySQL + Neo4j + Milvus + etcd + MinIO)
- Python 3.11+
- Git

### 2. 启动基础设施

```bash
cd BGI/docker
docker compose up -d
```

等待所有容器健康运行后继续。

### 3. 安装依赖

```bash
pip install -r requirements.txt
```

### 4. 配置 API Key

```bash
cp .env.template .env
```

编辑 `.env`，填入 DeepSeek API Key（或豆包/OpenAI 兼容 Key）：

```
BGI_LLM_API_KEY=sk-your-key-here
```

Telegram 采集可选（需从 https://my.telegram.org 获取 api_id 和 api_hash）。

### 5. 初始化数据库

```bash
python main.py init-db
```

自动创建 MySQL 表、Neo4j 约束、Milvus 集合，并加载 49 条种子黑话。

### 6. 启动 Dashboard

```bash
python main.py ui
```

浏览器打开 http://localhost:8501

### 7. 运行采集（可选，需 Telegram 凭证）

```bash
python main.py collect --platform telegram --tg-groups "group1,group2"
```

## 命令一览

```bash
python main.py init-db                   # 初始化所有数据库
python main.py collect -p telegram       # 采集情报
python main.py clean -l 500              # 清洗去重
python main.py analyze -l 200            # 分类 + 实体抽取
python main.py run -l 500                # 全流程：collect → clean → analyze
python main.py ui                        # 启动 Dashboard
```

## 项目结构

```
BGI/
├── main.py                  # CLI 入口
├── schema.py                # 数据模型 & 枚举定义
├── requirements.txt         # Python 依赖
├── .env.template            # 环境变量模板
│
├── collectors/              # 数据采集层
│   ├── base.py              #   IntelItem 数据类 + BaseCollector 抽象
│   ├── telegram_collector.py#   Telegram 采集器 (Telethon)
│   ├── web_collector.py     #   Web 采集器 (Scrapy/Playwright)
│   └── registry.py          #   采集器注册表
│
├── cleaner/                 # 数据清洗层
│   ├── pipeline.py          #   清洗管道 (HTML→去噪→SimHash→优先级)
│   └── simhash_py.py        #   纯 Python SimHash 实现
│
├── analyzer/                # 分析引擎层
│   ├── classifier.py        #   三级级联分类器
│   ├── entity_extractor.py  #   四层级联实体抽取
│   └── engine.py            #   分析编排引擎
│
├── storage/                 # 存储层
│   ├── mysql_store.py       #   MySQL 业务数据 CRUD
│   ├── neo4j_store.py       #   Neo4j 知识图谱操作
│   └── milvus_store.py      #   Milvus 向量检索操作
│
├── api/                     # API 服务层
│   └── server.py            #   FastAPI REST API
│
├── ui/                      # 可视化仪表盘
│   ├── app.py               #   Streamlit 主入口
│   ├── theme.py             #   莫兰迪配色 CSS 主题
│   └── pages/               #   6 个页面模块
│       ├── dashboard.py     #   仪表盘
│       ├── intel_list.py    #   情报列表
│       ├── entities.py      #   实体库
│       ├── graph.py         #   知识图谱
│       ├── cheat_scripts.py #   作弊剧本生成
│       └── slang_dict.py    #   黑话词典
│
├── docker/                  # 容器编排
│   ├── docker-compose.yml   #   6 容器编排配置
│   └── mysql_init/          #   MySQL 初始化 SQL
│       └── 01_schema.sql    #   建表语句
│
├── data/                    # 数据目录
│   └── slang_dict/          #   黑话种子数据 (49条)
│       └── seed_slang.json
│
├── tests/                   # 单元测试 (27/27 PASS)
│   ├── test_cleaner.py      #   清洗管道测试
│   ├── test_classifier.py   #   分类器测试
│   └── test_entity_extractor.py  # 实体抽取测试
│
├── scripts/                 # 工具脚本（预留）
└── config/                  # 全局配置
    └── settings.py          #   Pydantic Settings
```

### 空文件说明

| 文件 | 作用 |
|------|------|
| `*/__init__.py` | Python 包标识。部分含模块导入（analyzer），部分仅占位（api/storage 为懒加载设计） |
| `scripts/` | 工具脚本目录，预留给数据迁移、模型训练等辅助任务 |
| `data/raw/` | 原始采集数据存储目录 |
| `data/cleaned/` | 清洗后数据存储目录 |
| `data/models/` | 微调模型文件存放目录（RoBERTa checkpoint） |

## 运行测试

```bash
python -m pytest tests/ -v    # 27 tests, all passing
```

## 许可证

仅供竞赛评估使用。

---

### 服务端口

| 服务 | 端口 | 地址 |
|------|------|------|
| Streamlit Dashboard | 8501 | http://localhost:8501 |
| FastAPI | 8000 | http://localhost:8000 |
| MySQL | 3306 | localhost:3306 |
| Neo4j Browser | 7474 | http://localhost:7474 |
| Neo4j Bolt | 7687 | bolt://localhost:7687 |
| Milvus | 19530 | localhost:19530 |
| Attu (Milvus GUI) | 3000 | http://localhost:3000 |
| MinIO Console | 9001 | http://localhost:9001 |
