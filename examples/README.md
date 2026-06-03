# 多源数据采集示例

本目录存放各平台数据采集接口的示例输出，供协作者对照开发使用。

## 文件说明

| 文件 | 平台 | 采集量 | 关键词 | 说明 |
|------|------|:------:|--------|------|
| `weibo_sample.json` | 微博 | 20条 | 刷单 | 含用户名、UID、时间、内容类型、链接等完整字段 |
| `zhihu_sample.json` | 知乎 | 10条 | 刷单 | 含问题、摘要、完整回答（赞数/评论数）、话题标签 |
| `tieba_sample.json` | 贴吧 | 4条 | 刷单 | 含帖吧名、用户名、回复数、正文、表情/图片检测 |

## 数据结构

所有平台输出统一为以下 JSON 格式：

```json
{
  "platform": "平台标识",
  "keyword": "搜索关键词",
  "count": 采集数量,
  "items": [
    {
      "platform": "平台名",
      "author_username": "作者用户名",
      "content_raw": "原始内容文本",
      "source_url": "来源链接",
      "collected_at": "采集时间 (ISO 8601)",
      "keyword": "匹配关键词",
      ...
    }
  ]
}
```

## 采集接口

各平台采集测试命令：

```bash
# 微博（20条/页）
python tests/test_weibo_search.py "刷单" 1

# 知乎（10条/页，含回答）
python tests/test_zhihu_search.py "刷单" 1

# 贴吧（4~50条/页，含回复）
python tests/test_tieba_search.py "刷单" 1
```

## 注意事项

- 贴吧反爬较强，短时间多次请求会触发百度滑块验证码，建议采集间隔 > 5 分钟
- 知乎需要有效的 `z_c0` Cookie，JS 注入方式与常规 `add_cookies` 不同
- 微博 Cookie 有较长有效期，部分字段（如长文/视频检测）需要展开全文
- Telegram 需要 API ID/Hash，目前未配置
