"""
贴吧关键词搜索功能测试
用法: python scripts/crawl/tieba_search_smoke.py
      python scripts/crawl/tieba_search_smoke.py 刷单 2
      python scripts/crawl/tieba_search_smoke.py 刷单 1 --no-replies
"""
import sys
import re
import argparse
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from collectors.spiders.tieba_spider import TiebaSpider


def clean_text(text: str) -> str:
    """去除零宽字符等不可见符号，避免终端显示异常。"""
    return re.sub(r"[​‌‍‎‏﻿]", "", text)


def main():
    parser = argparse.ArgumentParser(description="贴吧关键词搜索测试")
    parser.add_argument("keyword", nargs="?", default="刷单", help="搜索关键词")
    parser.add_argument("max_pages", nargs="?", type=int, default=1, help="翻页数")
    parser.add_argument("--no-replies", action="store_true", help="不采集帖子详情和回复")
    parser.add_argument("--headless", type=bool, default=True, help="无头模式")
    args = parser.parse_args()

    print("=" * 60)
    print(f"  贴吧关键词搜索测试")
    print(f"  关键词: {args.keyword}")
    print(f"  翻页数: {args.max_pages}")
    print(f"  采集回复: {'否' if args.no_replies else '是'}")
    print("=" * 60)

    spider = TiebaSpider(
        headless=args.headless,
        fetch_replies=not args.no_replies,
    )
    spider.start()
    items = spider.search_and_parse(args.keyword, max_pages=args.max_pages)
    spider.close()

    print(f"\n共采集 {len(items)} 条贴吧帖子\n")

    for i, item in enumerate(items, 1):
        print(f"━━━ 第 {i} 条 ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
        print(f"  贴吧:      {clean_text(item.bar_name)}")
        print(f"  用户名:    {clean_text(item.author_username)}")
        print(f"  用户UID:   {item.author_uid}")
        print(f"  发布时间:  {item.collected_at.strftime('%Y-%m-%d %H:%M') if item.collected_at else '未知'}")
        print(f"  回复数:    {item.reply_count}")
        print(f"  Thread ID: {item.thread_id}")
        print(f"  链接:      {item.source_url}")
        print(f"  关键词:    {item.keyword}")
        print(f"  含表情:    {item.metadata.get('has_emoji')}")
        print(f"  含图片:    {item.metadata.get('has_image')}")
        print(f"  ─────────────────────────────────────────────")
        text = clean_text(item.content_raw)
        if len(text) > 200:
            text = text[:200] + "..."
        print(f"  正文: {text}")

        # 显示回复
        replies = item.metadata.get("replies", [])
        if replies:
            print(f"  ── 回复 ({len(replies)} 条) ──")
            for r in replies[:5]:
                r_text = clean_text(r.get("content", ""))
                if len(r_text) > 80:
                    r_text = r_text[:80] + "..."
                print(f"    L{r.get('floor', '?')} {r.get('author_username', '?')}: {r_text}")
            if len(replies) > 5:
                print(f"    ... 还有 {len(replies) - 5} 条回复")
        print()


if __name__ == "__main__":
    main()
