"""
微博关键词搜索功能测试（纯HTTP AJAX API）
用法: python scripts/crawl/weibo_search_smoke.py
      python scripts/crawl/weibo_search_smoke.py 刷单 2
"""
import sys
import re
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

# 强制 UTF-8 输出，避免 Windows GBK 终端乱码
sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore

from collectors.spiders.weibo_api_spider import WeiboAPISpider


def clean_text(text: str) -> str:
    """去除零宽字符等不可见符号，避免终端显示异常。"""
    return re.sub(r"[​‌‍‎‏﻿]", "", text)


def main():
    # ── 输入参数 ──────────────────────────────────────────────────────────
    keyword = sys.argv[1] if len(sys.argv) > 1 else "刷单"
    max_pages = int(sys.argv[2]) if len(sys.argv) > 2 else 1

    print("=" * 60)
    print(f"  微博关键词搜索测试")
    print(f"  关键词: {keyword}")
    print(f"  翻页数: {max_pages}")
    print("=" * 60)

    # ── 执行搜索 ──────────────────────────────────────────────────────────
    spider = WeiboAPISpider()
    items = spider.search(keyword, max_pages=max_pages)

    # ── 输出结果 ──────────────────────────────────────────────────────────
    print(f"\n共采集 {len(items)} 条微博\n")

    for i, item in enumerate(items, 1):
        print(f"━━━ 第 {i} 条 ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
        print(f"  用户名:    {clean_text(item.author_username)}")
        print(f"  用户UID:   {item.author_uid}")
        print(f"  发布时间:  {item.collected_at.strftime('%Y-%m-%d %H:%M')}")
        print(f"  内容类型:  {item.content_type}")
        print(f"  来源链接:  {item.source_url}")
        print(f"  关键词:    {item.keyword}")
        print(f"  转发数:    {item.reposts_count}")
        print(f"  评论数:    {item.comments_count}")
        print(f"  点赞数:    {item.attitudes_count}")
        print(f"  ─────────────────────────────────────────────")
        text = clean_text(item.content_raw)
        if len(text) > 150:
            text = text[:150] + "..."
        print(f"  正文: {text}")
        print()


if __name__ == "__main__":
    main()
