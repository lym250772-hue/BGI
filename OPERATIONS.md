# BGI 操作手册 — v4.2 最终版

> 最后更新: 2026-06-10 | 清洗层: 作者感知去重 + 内容角色五分类 + MEDIA_ONLY | UI: 8页面(情报工厂/钓鱼模拟/总览/采集/清洗/工作台/情报池/知识库/系统)

---

## 一、数据流程

```
原始数据导入               UI 手动清洗              自动研判流程
───────────              ───────────              ──────────
demo.py load             数据清洗 页面              规则自动研判
现场采集                  勾选 → 清洗所选               ↓
    ↓                        ↓                  dwd_intel_analysis
raw_data 表             ods_raw_intel            → 实体提取
(临时,定期清理)          (CLEANED 状态)           → 知识图谱
                        作者感知去重              → 风险评分
                        内容角色五分类             → 自动入库
                        MEDIA_ONLY 保护
```

> 各环节拆分为独立页面仅为展示处理过程。实际生产环境中清洗后的自动研判由队友实现的规则引擎全自动完成。

---

## 二、黑话关键词字典

位置: `data/slang_dict/seed_slang.json`

**48个黑话关键词**（采集时逐词搜索，覆盖7平台）:

```
714高炮, AB贷, 上车, 下车, 云手机, 人脸, 代下, 代理IP, 众包, 八件套,
养号, 出号, 刷单, 千粉, 卡商, 反卤, 发卡, 可开播, 号商, 四件套,
大肉, 引流, 打码, 报单, 挂机, 接码, 搬砖, 撞库, 数字人, 料商,
无人直播, 无损套, 日结, 模拟器, 水房, 洗号, 狗推, 猫池, 白户,
破盾, 羊头, 羊腿, 群控, 薅羊毛, 融车, 跑分, 车手, 黄牛
```

---

## 三、答辩演示流程（推荐）

### Step 1: 启动基础设施

```bash
# 确保 Docker Desktop 已启动
docker compose -f docker/docker-compose.yml up -d
docker ps  # 确认 5 个容器 running

# 清库建表 + 写入黑话词典
python main.py init-db --reset
```

### Step 2: 导入示例数据

```bash
# 导入 7 平台 10,248 条原始数据（仅导入，不清洗）
python scripts/demo.py load
```

### Step 3: 启动前端

```bash
python main.py ui
# → http://localhost:8600
```

### Step 4: UI 操作流程

| 步骤 | 页面 | 操作 |
|------|------|------|
| 1 | **总览 / ChatBI** | 查看数据概览、风险分布、ChatBI 问答 |
| 2 | **采集器管理** | 可选：现场采集1个关键词展示实时能力 |
| 3 | **数据清洗** | 勾选数据 → 批量清洗，查看清洗前后对比和角色分类 |
| 4 | **研判工作台** | 提交研判任务，查看分类+实体+证据+风险评分 |
| 5 | **知识库** | 浏览黑话词典、实体库、候选黑话、图谱扩线 |
| 6 | **系统状态** | 查看 MySQL/Neo4j/Milvus 连接状态 |

### 一键启动

```bash
# 完整流程：Docker → 建表 → 导数据 → 采集演示 → 钓鱼演示 → UI
python scripts/demo.py full
```

| 子命令 | 功能 |
|------|------|
| `start` | Docker + 建表 + 导数据 + UI |
| `load` | 仅导入 10,248 条示例数据 |
| `crawl` | 快速采集演示（微博"刷单"1页） |
| `persona` | AI 人物钓鱼对话演示 |
| `ui` | 仅启动前端 |
| `full` | 完整流程 |

---

## 四、手动操作

### 环境准备

```bash
cd "E:\pythonProject\2605 灰黑产Agent比赛\BGI"
pip install -r requirements.txt
playwright install chromium
```

### 数据库初始化

```bash
python main.py init-db --reset    # 清空全部数据从零开始（答辩推荐）
python main.py init-db            # 保留已有数据，增量迁移
```

### 采集命令

```bash
# 内容平台
python main.py collect -p weibo -k "刷单" --max-pages 5        # AJAX API ~8/s
python main.py collect -p zhihu -k "刷单,接码" --max-pages 5    # 浏览器内fetch ~5/s
python main.py collect -p tieba -k "刷单" --max-pages 2         # 浏览器+DOM ~10/s

# 小红书/抖音（Playwright）
python main.py collect -p xiaohongshu -k "刷单" --max-pages 3
python main.py collect -p douyin -k "刷单" --max-pages 3

# 闲鱼（需首次登录）
python main.py login-xianyu
python main.py collect -p xianyu -k "账号交易" --max-pages 2

# QQ群（需 NapCatQQ）
python main.py collect -p qq_group --mode listen --duration 60
python main.py collect -p qq_group --mode fetch --fetch-count 200
python main.py collect -p qq_group --mode both --fetch-count 300 --duration 30

# 人物钓鱼
python main.py persona list
python main.py persona run -p ecommerce_buyer -t "platform:uid:name:context"
python main.py persona run-batch -p ecommerce_buyer -f targets.json
```

### 清洗 + 分析

```bash
python main.py clean -l 500       # 命令行清洗（或通过 UI 数据清洗页面操作）
python main.py analyze -l 200     # 命令行分析（或通过 UI 研判工作台提交）
python main.py ui                 # 启动前端 (8600)
python main.py api                # 启动 FastAPI (8000)
```

---

## 五、UI 页面一览

| 页面 | 路由 | 功能 |
|------|------|------|
| **总览 / ChatBI** | `?page=overview` | 接收总量/待研判/研判中/已研判/高危情报 + 风险分布 + 自然语言问答 |
| **采集器管理** | `?page=collector` | 7 平台卡片 + 一键采集 + 实时日志 |
| **数据清洗** 🆕 | `?page=cleaning` | 批量清洗 + 清洗前后预览 + 作者感知去重 + 内容角色分类 |
| **研判工作台** | `?page=workbench` | Think-Chain 分析 + 分类/实体/证据/风险评分 |
| **知识库** | `?page=knowledge` | 实体库 + 黑话词典 + 候选黑话 + 图谱扩线 |
| **系统状态** | `?page=system` | MySQL/Neo4j/Milvus 连接状态 + 当前配置 |

---

## 六、数据总览

| 文件 | 平台 | 类型 | 条目 |
|------|------|:--:|--:|
| `xiaohongshu_sample.json` | 小红书 | 内容 | 2,556 |
| `weibo_sample.json` | 微博 | 内容 | 1,768 |
| `zhihu_sample.json` | 知乎 | 内容 | 1,607 |
| `xianyu_sample.json` | 闲鱼 | 二手 | 1,389 |
| `douyin_sample.json` | 抖音 | 内容 | 1,167 |
| `tieba_sample.json` | 贴吧 | 内容 | 1,141 |
| `qq_group_sample.json` | QQ群 | 社交 | 620 |
| **合计** | **7平台** | **3品类** | **10,248** |

统一 IntelItem 格式（`collectors/base.py`），QQ 群消息通过 `IMMessageItem` → `im_to_intel()` 转换。

---

## 七、故障排查

| 症状 | 原因 | 解决 |
|------|------|------|
| **UI 打开空白** | Docker 未启动 | 启动 Docker Desktop，等图标变绿 |
| **概览数字异常** | 旧数据残留 | `python main.py init-db --reset` 重建 |
| **Doris 起不来** | 国内拉不到镜像 | 不需要，系统自动降级到 MySQL |
| 采集返回 0 条 | Cookie 过期 | `python main.py login-<平台>` |
| 闲鱼 0 条/验证码 | 阿里反爬 | 等 15 分钟；限量 20-30 条/次 |
| QQ 群无连接 | NapCatQQ 未启动 | 启动 NapCatQQ；确认 `ws://localhost:3001` |
| LLM 功能降级 | API Key 无效 | 编辑 `.env` → `BGI_LLM_API_KEY` |
| GBK 乱码 | Windows 终端编码 | `PYTHONIOENCODING=utf-8` |

---

## 八、服务端口

| 服务 | 端口 |
|------|------|
| Streamlit UI | 8600 |
| FastAPI | 8000 |
| MySQL | 3306 |
| Neo4j | 7474 / 7687 |
| Milvus | 19530 |
| NapCatQQ HTTP | 3000 |
| NapCatQQ WS | 3001 |
