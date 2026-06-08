# BGI 操作手册 — v4.2 最终版

> 最后更新: 2026-06-08 v4.2

---

## 一、黑话关键词字典

位置: `data/slang_dict/seed_slang.json`

**49个黑话关键词**（采集时逐词搜索，覆盖7平台）:

```
714高炮, AB贷, 上车, 下车, 云手机, 人脸, 代下, 代理IP, 众包, 八件套,
养号, 出号, 刷单, 千粉, 卡商, 反卤, 发卡, 可开播, 号商, 四件套,
大肉, 引流, 打码, 报单, 挂机, 接码, 搬砖, 撞库, 数字人, 料商,
无人直播, 无损套, 日结, 模拟器, 水房, 洗号, 狗推, 猫池, 白户,
破盾, 羊头, 羊腿, 群控, 薅羊毛, 融车, 跑分, 车手, 黄牛
```

**数据采集策略**: 用以上49个关键词，在7个平台上逐个搜索，结果保存为统一 IntelItem 格式到 `examples/` 目录。

---

## 二、完整实机演示流程

### Step 1: 启动基础设施

```bash
# 确保 Docker Desktop 已启动（状态栏图标变绿）
# 然后执行一键脚本：
python scripts/demo.py start
```

这个命令自动完成：启动容器 → 初始化数据库 → 导入全部7平台数据 → 清洗 → 启动前端。

完成后访问: `http://localhost:8600`

### Step 2: 采集演示（可选）

```bash
# 快速演示：微博搜索"刷单"，1页，展示实时采集能力
python scripts/demo.py crawl
```

### Step 3: 人物钓鱼演示（可选）

```bash
# AI人物钓鱼对话演示：模拟电商卖家与涨粉服务卖家对话
python scripts/demo.py persona
```

### Step 4: 前端分析展示

打开浏览器 → `http://localhost:8600`：

| 页面 | 功能 |
|------|------|
| **总览/ChatBI** | 情报总览、风险分布、快速问答 |
| **情报池** | 10K+条原始情报，按平台/状态筛选 |
| **研判工作台** | 逐条分析详情：分类+实体+证据+风险评分 |
| **知识库** | 黑话词典、实体库、候选黑话审核 |
| **系统状态** | Docker/MySQL/Neo4j/Milvus 运行状态 |

### 一键完整演示

```bash
python scripts/demo.py full
# 自动完成：Docker → 数据 → 清洗 → 采集演示 → 钓鱼演示 → UI
```

---

## 三、手动操作流程

### 环境准备

```bash
cd "E:\pythonProject\2605 灰黑产Agent比赛\BGI"
pip install -r requirements.txt
playwright install chromium
```

### 数据写入

```bash
# 方式1: 使用demo脚本（推荐）
python scripts/demo.py start

# 方式2: 手动逐步
docker compose -f docker/docker-compose.yml up -d
python main.py init-db
python scripts/demo.py load     # 需在demo.py中添加load子命令，或用下方方式
```

### 采集命令

```bash
# 内容平台（HTTP快速）
python main.py collect -p weibo -k "刷单" --max-pages 5
python main.py collect -p zhihu -k "刷单,接码" --max-pages 5
python main.py collect -p tieba -k "刷单" --max-pages 2

# 小红书/抖音（Playwright浏览器）
python main.py collect -p xiaohongshu -k "刷单" --max-pages 3
python main.py collect -p douyin -k "刷单" --max-pages 3

# 闲鱼（需首次登录）
python main.py login-xianyu
python main.py collect -p xianyu -k "账号交易" --max-pages 2

# QQ群（需NapCatQQ）
python main.py collect -p qq_group --mode listen --duration 60                      # 被动监听
python main.py collect -p qq_group --qq-groups "123456" --mode fetch --fetch-count 200  # 拉取历史
python main.py collect -p qq_group --mode both --fetch-count 300 --duration 30      # 先拉后监(推荐)

# 全量黑话采集
python scripts/collect_xianyu_full.py
python scripts/qq_fetch_history.py --count 500

# 人物钓鱼
python main.py persona list
python main.py persona run -p ecommerce_buyer -t "platform:uid:name:context"
python main.py persona run-batch -p ecommerce_buyer -f targets.json -o results.json
```

### 清洗分析

```bash
python main.py clean -l 500       # 清洗去重
python main.py analyze -l 200     # L1→L2→L3 分类+实体+评分
python main.py ui                 # 启动前端 (默认8501)
python main.py api                # 启动FastAPI (8000)
```

---

## 四、数据总览

### examples/ 目录

| 文件 | 平台 | 类型 | 条目 |
|------|------|:--:|--:|
| `xiaohongshu_sample.json` | 小红书 | 内容 | 2,556 |
| `weibo_sample.json` | 微博 | 内容 | 1,768 |
| `zhihu_sample.json` | 知乎 | 内容 | 1,607 |
| `xianyu_sample.json` | 闲鱼 | 二手 | 1,365 |
| `douyin_sample.json` | 抖音 | 内容 | 1,167 |
| `tieba_sample.json` | 贴吧 | 内容 | 1,141 |
| `qq_group_sample.json` | QQ群 | 社交 | 620 |
| **合计** | **7平台** | **3品类** | **10,224** |

### 统一数据格式

所有平台使用 `IntelItem` 格式（`collectors/base.py`），通过 `normalizer.py` 归一化。QQ群消息通过 `IMMessageItem` → `im_to_intel()` 转换适配。

---

## 五、故障排查

| 症状 | 原因 | 解决 |
|------|------|------|
| **UI打开空白** | Docker未启动 | 先启动Docker Desktop，等图标变绿，再启动UI |
| **Docker频繁崩溃** | Docker Desktop VM不稳定 | 重启Docker Desktop（右键托盘→Restart） |
| 采集返回0条 | Cookie过期 | `python login_edge.py <平台>` |
| 闲鱼0条/验证码 | 阿里反爬 | 等15分钟；限量20-30条/次 |
| QQ群无连接 | NapCatQQ未启动 | 启动NapCatQQ；确认 ws://localhost:3001 |
| LLM功能降级 | API Key无效 | 编辑 `.env` → `BGI_LLM_API_KEY` |
| GBK乱码 | Windows终端编码 | `PYTHONIOENCODING=utf-8` |

---

## 六、服务端口

| 服务 | 端口 | 地址 |
|------|------|------|
| Streamlit UI | 8600 | http://localhost:8600 |
| FastAPI | 8000 | http://localhost:8000 |
| MySQL | 3306 | localhost:3306 |
| Neo4j | 7474/7687 | localhost:7474 |
| Milvus | 19530 | localhost:19530 |
| NapCatQQ HTTP | 3000 | http://localhost:3000 |
| NapCatQQ WS | 3001 | ws://localhost:3001 |
