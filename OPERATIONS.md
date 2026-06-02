# BGI 完整操作流程

> 从零到可演示的完整操作步骤（覆盖采集 → 清洗 → OCR → 分析 → 展示）
> 最后更新: 2026-06-02 (v2.0)

---

## 环境检查

```bash
# 确认在正确目录
cd "E:\pythonProject\2605 灰黑产Agent比赛\BGI"

# 确认 Python 版本 >= 3.11
python --version

# 确认依赖已安装
pip install -r requirements.txt

# 确认 Docker 在运行
docker ps
# 应有: bagi_mysql, bagi_neo4j, bagi_milvus, bagi_doris 等容器
```

## Step 1: 启动基础设施

```bash
docker compose -f docker/docker-compose.yml --profile olap up -d
```

等待所有容器 Healthy（约 30 秒）。

## Step 2: 初始化数据库

```bash
python main.py init-db
```

创建 MySQL 10 表 + Neo4j 约束 + Milvus 集合 + 加载 49 条种子黑话。

## Step 3: 登录各平台

```bash
# 依次登录（浏览器弹出 → 手动扫码 → 终端按 Enter）
python main.py login -p weibo
python main.py login -p zhihu
python main.py login -p tieba
python main.py login -p xiaohongshu
python main.py login -p douyin
```

Cookie 保存在 `data/raw/{platform}_cookies.json`，有效期 7-30 天。

## Step 4: 全通道并发采集（★推荐）

```bash
# 单关键词快速测试
python main.py collect-all -k "刷单" --max-pages 1

# 多关键词深度采集
python main.py collect-all -k "刷单,接码,跑分,账号出售" --max-pages 3

# 从关键词文件加载（含70+高危关键词）
python main.py collect-all --keyword-file data/grey_keywords.json --max-pages 2

# 控制速率（避免触发反爬）
python main.py collect-all -k "刷单" --rpm-per-platform 10 --batch-size 200
```

**采集过程中**：
- 每 5 秒输出实时进度（各平台 items/状态）
- `Ctrl+C` 可随时中断，自动保存断点到 `data/raw/*_checkpoint.json`
- 重新运行自动恢复未完成的关键词

## Step 5: 清洗去重

```bash
python main.py clean -l 500
```

处理流程：HTML归一化 → SimHash去重 → 噪声过滤 → 优先级标记 → 写入 `dwd_clean_intel`

## Step 6: OCR 图文提取

```bash
# 对小红书和抖音的图片进行 OCR
python main.py ocr -p douyin,xiaohongshu -l 100
```

从图片中提取文字（如截图中的微信号/QQ号），追加到 `dwd_clean_intel.merged_text`

> **注意**: 需要 PaddleOCR，首次运行会自动下载模型。无图片的内容跳过。

## Step 7: 分析引擎

```bash
python main.py analyze -l 200
```

执行：L1关键词分类 → L1.5 Metadata增强 → L2 RoBERTa → L3 LLM → 实体抽取 → 证据提取 → 风险评分 → 黑话归一 → 图谱扩线 → 多库同步

> **注意**: L3 LLM 需要有效的 `.env` 中 `BGI_LLM_API_KEY`。无 API Key 时自动降级到 L1+L2。

## Step 8: 启动 Dashboard

```bash
python main.py ui
```

浏览器打开 http://localhost:8501

**演示顺序建议**：
1. 总览/ChatBI → 看数据概况，用自然语言提问
2. 情报池 → 查看全量采集数据，按状态筛选
3. 研判工作台 → 选一条数据，看分类/实体/证据/黑话
4. 知识库 → 查看实体库和黑话词典
5. 系统状态 → 展示 MySQL/Neo4j/Milvus/Doris 全在线

---

## 快速演示流程（5 分钟）

如果已有数据库数据，直接展示：

```bash
# 1. 启动 Dashboard
python main.py ui

# 2. 在 "情报池" 页面展示采集的多平台数据
# 3. 在 "研判工作台" 展示一条数据的分析结果
# 4. 在 "总览/ChatBI" 问: "当前风险类型分布怎么样？"
# 5. 在 "系统状态" 展示所有服务在线
```

---

## 命令参考

```bash
# 数据采集
python main.py collect -p <平台> -k "关键词" --max-pages 3  # 单平台
python main.py collect-all -k "关键词" --max-pages 3          # 全平台并发

# 数据处理
python main.py clean -l 500          # 清洗去重
python main.py ocr -p douyin,xhs -l 100  # OCR图文
python main.py analyze -l 200        # 完整分析
python main.py run -l 500            # 一键: clean → analyze

# 数据导入
python scripts/importers/import_partner_jsonl.py data/partner/demo.jsonl
python scripts/importers/import_seed_slang.py
python scripts/importers/import_slang_from_excel.py data/slang.xlsx

# 系统管理
python main.py init-db               # 初始化数据库
python main.py login -p <平台>        # 交互式登录
python main.py api                   # FastAPI (port 8000)
python main.py ui                    # Streamlit (port 8501)

# 测试
python -m pytest tests/ -v           # 41 tests
python scripts/collect_examples.py   # 生成示例数据

# 小模型训练
python scripts/modeling/train_roberta.py --epochs 3
```

---

## 数据流

```
采集 (collect-all) 
  → ods_raw_intel (RAW_COLLECTED)
    → 清洗 (clean) 
      → dwd_clean_intel (CLEANED)
        → OCR (ocr) → dwd_clean_intel.merged_text
        → 分析 (analyze) 
          → dwd_intel_analysis (ANALYZED)
          → dwd_entity (实体)
          → dwd_entity_relation (关系)
          → agent_report (报告)
          → Neo4j (图谱)
          → Milvus (向量)
          → Doris (OLAP宽表)
            → Dashboard (展示)
              → ChatBI (问答)
```

---

## 示例数据

```bash
# 查看已采集的示例
ls examples/

# 重新采集（需要有效的 Cookie）
python scripts/collect_examples.py --max-pages 2
```

当前示例覆盖 5 平台 246 条真实黑灰产数据（微博75/知乎39/小红书80/抖音44/贴吧8）。
