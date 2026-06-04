# BGI 变更日志

## 2026-06-04 — 评论大规模采集完成 v4.1

### 📊 评论采集成果: 1830篇/17916条 (22%覆盖率)

| 平台 | 帖子 | 有评论 | 总评论 | 技术 |
|------|:--:|:--:|:--:|------|
| 知乎 | 1,607 | 821 | 10,326 | HTTP API 内置 |
| 微博 | 1,768 | 362 | 2,461 | AJAX API 内置 |
| 小红书 | 2,556 | **222** | **2,986** | v3 持久化浏览器+响应拦截 |
| 抖音 | 1,167 | **233** | **1,267** | v3 持久化浏览器+响应拦截 |
| 贴吧 | 1,141 | 192 | 876 | DOM .pb-comment-item 提取 |
| **合计** | **8,239** | **1,830** | **17,916** | |

### 🆕 v3 采集引擎

| 文件 | 说明 |
|------|------|
| `scripts/crawl/douyin_comments_v3.py` | 持久化浏览器+自然节奏评论采集 |
| `scripts/crawl/xiaohongshu_comments_v3.py` | 持久化浏览器+自然节奏评论采集 |
| `scripts/crawl/douyin_comments_gentle.py` | v2 温和模式（备用） |
| `scripts/crawl/xiaohongshu_comments_gentle.py` | v2 温和模式（备用） |
| `scripts/crawl/debug_xhs_comment.py` | 小红书评论调试工具 |

### 🔑 关键突破

- **持久化浏览器配置**: `launch_persistent_context` → 一次登录永久复用
- **Edge内核**: `channel="msedge"` → 指纹更可信
- **自然节奏**: 高斯延迟 5-16s，无固定批次休息
- **反爬增强**: 高斯分布延迟、贝塞尔鼠标、随机回滚

### 🐛 修复

- 小红书: 假登录检测修复（页面内容检查替代cookie检查）
- 小红书: 评论API 461 → 重新登录后正常
- 抖音: 桌面应用CDP端口无法访问，改用持久化浏览器
- batch_comments: 移除首页导航冲突导致的navigation error

---

## 2026-06-03 最终版 — 全平台48黑话词大规模采集 + 评论打通

### 📊 采集成果: 5平台 8,239条

| 平台 | 条数 | 评论 | 技术突破 |
|------|:--:|:--:|------|
| 小红书 | 2,556 | ✅ | SSR提取 + 可见浏览器 |
| 微博 | 1,768 | ✅ | AJAX API |
| 知乎 | 1,607 | ✅ | HTTP API |
| 抖音 | 1,167 | ✅ | X-Bogus + 可见浏览器 |
| 贴吧 | 1,141 | 🔲 | JSON API ~10/s |

### 🆕 新增功能

| 模块 | 说明 |
|------|------|
| `collectors/comment_collector.py` | 统一评论采集: 响应拦截(小红书/抖音) + DOM提取(贴吧) |
| `collectors/normalizer.py` | 5平台统一IntelItem格式，含评论字段 |
| `collectors/spiders/tieba_api_spider.py` | 贴吧JSON API (~10/s, 300x提升) |
| `collectors/spiders/douyin_xbogus.js` | 抖音X-Bogus签名生成 (487KB execjs) |
| `scripts/crawl/douyin_batch.py` | 抖音分批拟人化采集 |
| `scripts/crawl/xiaohongshu_batch.py` | 小红书分批拟人化采集 |
| `scripts/crawl/douyin_get_tokens.py` | msToken交互式提取 |
| `scripts/crawl/douyin_visible_collect.py` | 抖音可见浏览器+评论采集 |
| `scripts/crawl/xiaohongshu_visible_collect.py` | 小红书可见浏览器采集 |

### 🔧 修复

- 小红书: API拦截→SSR提取 (window.__INITIAL_STATE__)
- 小红书: source_url增加xsec_token参数，可直接访问
- 抖音: 首页搜索框→X-Bogus签名API (page.evaluate fetch)
- 贴吧: Playwright DOM→纯HTTP JSON API
- IntelItem: 新增post_id/comments/tags/like_count等统一字段
- 反检测增强: 高斯延迟/贝塞尔鼠标/随机滚动/拟人输入

---

## 2026-06-03 (下午) — 贴吧 JSON API 加速（~300x 提升）🆕

### 🚀 贴吧从 Playwright → 纯 HTTP JSON API

| 指标 | 旧方案 | 新方案 |
|------|:--:|:--:|
| 技术 | Playwright DOM 解析 | HTTP `requests` + JSON API |
| 速度 | **0.03 条/秒** | **~10 条/秒** |
| 提升 | — | **~300x** |
| 内存 | ~400MB | ~50MB |

### 🔍 发现的内部 API

- 端点: `tieba.baidu.com/mo/q/search/multsearch`
- 方法: GET，返回 JSON
- 认证: Cookie（BDUSS + BAIDUID），**无需 sign 参数**
- 数据: 完整主帖内容 + 作者 + 图片列表 + 回复数

### 📁 新增文件

| 文件 | 说明 |
|------|------|
| `collectors/spiders/tieba_api_spider.py` | 纯 HTTP API Spider，兼容旧 search_and_parse() 接口 |
| `scripts/crawl/tieba_api_sniff.py` | API 抓包脚本（Playwright 网络拦截） |
| `scripts/crawl/test_tieba_api.py` | 速度对比测试脚本 |

### ⚠️ 已知限制

- 回复 API (`c.tieba.baidu.com/c/f/pb`) 需额外签名，暂时不可用
- 如需回复内容，可回退到旧 Playwright `tieba_spider.py`

---

## 2026-06-03 (上午) — 采集层恢复 + 示例数据更新

### ✏️ 恢复核心文件

| 模块 | 说明 |
|------|------|
| `collectors/spiders/base_spider.py` | Spider 基类（Cookie管理/反爬/检查点） |
| `collectors/spiders/weibo_api_spider.py` | 微博 AJAX API（~8条/秒，含评论采集） |
| `collectors/spiders/douyin_spider.py` | 抖音首页搜索+正则（含 image_list/video_cover_url） |
| `collectors/spiders/xiaohongshu_spider.py` | 小红书 API拦截+DOM（含 image_list） |
| `collectors/base.py, registry.py` | IntelItem 统一格式 + 平台注册表 |
| `collectors/douyin_collector.py, xiaohongshu_collector.py` | 抖音/小红书 Collector |

### 📊 示例数据更新

| 平台 | 条数 | 特点 |
|------|:--:|------|
| weibo | 380 | 5关键词x5页，含评论 |
| zhihu | 375 | 5关键词x5页，含答案+评论 |
| xiaohongshu | 180 | 3关键词x3页，含图片列表 |
| douyin | 123 | 3关键词x3页，含封面+图片 |
| tieba | 18 | 3关键词x2页，含回复 |

### 🔧 修复

- `collect_examples.py`：微博接入评论采集、贴吧启用回复采集、清除增量状态
- `cleaner/__init__.py`：移除已删除的 media_processor 导入
- 文档全部更新至当前状态

---

## 2026-06-02 — 大规模多通道并发采集 + 知乎API加速 + 评论采集 + 图文存储 (v2.0)

### 🆕 并发编排引擎

| 模块 | 说明 |
|------|------|
| `collectors/orchestrator.py` | 多通道并发编排器 — 每平台独立线程并行，RateLimiter令牌桶限速，ProgressTracker实时统计，SIGINT优雅停机+断点保存 |
| `storage/write_pipeline.py` | 生产者-消费者写入管道 — Queue背压，单consumer线程批量INSERT，失败自动重试（指数退避） |
| `main.py collect-all` 命令 | `python main.py collect-all -k "刷单,接码" --max-pages 3` 一键全通道并发 |

### 🆕 知乎纯 HTTP API Spider

| 模块 | 说明 |
|------|------|
| `collectors/spiders/zhihu_api_spider.py` | 纯 requests 知乎采集 — 搜索+答案+评论三合一，3-5条/秒（15-25x提升），零浏览器开销 |
| orchestrator 集成 | 知乎自动走 HTTP 通道，不再启动 Playwright |

### 🆕 评论/回复采集

| 平台 | 状态 | 说明 |
|------|:--:|------|
| 微博 | ✅ | `get_comments()` 已接入collector，评论生成独立 IntelItem (content_type="comment") |
| 知乎 | ✅ | ZhihuAPISpider 内置 `get_comments()`，评论嵌套在 metadata.answers[].comments |
| 贴吧 | ✅ | `_fetch_thread_detail()` 已在 fetch_replies 模式下工作 |
| 小红书 | ❌ | 需 X-s/X-t 签名，当前仅记录 comment_count |
| 抖音 | ❌ | 需 msToken/Bogus 签名 |

### 🆕 图文数据采集 & 存储

| 模块 | 说明 |
|------|------|
| `collectors/base.py` | IntelItem 新增 `image_urls` + `video_cover_url` 字段 |
| `collectors/orchestrator.py` | `_parsed_to_dict()` 修复 `media_urls` 永远为空的 BUG，新增 `_collect_media_urls()` + `_compute_media_hash()` |
| `collectors/spiders/douyin_spider.py` | `ParsedDouyinItem` 新增 `image_list`，图集图片 URL 不再丢弃 |
| `storage/media_store.py` | 图片下载+持久存储 — 线程池并发下载，MD5去重，自动格式检测，`data/images/{platform}/{raw_id}/` |

### 🔧 断点续采接入

| 文件 | 说明 |
|------|------|
| `tieba_spider.py` | 接入 `start_page` + `checkpoint_callback`，支持中断恢复 |
| `zhihu_spider.py` | 同上（while循环模式）|
| `xiaohongshu_spider.py` | 同上（for循环模式）|
| `douyin_spider.py` | 同上（首页导航模式，关键词级恢复）|

### 📄 文档 & 示例

| 变更 | 说明 |
|------|------|
| `docs/操作手册.md` | 完全重写 — 全通道采集/完整工作流/命令速查/故障排查 |
| `docs/数据采集层技术文档.md` | v3.0 更新 — 新架构图/渠道矩阵/并发引擎/图片管道 |
| `examples/` | 5平台72+条真实黑灰产样本（微博75/知乎39/小红书80/抖音44/贴吧8） |
| `scripts/collect_examples.py` | 一键样本采集脚本 |
| `examples/README.md` | 数据格式说明 + 重新采集指南 |

---

## 2026-06-02 — 小红书/抖音采集器 + Emoji翻译 + Metadata增强 + 交互式登录

### 🆕 新增平台

| 模块 | 说明 |
|------|------|
| 小红书 Spider | `collectors/spiders/xiaohongshu_spider.py` — API拦截+DOM兜底，提取标题/正文/标签/图片列表/赞藏评，支持灰黑产笔记采集 |
| 小红书 Collector | `collectors/xiaohongshu_collector.py` — ParsedXiaohongshuItem → IntelItem |
| 抖音 Spider | `collectors/spiders/douyin_spider.py` — page.evaluate(fetch)+SSR+DOM三路解析，提取描述/话题/播放量/时长/封面图 |
| 抖音 Collector | `collectors/douyin_collector.py` — ParsedDouyinItem → IntelItem |
| 测试脚本 | `tests/test_xiaohongshu_search.py` / `tests/test_douyin_search.py` |

### 🆕 Emoji 语义翻译系统

| 模块 | 说明 |
|------|------|
| `cleaner/emoji_translator.py` | 120+条目灰黑产emoji词典，9大分类(contact/money/gambling/adult/illegal/gaming/trust/platform/identity)，全面Unicode覆盖(60+block)，translate/extract_emojis/get_risk_signals API，零依赖零API开销 |
| 修复 Unicode 检测 | `BaseSpider.contains_emoji()` 扩展到60+ Unicode block（补充8个缺失block） |

### 🆕 Metadata 增强分类

| 模块 | 说明 |
|------|------|
| `analyzer/metadata_classifier.py` | L1.5分类器：50+ hashtag规则覆盖7大风险类别，播放量异常检测，短视频导流检测，零API开销 |
| 风险评分增强 | 新增Factor 7 `metadata_signals` 权重0.10，调整各因子权重 |

### 🆕 异步 OCR 管道

| 模块 | 说明 |
|------|------|
| `cleaner/media_bridge.py` | 异步图片下载+PaddleOCR管道，24h缓存，写入dwd_clean_intel.ocr_text/merged_text |
| `main.py ocr` 命令 | `python main.py ocr -p douyin,xiaohongshu -l 100` |

### 🆕 交互式登录

| 功能 | 说明 |
|------|------|
| `BaseSpider.interactive_login()` | 弹出浏览器→手动登录→按Enter→自动保存Cookie |
| `main.py login` 命令 | `python main.py login -p weibo/zhihu/tieba/xiaohongshu/douyin` |
| Cookie检查 | collect命令自动检查Cookie，缺失时提示login |

### ✏️ 管道增强

| 变更 | 说明 |
|------|------|
| 平台感知噪声过滤 | `is_noise()` 新增platform/metadata参数，抖音min=2chars，emoji+hashtag短文本不丢弃 |
| Emoji翻译步骤 | `process()` 新增Step 0 emoji翻译 + Step 0.5 metadata增强 |
| 修复正则bug | `LOW_VALUE_PATTERNS` 中 `\\u` 转义修复为正确Unicode范围 |
| clean命令适配 | 传递platform+metadata到管道，使用真实noise_score |

### 🔒 安全

| 变更 | 说明 |
|------|------|
| 根目录 `.gitignore` | 保护.idea/.claude/.pytest_cache/*.docx |
| 调试文件清理 | 删除15+含个人信息的截图/HTML/输出文件 |
| Cookie文件验证 | `data/raw/` 已被gitignore完全排除 |

### ✅ 测试验证

| 测试 | 结果 |
|------|:----:|
| 37个单元测试 | 全部通过 |
| 知乎端到端(30关键词) | 501条/172秒，零错误 |
| 清洗管道(501条) | 保留258条(51.5%)，命中高危254条 |
| Emoji翻译器 | 120+条目词典，<1ms响应 |

---

## 2026-06-01 — 采集层大规模重构 + 清洗层高危过滤

### 采集层重构

| 模块 | 变更 |
|------|------|
| BaseSpider | 🆕 `collectors/spiders/base_spider.py` — 三平台公共基类，统一浏览器生命周期、UA池(7个)、Cookie管理(EditThisCookie格式标准化)、三级重试、断点续采、自适应延迟、请求拦截 |
| 知乎 Spider | ✏️ 重写为 API 直调模式 (`/api/v4/search_v3`)，零 HTML 解析，不受页面改版影响。支持无限翻页、增量/全量双模式、回答+评论采集 |
| 贴吧 Spider | ✏️ 重写 DOM 提取，适配新版 React 渲染页面。networkidle 等待渲染、通用帖子链接遍历 |
| 微博 Spider | ✏️ 继承 BaseSpider，代码量减少 55% |
| 采集器注册 | 🆕 `collectors/registry.py` — 6 平台工厂映射 |
| Telegram | 🆕 `collectors/telegram_collector.py` |
| Web 通用 | 🆕 `collectors/web_collector.py` (stub) |

### 采集器核心能力

| 能力 | 说明 |
|------|------|
| 批量入库 | `executemany` 100~200 条/批，速度 10x+ |
| 无限翻页 | `max_pages=0` 自动翻到空结果 |
| 全量/增量 | `--no-incremental` 全量 / `--incremental` 增量 |
| 关键词文件 | `--keyword-file data/grey_keywords.json` 85 个灰黑产关键词 |
| 评论采集 | 知乎默认开启 `fetch_comments`，存储于 `metadata.answers[].comments[]` |
| 回复关联 | 贴吧回复存储于 `metadata.replies[]`，每条含 author/content/time/floor |

### 清洗层高危过滤

| 变更 | 说明 |
|------|------|
| 实体检测 | `has_entities()` — 检测微信/QQ/手机/URL/群号等 10 种模式 |
| 风险判定 | `is_risk_relevant()` — 高危关键词 OR 含可追溯实体 → 保留；否则丢弃 |
| 保留率 | 55.3% (1,073/1,942) |

### 数据采集实测 (知乎)

| 指标 | 数值 |
|------|------|
| 采集总量 | 2,271 条 |
| 清洗保留 | 1,073 条 (高危) |
| 关键词覆盖 | 50 个灰黑产关键词 |
| 错误率 | 0% |
| 速度 | 3.3 条/秒 (无回答模式更快) |

### Cookie 管理改进

- 环境变量 → `data/raw/{platform}_cookies.json` 文件化
- EditThisCookie 导出格式自动标准化 (`no_restriction` → `None`, `expirationDate` → `expires`)
- `.env` 中旧 Cookie 已清除，文件优先

### 贴吧已知问题

- 百度安全验证频繁触发
- 新版 React 页面 `networkidle` 加载超时
- 搜索页与首页 DOM 混合渲染，帖子提取不稳定

---

## 2026-05-25 (5) — 三平台采集测试验证 + 微博反爬增强

### 三平台采集渠道实测通过

以关键词"刷单"对所有已实现平台进行端到端测试：

| 平台 | 状态 | 采集量 | 数据质量 |
|------|:----:|:------:|------|
| 贴吧 | ✅ | 4条/页 | 社区真实讨论，含帖吧名、用户、回复数、正文 |
| 知乎 | ✅ | 10条/页 | 问题+摘要+完整回答，含赞数/评论数 |
| 微博 | ✅ | 20条/页 | 字段最完整，含用户名/UID/时间/内容类型/链接 |
| Telegram | ⚠️ | - | API ID/Hash 未配置 |

### 贴吧 Cookie 修复

- BDUSS Cookie 过期导致百度安全验证 → 重新登录获取新凭证后恢复
- 问题：短时间内连续请求（~2min内3次）仍会触发验证码，需控制采集频率

### 微博 Spider 反爬增强

- 新增 User-Agent 池（5个UA随机轮换），与贴吧/知乎对齐
- Cookie 加载统一为 `_load_cookies()` 方法（env 优先，文件兜底）
- 新增 `--no-sandbox` 启动参数

### 三平台反爬策略对齐

| 策略 | 贴吧 | 知乎 | 微博 |
|------|:--:|:--:|:--:|
| UA 池 | ✅ | ✅ | ✅ |
| webdriver 隐藏 | ✅ | ✅ | ✅ |
| Cookie 注入 | ✅ | ✅ | ✅ |
| 随机间隔 | 2.5~5s | 3~6s | 2.5~5.5s |
| 首页预热 | ✅ | ✅ | ✅ |
| 增量采集 | ✅ | ✅ | ✅ |
| 验证码检测 | ✅ | ✅ | ✅ |

---

## 2026-05-25 (4) — 知乎 Spider 打通 + 贴吧 Referer 修复

### 知乎 Spider 攻克（P0 完成）

经过多轮调试，知乎搜索采集完全打通：

**核心发现：**
1. `context.add_cookies()` 对知乎完全无效 → 改用 JS `document.cookie` 注入
2. 必须只注入认证 Cookie（`z_c0`/`d_c0`），不能覆盖服务端会话 Cookie（`JOID`/`osd`/`__zse_ck`）
3. `z_c0` 是 HttpOnly Cookie，浏览器 Console 读不到，必须从 Application 面板获取完整值
4. JS 设置的 Cookie 在页面导航后会丢失 → 采用「先导航 → 注入 Cookie → reload」策略
5. 知乎搜索结果通过 XHR 动态加载到 DOM，不在 SSR 中 → 解析 `.SearchResult-Card` 元素

**最终技术路线：**
- `start()`: 访问知乎首页 → JS 注入 z_c0 + d_c0
- `_fetch_and_parse_search_page()`: 导航到搜索页 → 重新注入 Cookie → reload → 等待 `.SearchResult-Card` 渲染 → DOM 解析
- 结果：10条/页，包含问题标题、回答摘要、作者、赞数、评论数、话题标签

### 贴吧 Spider Referer 修复
- `_fetch_search_page()`: 添加 `referer="https://tieba.baidu.com/index.html"` 绕过百度安全验证

### 修改文件
- `collectors/spiders/zhihu_spider.py` — 重写 start()、_fetch_and_parse_search_page()、_parse_search_from_dom()
- `collectors/spiders/tieba_spider.py` — 修复选择器 + Referer + HTML 注释兼容
- `方案.md` — 更新进度
- `CHANGELOG.md` — 本文档

---

## 2026-05-25 (3) — Cookie 管理重构 + 贴吧选择器修复

### 修改

**Cookie 管理统一为 .env 环境变量方式**
- `config/settings.py` — 新增 `weibo_cookies` / `tieba_cookies` / `zhihu_cookies` 三个配置项（`BGI_` 前缀）
- 三个 Spider (`weibo_spider.py` / `tieba_spider.py` / `zhihu_spider.py`) 统一新增 `_load_cookies()` 静态方法
  - 优先级: 环境变量 `BGI_{PLATFORM}_COOKIES` > 文件 `data/raw/{platform}_cookies.json`
  - 与 LLM API Key (`BGI_LLM_API_KEY`) 管理方式一致
- `.env.template` — 新增 Cookie 配置模板和获取说明
- `方案.md` — 新增"环境配置说明"章节，含 Cookie 获取步骤

**贴吧 Spider 选择器修复（适配新版 Vue 页面结构）**
- `tieba_spider.py` — 重写 `_extract_search_cards()` 和 `_parse_one_card()`：
  - 新版选择器: `.threadcardclass.thread-new3` / `.title-wrap span` / `.abstract-wrap span` / `.forum-name-text` / `.forum-attention.user`
  - 修复 `<!---->` HTML 注释阻断正则的问题
  - 预热策略优化：主 page 先访问首页再搜索，降低验证码触发概率
  - 新增 "发布于 YYYY-M-D" 时间格式解析

**CLI 完善**
- `main.py` — `collect` 命令新增 `--keywords` / `-k`、`--max-pages`、`--fetch-replies` / `--no-fetch-replies` 参数

---

## 2026-05-25 (2) — 多源数据采集：知乎 Spider 实现

### 新增

**知乎 Spider (P0 公开论坛)**
- `collectors/spiders/zhihu_spider.py` — Playwright + API 拦截驱动的知乎搜索 Spider
  - 核心策略：通过 `page.evaluate()` 在浏览器上下文调用知乎搜索 API (`/api/v4/search_v3`)，获取结构化 JSON
  - 优势：无需处理 `x-zse-96` 签名头，浏览器自动携带所有验证信息
  - 支持完整回答采集（问题答案 API `/api/v4/questions/{qid}/answers`）
  - 支持评论采集（可选，回答评论 API `/api/v4/answers/{aid}/comments`）
  - HTML 内容清理（知乎回答是 rich HTML）
  - 话题/标签提取
  - Unicode emoji 表情检测
  - 增量采集：按关键词记录最后采集时间
  - 反爬策略：较长随机间隔 (3~6s)、Cookie 注入、webdriver 隐藏
  - 数据结构：`ParsedZhihuItem` + `ParsedZhihuComment`
- `collectors/zhihu_collector.py` — 实现 `BaseCollector` 接口的知乎采集器适配器
- `tests/test_zhihu_search.py` — 知乎搜索测试脚本
  - 支持 `--no-answers`（快速模式，只取搜索摘要）
  - 支持 `--comments`（同时拉取评论，慢）

### 修改
- `collectors/spiders/__init__.py` — 导出 `ZhihuSearchSpider`
- `collectors/__init__.py` — 导出 `ZhihuCollector`
- `collectors/registry.py` — 知乎平台改为 `ZhihuCollector`（替换 WebCollector stub）
- `main.py` — 知乎/贴吧共享关键词参数逻辑
- `方案.md` — 更新进度表（P0 全部完成）
- `CHANGELOG.md` — 本文档

### 技术选型说明

1. **为什么用 API 拦截而非 HTML 解析？**
   知乎搜索页是 SPA，HTML 为空白壳。搜索数据通过 `/api/v4/search_v3` 以 JSON 返回。
   API 有 `x-zse-96` 签名头保护，但 Playwright 真实浏览器 + `page.evaluate()` 在页面上下文内
   执行 `fetch()` 会自动携带该签名，无需逆向。

2. **与贴吧 Spider 的架构差异**
   - 贴吧：传统 HTML 解析（有可解析的静态骨架）
   - 知乎：API JSON 解析（纯 SPA，搜索结果是 XHR 加载的）

3. **请求间隔选择**
   知乎反爬强于贴吧，选择了 3~6s 随机间隔（贴吧 2~5s）。

---

## 2026-05-25 (1) — 多源数据采集：贴吧 Spider 实现

### 新增

**贴吧 Spider (P0 公开论坛)**
- `collectors/spiders/tieba_spider.py` — Playwright 驱动的贴吧关键词搜索 Spider
  - 支持关键词搜索，每页最多50条结果，支持翻页控制
  - 支持帖子详情页采集（完整正文 + 回帖内容）
  - 支持表情符号提取：Unicode emoji 保留 + 贴吧 BDE_Smiley 图片表情 alt 文本提取
  - 增量采集：按关键词记录最后采集时间，存储至 `data/raw/tieba_last_collected.json`
  - 反爬策略：随机 User-Agent 池（5个UA轮换）、2~5s 随机请求间隔、navigator.webdriver 隐藏
  - Cookie 登录态注入支持（`data/raw/tieba_cookies.json`）
  - 数据结构：`ParsedTiebaItem` + `ParsedReply`
- `collectors/tieba_collector.py` — 实现 `BaseCollector` 接口的贴吧采集器适配器
  - 将 ParsedTiebaItem 转换为标准 IntelItem 格式
  - 回复数据序列化为 metadata.replies

**测试**
- `tests/test_tieba_search.py` — 贴吧搜索测试脚本
  - 支持命令行参数：关键词、翻页数、`--no-replies` 开关
  - 输出完整的帖子信息和回复内容预览

### 修改

- `collectors/spiders/__init__.py` — 导出 `TiebaSpider`
- `collectors/__init__.py` — 导出 `TiebaCollector`
- `collectors/registry.py` — 贴吧平台注册改为 `TiebaCollector`（替换原 WebCollector stub）
- `main.py` — `collect` 命令新增 `--keywords`/`-k`、`--max-pages`、`--fetch-replies`/`--no-fetch-replies` 参数
- `方案.md` — 新增多源数据采集模块实施进度表

### 技术路线说明

1. 选择 Playwright 而非 Scrapy 的原因：贴吧搜索结果由 Ajax 动态渲染，必须用浏览器引擎
2. 两阶段采集设计：搜索结果层（快速获取元信息）+ 帖子详情层（可选，获取全文和回复）
3. 增量采集以关键词为粒度，每个关键词记录独立的时间戳
4. 表情符号提取分两层：HTML 解析时转换 BDE_Smiley img 标签为 `[表情名]`，Unicode emoji 原生保留在文本中
5. User-Agent 池设计为可扩展，目前5个常用 UA 随机轮换

### 后续计划

- [ ] 知乎 Spider（P0，可复用 TiebaSpider 模式）
- [ ] 小红书 Spider（P1，需处理特殊的反爬机制）
- [ ] 统一 JSON 文件输出格式
- [ ] 图片 OCR 文字提取
