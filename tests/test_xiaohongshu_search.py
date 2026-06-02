"""
小红书关键词搜索功能测试
用法: python tests/test_xiaohongshu_search.py
      python tests/test_xiaohongshu_search.py 刷单 2        # 自定义关键词和页数
      python tests/test_xiaohongshu_search.py 刷单 1 --headful # 有头模式调试
"""
import sys
import re
import argparse
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from collectors.spiders.xiaohongshu_spider import XiaohongshuSearchSpider


def clean_text(text: str) -> str:
    """去除零宽字符等不可见符号。"""
    return re.sub(r"[​‌‍‎‏﻿]", "", text)


def main():
    parser = argparse.ArgumentParser(description="小红书关键词搜索测试")
    parser.add_argument("keyword", nargs="?", default="刷单", help="搜索关键词")
    parser.add_argument("max_pages", nargs="?", type=int, default=1, help="翻页数")
    parser.add_argument("--headful", action="store_true", help="有头模式（调试用）")
    args = parser.parse_args()

    print("=" * 60)
    print(f"  小红书关键词搜索测试")
    print(f"  关键词: {args.keyword}")
    print(f"  翻页数: {args.max_pages}")
    print(f"  模式: {'有头调试' if args.headful else '无头'}")
    print("=" * 60)

    spider = XiaohongshuSearchSpider(headless=not args.headful)
    try:
        spider.start()
        results = spider.search_and_parse(args.keyword, max_pages=args.max_pages)

        print(f"\n共采集 {len(results)} 条小红书笔记\n")

        for i, item in enumerate(results, 1):
            print(f"━━━ 第 {i} 条 ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
            print(f"  笔记ID:    {item.note_id}")
            print(f"  作者:      {item.author_username}  (UID: {item.author_uid})")
            print(f"  类型:      {item.content_type}")
            print(f"  赞/藏/评:  {item.like_count}赞 / {item.collect_count}藏 / {item.comment_count}评")
            print(f"  标签:      {', '.join(item.tags) if item.tags else '(无)'}")
            print(f"  图片数:    {len(item.image_list)}")
            print(f"  链接:      {item.source_url}")
            print(f"  含表情:    {item.metadata.get('has_emoji', False)}")
            print(f"  解析方式:  {item.metadata.get('parse_method', 'unknown')}")
            print(f"  ─────────────────────────────────────────────")
            content = clean_text(item.content_raw)
            print(f"  内容: {content[:300]}{'...' if len(content) > 300 else ''}")
            print()

    finally:
        spider.close()

    print(f"\n统计: pages={spider.stats['pages_loaded']}, retries={spider.stats['retries']}, errors={spider.stats['errors']}")


if __name__ == "__main__":
    main()
