"""
知乎关键词搜索功能测试
用法: python tests/test_zhihu_search.py
      python tests/test_zhihu_search.py 刷单 2             # 自定义关键词和页数
      python tests/test_zhihu_search.py 刷单 1 --no-answers # 不拉取完整回答（快速模式）
      python tests/test_zhihu_search.py 刷单 1 --comments   # 同时拉取评论（慢）
"""
import sys
import re
import argparse
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from collectors.spiders.zhihu_spider import ZhihuSearchSpider


def clean_text(text: str) -> str:
    """去除零宽字符等不可见符号。"""
    return re.sub(r"[​‌‍‎‏﻿]", "", text)


def main():
    parser = argparse.ArgumentParser(description="知乎关键词搜索测试")
    parser.add_argument("keyword", nargs="?", default="刷单", help="搜索关键词")
    parser.add_argument("max_pages", nargs="?", type=int, default=1, help="翻页数")
    parser.add_argument("--no-answers", action="store_true", help="不拉取完整回答内容")
    parser.add_argument("--comments", action="store_true", help="同时拉取评论")
    parser.add_argument("--headless", type=bool, default=True, help="无头模式")
    args = parser.parse_args()

    print("=" * 60)
    print(f"  知乎关键词搜索测试")
    print(f"  关键词: {args.keyword}")
    print(f"  翻页数: {args.max_pages}")
    print(f"  拉取回答: {'否' if args.no_answers else '是'}")
    print(f"  拉取评论: {'是' if args.comments else '否'}")
    print("=" * 60)

    spider = ZhihuSearchSpider(
        headless=args.headless,
        fetch_answers=not args.no_answers,
        fetch_comments=args.comments,
    )
    spider.start()
    items = spider.search_and_parse(args.keyword, max_pages=args.max_pages)
    spider.close()

    print(f"\n共采集 {len(items)} 条知乎内容\n")

    for i, item in enumerate(items, 1):
        print(f"━━━ 第 {i} 条 ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
        print(f"  类型:      {item.metadata.get('result_type', '?')}")
        print(f"  作者:      {clean_text(item.author_username)}")
        print(f"  作者UID:   {item.author_uid}")
        print(f"  发布时间:  {item.collected_at.strftime('%Y-%m-%d %H:%M') if item.collected_at else '未知'}")
        print(f"  赞/评论:   {item.voteup_count}赞 / {item.comment_count}评")
        print(f"  话题:      {', '.join(item.topics[:5])}")
        print(f"  问题ID:    {item.question_id}")
        print(f"  链接:      {item.source_url}")
        print(f"  含表情:    {item.metadata.get('has_emoji', False)}")
        print(f"  ─────────────────────────────────────────────")
        text = clean_text(item.content_raw)
        if len(text) > 300:
            text = text[:300] + "..."
        print(f"  内容: {text}")

        # 显示回答列表
        answers = item.metadata.get("answers", [])
        if answers:
            print(f"  ── 回答 ({len(answers)} 条) ──")
            for a in answers[:3]:
                a_text = clean_text(a.get("content", ""))
                if len(a_text) > 100:
                    a_text = a_text[:100] + "..."
                author = a.get("author_username", "?")
                votes = a.get("voteup_count", 0)
                print(f"    @{author} ({votes}赞): {a_text}")

                # 评论
                comments = a.get("comments", [])
                if comments:
                    for c in comments[:2]:
                        c_text = clean_text(c.get("content", ""))
                        if len(c_text) > 60:
                            c_text = c_text[:60] + "..."
                        print(f"      └ {c.get('author_username', '?')}: {c_text}")
            if len(answers) > 3:
                print(f"    ... 还有 {len(answers) - 3} 条回答")
        print()


if __name__ == "__main__":
    main()
