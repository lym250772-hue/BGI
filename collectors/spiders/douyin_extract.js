// douyin_search_helper.js — 在 douyin 搜索页面提取视频卡片
() => {
    var results = [];
    var seen = {};
    var links = document.querySelectorAll('a');
    links.forEach(function(a) {
        var href = a.href;
        var idx = href.indexOf('/video/');
        if (idx === -1) return;
        var vid = href.substring(idx + 7).split('?')[0];
        if (!vid || seen[vid]) return;
        seen[vid] = true;
        var c = a.closest('div');
        if (c) c = c.parentElement;
        var text = (c ? c.innerText : a.innerText) || '';
        text = text.trim();
        if (text.length > 15) {
            text = text.substring(0, 200);
            results.push({vid: vid, text: text});
        }
    });
    return results;
}
