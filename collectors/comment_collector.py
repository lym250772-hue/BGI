"""
统一评论采集器 — 打开帖子详情页，截获评论 API 或从 DOM 提取评论。

支持平台:
  - 小红书: 打开 note 页 → 截获 /api/sns/web/v2/comment/page
  - 抖音:   打开 video 页 → 截获评论 API
  - 贴吧:   打开 thread 页 → DOM 提取回复
"""

import time
import json
import re
import random
from typing import Any
from loguru import logger


# ═══════════════════════════════════════════════════════════════════════════════
# 统一评论格式（对齐 IntelItem.comments）
# ═══════════════════════════════════════════════════════════════════════════════

def make_unified_comment(
    id: str = "",
    author_uid: str = "",
    author_username: str = "",
    content: str = "",
    like_count: int = 0,
    reply_to: str = "",
    created_at: str = "",
    comment_type: str = "comment",
) -> dict:
    return {
        "id": str(id),
        "author_uid": str(author_uid),
        "author_username": author_username,
        "content": content,
        "like_count": like_count,
        "reply_to": reply_to,
        "created_at": created_at,
        "type": comment_type,
    }


# ═══════════════════════════════════════════════════════════════════════════════
# 小红书评论
# ═══════════════════════════════════════════════════════════════════════════════

def fetch_xiaohongshu_comments(page, note_id: str, xsec_token: str = "",
                               max_pages: int = 3) -> list[dict]:
    """打开小红书笔记页，通过响应拦截捕获评论 API（自动带 X-s 签名）。

    Args:
        page: Playwright page（需已登录）
        note_id: 笔记 ID
        xsec_token: 安全令牌（搜索时从 SSR 获取）
        max_pages: 最大翻页数
    """
    comments = []

    url = f"https://www.xiaohongshu.com/explore/{note_id}"
    if xsec_token:
        url += f"?xsec_token={xsec_token}"

    for pn in range(max_pages):
        captured = []

        def on_response(response):
            if "/comment/page" in response.url and "note_id=" + note_id in response.url:
                try:
                    body = response.json()
                    if body.get("success"):
                        captured.append(body)
                except Exception:
                    pass

        try:
            page.on("response", on_response)

            if pn == 0:
                page.goto(url, wait_until="domcontentloaded", timeout=20000)
                time.sleep(3)
                # 滚动触发评论加载
                page.evaluate("window.scrollBy(0, 1500)")
                time.sleep(3)
            else:
                page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                time.sleep(3)

            # 移除监听器
            page.remove_listener("response", on_response)

            if not captured:
                break

            page_comments = captured[0].get("data", {}).get("comments", [])
            for c in page_comments:
                user = c.get("user_info", {}) or {}
                comments.append(make_unified_comment(
                    id=c.get("id", ""),
                    author_uid=str(user.get("user_id", "")),
                    author_username=user.get("nickname", ""),
                    content=c.get("content", ""),
                    like_count=c.get("like_count", 0),
                    created_at=str(c.get("create_time", "")),
                    comment_type="comment",
                ))
                for sub in c.get("sub_comments", []):
                    sub_user = sub.get("user_info", {}) or {}
                    target = sub.get("target_comment", {}) or {}
                    target_user = target.get("user_info", {}) or {}
                    comments.append(make_unified_comment(
                        id=sub.get("id", ""),
                        author_uid=str(sub_user.get("user_id", "")),
                        author_username=sub_user.get("nickname", ""),
                        content=sub.get("content", ""),
                        like_count=sub.get("like_count", 0),
                        reply_to=target_user.get("nickname", ""),
                        created_at=str(sub.get("create_time", "")),
                        comment_type="reply",
                    ))

            if len(page_comments) < 10:
                break

            time.sleep(random.uniform(1.5, 3.0))
        except Exception as e:
            logger.debug(f"  小红书评论第{pn+1}页失败: {e}")
            break
        finally:
            try:
                page.remove_listener("response", on_response)
            except Exception:
                pass

    return comments


# ═══════════════════════════════════════════════════════════════════════════════
# 贴吧回复（打开帖子页 → DOM 提取）
# ═══════════════════════════════════════════════════════════════════════════════

def fetch_tieba_replies(page, thread_id: str, max_pages: int = 3) -> list[dict]:
    """打开贴吧帖子页，从 DOM 提取回复（使用已验证的旧版 Spider 选择器）。"""
    replies = []

    for pn in range(1, max_pages + 1):
        try:
            url = f"https://tieba.baidu.com/p/{thread_id}"
            if pn > 1:
                url += f"?pn={pn}"

            page.goto(url, wait_until="domcontentloaded", timeout=20000,
                      referer="https://tieba.baidu.com/index.html")

            # 等待帖子内容渲染
            try:
                page.wait_for_selector("div.l_post, div.d_post_content", timeout=10000)
            except Exception:
                pass
            time.sleep(2)

            # 使用已验证的 DOM 提取逻辑（来自 tieba_spider.py）
            raw = page.evaluate("""
            () => {
                var results = [];
                var posts = document.querySelectorAll('div.l_post');
                // 跳过第1个（主帖）
                for (var i = 1; i < posts.length; i++) {
                    var post = posts[i];
                    var content = '';
                    var contentEl = post.querySelector('.d_post_content, [class*=\"post_content\"]');
                    if (contentEl) content = contentEl.innerText.trim();
                    if (!content) continue;

                    var author = '';
                    var authorEl = post.querySelector('.d_author a, [class*=\"author\"]');
                    if (authorEl) author = authorEl.innerText.trim();

                    var floor = '';
                    var floorEl = post.querySelector('.tail-info');
                    if (floorEl) floor = floorEl.innerText.replace('楼', '').trim();

                    results.push({
                        author_username: author,
                        content: content.substring(0, 500),
                        floor: parseInt(floor) || 0,
                    });
                }
                return results;
            }
            """)

            for r in raw:
                replies.append(make_unified_comment(
                    author_username=r.get("author_username", ""),
                    content=r.get("content", ""),
                    comment_type="reply",
                ))

            if len(raw) < 20:
                break

            time.sleep(random.uniform(1.0, 2.0))
        except Exception as e:
            logger.debug(f"  贴吧回复第{pn}页失败: {e}")
            break

    return replies


# ═══════════════════════════════════════════════════════════════════════════════
# 抖音评论（打开视频页 → 截获评论 API）
# ═══════════════════════════════════════════════════════════════════════════════

def fetch_douyin_comments(page, aweme_id: str, max_pages: int = 3) -> list[dict]:
    """打开抖音视频页，通过响应拦截截获评论 API（自动带 X-Bogus 签名）。

    必须使用可见浏览器（headless=False），否则 hit_shark。
    参考: DrissionPage 浏览器自动化方案
    """
    comments = []

    for pn in range(max_pages):
        captured = []

        def on_response(response):
            if "/comment/list/" in response.url and f"aweme_id={aweme_id}" in response.url:
                try:
                    body = response.json()
                    if body.get("comments"):
                        captured.append(body)
                except Exception:
                    pass

        try:
            page.on("response", on_response)

            if pn == 0:
                url = f"https://www.douyin.com/video/{aweme_id}"
                page.goto(url, wait_until="domcontentloaded", timeout=20000,
                          referer="https://www.douyin.com/")
                time.sleep(4)
                # 滚动触发评论加载
                page.evaluate("window.scrollBy(0, 800)")
                time.sleep(3)
            else:
                # 翻页：滚动到底部
                page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                time.sleep(3)

            page.remove_listener("response", on_response)

            if not captured:
                break

            raw_comments = captured[0].get("comments", [])
            for c in raw_comments:
                user = c.get("user", {}) or {}
                comments.append(make_unified_comment(
                    id=str(c.get("cid", "")),
                    author_uid=str(user.get("uid", "")),
                    author_username=user.get("nickname", ""),
                    content=c.get("text", ""),
                    like_count=c.get("digg_count", 0),
                    created_at=str(c.get("create_time", "")),
                    comment_type="comment",
                ))
                # 回复的回复
                for r in c.get("reply_comment", []) or []:
                    ruser = r.get("user", {}) or {}
                    comments.append(make_unified_comment(
                        id=str(r.get("cid", "")),
                        author_uid=str(ruser.get("uid", "")),
                        author_username=ruser.get("nickname", ""),
                        content=r.get("text", ""),
                        like_count=r.get("digg_count", 0),
                        comment_type="reply",
                    ))

            if len(raw_comments) < 20:
                break

            time.sleep(random.uniform(1.5, 3.0))
        except Exception as e:
            logger.debug(f"  抖音评论第{pn+1}页失败: {e}")
            break
        finally:
            try:
                page.remove_listener("response", on_response)
            except Exception:
                pass

    return comments


# ═══════════════════════════════════════════════════════════════════════════════
# 批量采集入口
# ═══════════════════════════════════════════════════════════════════════════════

def enrich_comments(page, platform: str, items: list[dict],
                    max_comment_pages: int = 2, max_items: int = 30) -> list[dict]:
    """为采集结果批量添加评论。

    Args:
        page: Playwright page
        platform: 平台名
        items: 已采集的条目列表（需含 post_id / xsec_token）
        max_comment_pages: 每条帖子最多翻页数
        max_items: 最多为多少条帖子采集评论（控制耗时）
    """
    if platform not in ("xiaohongshu", "douyin", "tieba"):
        return items

    logger.info(f"[{platform}] 开始采集评论 (最多 {max_items} 条帖子)")

    enriched = 0
    for i, item in enumerate(items[:max_items]):
        post_id = item.get("post_id", "") or item.get("metadata", {}).get("aweme_id", "")
        if not post_id:
            continue

        try:
            if platform == "xiaohongshu":
                xsec = item.get("metadata", {}).get("xsec_token", "")
                comments = fetch_xiaohongshu_comments(page, post_id, xsec, max_comment_pages)
            elif platform == "douyin":
                comments = fetch_douyin_comments(page, post_id, max_comment_pages)
            elif platform == "tieba":
                comments = fetch_tieba_replies(page, post_id, max_comment_pages)
            else:
                continue

            if comments:
                item.setdefault("comments", []).extend(comments)
                item["comment_count"] = max(item.get("comment_count", 0), len(comments))
                enriched += 1

        except Exception as e:
            logger.debug(f"  [{platform}] 帖子 {post_id} 评论失败: {e}")

        time.sleep(random.uniform(0.5, 1.5))

    logger.info(f"[{platform}] 评论采集完成: {enriched}/{min(len(items), max_items)} 篇有评论")
    return items
