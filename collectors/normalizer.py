"""数据格式统一器 — 将各平台 ParsedItem 转换为统一的 IntelItem 格式。

所有渠道输出统一的字段结构，即使某些字段暂时为空（预留）。
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from collectors.base import IntelItem


# ═══════════════════════════════════════════════════════════════════════════════
# 统一的评论格式
# ═══════════════════════════════════════════════════════════════════════════════

def make_comment(
    id: str = "",
    author_uid: str = "",
    author_username: str = "",
    content: str = "",
    like_count: int = 0,
    reply_to: str = "",
    created_at: str = "",
    comment_type: str = "comment",
) -> dict:
    """创建统一评论格式。"""
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
# 平台归一化函数
# ═══════════════════════════════════════════════════════════════════════════════

def normalize_weibo(item: Any) -> IntelItem:
    """微博 ParsedWeiboAPIItem → IntelItem"""
    meta = getattr(item, "metadata", {}) or {}
    comments_raw = meta.get("comments", [])

    comments = []
    for c in comments_raw:
        comments.append(make_comment(
            id=str(c.get("id", "")),
            author_username=c.get("author", ""),
            content=c.get("text", ""),
            like_count=c.get("like_count", 0),
            created_at="",
            comment_type="comment",
        ))

    return IntelItem(
        platform="weibo",
        content_raw=getattr(item, "content_raw", ""),
        content_type=getattr(item, "content_type", "text"),
        source_url=getattr(item, "source_url", ""),
        author_uid=str(getattr(item, "author_uid", "")),
        author_username=getattr(item, "author_username", ""),
        post_id=str(getattr(item, "weibo_id", "")),
        like_count=getattr(item, "attitudes_count", 0),
        comment_count=getattr(item, "comments_count", 0),
        share_count=getattr(item, "reposts_count", 0),
        comments=comments,
        tags=[],
        image_urls=meta.get("image_urls", []),
        metadata={
            "weibo_id": getattr(item, "weibo_id", ""),
            "is_long_text": meta.get("is_long_text", False),
            "has_video": meta.get("has_video", False),
            "page_id": meta.get("page_id", ""),
        },
    )


def normalize_zhihu(item: Any) -> IntelItem:
    """知乎 ParsedZhihuAPIItem → IntelItem"""
    meta = getattr(item, "metadata", {}) or {}
    answers_raw = meta.get("answers", [])
    topics = list(getattr(item, "topics", []) or [])

    comments = []
    for a in answers_raw:
        # 答案作为 comment type=answer
        comments.append(make_comment(
            id=str(a.get("answer_id", "")),
            author_username=a.get("author_name", ""),
            content=a.get("content", ""),
            like_count=a.get("voteup_count", 0),
            created_at=a.get("created_time", ""),
            comment_type="answer",
        ))
        # 答案下的评论
        for ac in a.get("comments", []):
            comments.append(make_comment(
                id=str(ac.get("id", "")),
                author_username=ac.get("author", {}).get("name", "") if isinstance(ac.get("author"), dict) else "",
                content=ac.get("content", ""),
                like_count=ac.get("vote_count", 0),
                created_at=ac.get("created_time", ""),
                comment_type="comment",
            ))

    return IntelItem(
        platform="zhihu",
        content_raw=getattr(item, "content_raw", ""),
        content_type=getattr(item, "content_type", "text"),
        source_url=getattr(item, "source_url", ""),
        author_uid=str(getattr(item, "author_uid", "")),
        author_username=getattr(item, "author_username", ""),
        post_id=str(getattr(item, "answer_id", "") or getattr(item, "question_id", "")),
        like_count=getattr(item, "voteup_count", 0),
        comment_count=getattr(item, "comment_count", 0),
        comments=comments,
        tags=topics,
        image_urls=list(getattr(item, "image_list", []) or []),
        metadata={
            "question_id": getattr(item, "question_id", ""),
            "answer_id": getattr(item, "answer_id", ""),
            "voteup_count": getattr(item, "voteup_count", 0),
        },
    )


def normalize_tieba(item: Any) -> IntelItem:
    """贴吧 ParsedTiebaItem → IntelItem"""
    meta = getattr(item, "metadata", {}) or {}
    replies_raw = meta.get("replies", [])

    comments = []
    for r in replies_raw:
        comments.append(make_comment(
            id="",
            author_username=r.get("author_username", ""),
            author_uid=str(r.get("author_uid", "")),
            content=r.get("content", ""),
            like_count=0,
            created_at=str(r.get("reply_time", "")) if r.get("reply_time") else "",
            comment_type="reply",
        ))

    return IntelItem(
        platform="tieba",
        content_raw=getattr(item, "content_raw", ""),
        content_type=getattr(item, "content_type", "text"),
        source_url=getattr(item, "source_url", ""),
        author_uid=str(getattr(item, "author_uid", "")),
        author_username=getattr(item, "author_username", ""),
        post_id=str(getattr(item, "thread_id", "")),
        like_count=meta.get("like_num", 0),
        comment_count=getattr(item, "reply_count", 0),
        comments=comments,
        tags=[getattr(item, "bar_name", "")] if getattr(item, "bar_name", "") else [],
        image_urls=meta.get("image_urls", []),
        metadata={
            "thread_id": getattr(item, "thread_id", ""),
            "bar_name": getattr(item, "bar_name", ""),
            "forum_id": meta.get("forum_id", ""),
            "has_emoji": meta.get("has_emoji", False),
            "has_video": meta.get("has_video", False),
        },
    )


def normalize_xiaohongshu(item: Any) -> IntelItem:
    """小红书 ParsedXiaohongshuItem → IntelItem"""
    meta = getattr(item, "metadata", {}) or {}
    tags = list(getattr(item, "tags", []) or [])
    image_list = list(getattr(item, "image_list", []) or [])

    # 🆕 评论格式预留（当前无评论采集）
    # 结构: [{"id": "", "author_username": "", "content": "", "like_count": 0, ...}, ...]

    return IntelItem(
        platform="xiaohongshu",
        content_raw=getattr(item, "content_raw", ""),
        content_type=getattr(item, "content_type", "text"),
        source_url=getattr(item, "source_url", ""),
        author_uid=str(getattr(item, "author_uid", "")),
        author_username=getattr(item, "author_username", ""),
        post_id=str(getattr(item, "note_id", "")),
        like_count=getattr(item, "like_count", 0),
        comment_count=getattr(item, "comment_count", 0),
        collect_count=getattr(item, "collect_count", 0),
        comments=[],  # 预留：评论采集暂未实现
        tags=tags,
        image_urls=image_list,
        metadata={
            "note_id": getattr(item, "note_id", ""),
            "tags_original": tags,
            "interact_info": meta.get("interact_info", {}),
        },
    )


def normalize_douyin(item: Any) -> IntelItem:
    """抖音 ParsedDouyinItem → IntelItem"""
    meta = getattr(item, "metadata", {}) or {}
    hashtags = list(getattr(item, "hashtags", []) or [])
    image_list = list(getattr(item, "image_list", []) or [])

    # 🆕 评论格式预留（当前无评论采集）
    # 结构: [{"id": "", "author_username": "", "content": "", "like_count": 0, ...}, ...]

    return IntelItem(
        platform="douyin",
        content_raw=getattr(item, "content_raw", ""),
        content_type=getattr(item, "content_type", "text"),
        source_url=getattr(item, "source_url", ""),
        author_uid=str(getattr(item, "author_uid", "")),
        author_username=getattr(item, "author_username", ""),
        post_id=str(getattr(item, "aweme_id", "")),
        like_count=getattr(item, "like_count", 0),
        comment_count=getattr(item, "comment_count", 0),
        share_count=getattr(item, "share_count", 0),
        comments=[],  # 预留：评论采集暂未实现（需 msToken 签名）
        tags=hashtags,
        image_urls=image_list,
        video_cover_url=getattr(item, "video_cover_url", ""),
        metadata={
            "aweme_id": getattr(item, "aweme_id", ""),
            "play_count": getattr(item, "play_count", 0),
            "duration": getattr(item, "duration", 0),
            "hashtags_original": hashtags,
        },
    )


# ═══════════════════════════════════════════════════════════════════════════════
# 统一入口
# ═══════════════════════════════════════════════════════════════════════════════

NORMALIZERS = {
    "weibo": normalize_weibo,
    "zhihu": normalize_zhihu,
    "tieba": normalize_tieba,
    "xiaohongshu": normalize_xiaohongshu,
    "douyin": normalize_douyin,
}


def normalize(platform: str, item: Any) -> IntelItem:
    """将任意平台的 ParsedItem 转换为统一的 IntelItem 格式。"""
    if platform not in NORMALIZERS:
        raise ValueError(f"未知平台: {platform}，支持: {list(NORMALIZERS.keys())}")
    return NORMALIZERS[platform](item)


def normalize_items(platform: str, items: list) -> list[IntelItem]:
    """批量归一化。"""
    return [normalize(platform, item) for item in items]
