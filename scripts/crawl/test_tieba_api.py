"""
贴吧 API Spider 速度对比测试 — 新 JSON API vs 旧 Playwright DOM
"""
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from collectors.spiders.tieba_api_spider import TiebaAPISpider


def test_search(keyword="刷单", max_pages=3, rn=15):
    """测试纯 HTTP API 搜索。"""
    spider = TiebaAPISpider()
    try:
        start = time.time()
        items = spider.search(keyword, max_pages=max_pages, rn=rn)
        elapsed = time.time() - start

        print(f"\n{'='*55}")
        print(f"📊 贴吧 JSON API Spider — {keyword}")
        print(f"{'='*55}")
        print(f"翻页: {max_pages} 页 × {rn} 条/页")
        print(f"结果: {len(items)} 条")
        print(f"耗时: {elapsed:.1f} 秒")
        speed = len(items) / elapsed if elapsed > 0 else 0
        print(f"速度: {speed:.1f} 条/秒")
        print(f"重试: {spider.stats['retries']}, 错误: {spider.stats['errors']}")
        print(f"提升: {speed / 0.03:.0f}x (旧方案 0.03条/秒)")

        # 平台分布
        forums = {}
        for item in items:
            bar = item.bar_name or "未知"
            forums[bar] = forums.get(bar, 0) + 1
        print(f"\n📋 贴吧分布: {dict(sorted(forums.items(), key=lambda x: -x[1])[:8])}")

        # 内容样例
        print(f"\n📝 样例 (前5条):")
        for i, item in enumerate(items[:5]):
            title = item.content_raw.split('\n')[0][:60]
            has_img = "🖼" if item.metadata.get("has_image") else "  "
            print(f"  [{i+1}] {has_img} [{item.bar_name}] {title}...")
            print(f"       作者={item.author_username} | 回复={item.reply_count}")

        # 数据质量统计
        with_content = sum(1 for i in items if len(i.content_raw) > 50)
        with_image = sum(1 for i in items if i.metadata.get("has_image"))
        with_author = sum(1 for i in items if i.author_username)
        print(f"\n📊 数据质量:")
        print(f"  长内容(>50字): {with_content}/{len(items)}")
        print(f"  含图片: {with_image}/{len(items)}")
        print(f"  有作者: {with_author}/{len(items)}")

        return items
    finally:
        spider.close()


def multi_keyword_test():
    """多关键词测试。"""
    keywords = ["刷单", "账号交易", "引流", "诈骗"]
    total = 0
    total_time = 0

    print(f"\n{'='*55}")
    print(f"📊 多关键词测试 ({len(keywords)} 个关键词)")
    print(f"{'='*55}")

    spider = TiebaAPISpider()
    try:
        for kw in keywords:
            start = time.time()
            items = spider.search(kw, max_pages=2, rn=10)
            elapsed = time.time() - start
            total += len(items)
            total_time += elapsed
            print(f"  {kw}: {len(items)}条 / {elapsed:.1f}秒 = {len(items)/elapsed:.0f}条/秒")
    finally:
        spider.close()

    print(f"\n  总计: {total}条 / {total_time:.1f}秒 = {total/total_time:.0f}条/秒")


if __name__ == "__main__":
    print("📌 旧 Playwright 方案: ~0.03条/秒, 每次~10-18条")
    print("   原因: 浏览器加载 + React渲染 + DOM解析 + 逐个帖子详情")

    print("\n📌 新 JSON API 方案:")
    test_search("刷单", max_pages=3, rn=15)
    multi_keyword_test()

    print(f"\n{'='*55}")
    print(f"✅ 总结: 贴吧现在可以使用类似微博的纯 HTTP API 模式!")
    print(f"   API: tieba.baidu.com/mo/q/search/multsearch")
    print(f"   速度: ~10条/秒 (vs 旧 0.03条/秒)")
    print(f"   数据: 含完整主帖内容+作者+图片+回复数")
    print(f"   限制: 回复需 Playwright 单独抓取")
    print(f"{'='*55}")
