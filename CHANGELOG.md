# BGI 变更日志

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
