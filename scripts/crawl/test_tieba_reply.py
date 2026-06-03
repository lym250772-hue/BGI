"""贴吧新版提取回复"""
import sys, time, json
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))
from collectors.spiders.tieba_spider import TiebaSpider

spider = TiebaSpider(headless=True)
try:
    spider.start()
    tid = '10761715894'
    spider._page.goto(f'https://tieba.baidu.com/p/{tid}',
                       wait_until='networkidle', timeout=20000,
                       referer='https://tieba.baidu.com/index.html')
    time.sleep(5)
    for _ in range(3):
        spider._page.evaluate('window.scrollTo(0, document.body.scrollHeight)')
        time.sleep(2)

    replies = spider._page.evaluate("""
    () => {
        var results = [];
        var items = document.querySelectorAll('.pb-comment-item');
        items.forEach(function(item) {
            // Extract author
            var author = '';
            var authorEl = item.querySelector('.user-info .user-name, [class*=user-name], [class*=author]');
            if (authorEl) author = authorEl.innerText.trim();

            // Extract content
            var content = '';
            var contentEl = item.querySelector('[class*=content], .comment-content, [class*=text]');
            if (!contentEl) {
                // Try to find the main text by removing user-info area
                var clones = item.cloneNode(true);
                var userDiv = clones.querySelector('[class*=user-info], [class*=head-line]');
                if (userDiv) userDiv.remove();
                content = clones.innerText.trim();
            } else {
                content = contentEl.innerText.trim();
            }

            if (content.length > 2) {
                results.push({
                    author: author,
                    content: content.substring(0, 300),
                });
            }
        });
        return results;
    }
    """)
    print(f"回复数: {len(replies)}")
    for r in replies[:10]:
        print(f"  [{r['author']}] {r['content'][:100]}")
finally:
    spider.close()
