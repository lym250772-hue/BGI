"""采集器基础模块 — 统一的 IntelItem 数据格式 + BaseCollector 抽象基类。

设计原则：
  - 所有平台的采集器都产出统一格式的 IntelItem
  - BaseCollector 定义 collect() → Iterator[IntelItem] 接口
  - 新增平台只需继承 BaseCollector 并实现 collect()
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from typing import Iterator, Optional

BJT = timezone(timedelta(hours=8))


def now_bjt() -> datetime:
    """返回北京时间（UTC+8），去除时区信息以兼容数据库。"""
    return datetime.now(BJT).replace(tzinfo=None)


@dataclass
class IntelItem:
    """统一的情报数据条目 — 所有采集器的标准输出格式。

    对应 ods_raw_intel 表结构（PROJECT_PLAN.md Step 1），
    是采集层与分析层的接口契约。
    """

    # ── 核心字段 ──
    platform: str           # 来源平台: weibo / tieba / zhihu / xiaohongshu / douyin / xianyu / qq_group
    content_raw: str        # 原始正文（保留原文，不去除任何内容）
    content_type: str = "text"  # text / image / video / audio
    source_url: str = ""    # 原文链接

    # ── 作者信息 ──
    author_uid: str = ""        # 作者 UID
    author_username: str = ""   # 作者昵称

    # ── 分组/频道 ──
    group_id: str = ""          # 贴吧名 / TG群组 / 关键词 等分组标识

    # ── 时间 ──
    collected_at: datetime = field(default_factory=now_bjt)

    # ── 消息标识 ──
    message_id: Optional[int] = None    # 平台消息/帖子 ID
    post_id: str = ""                   # 🆕 统一帖子ID（映射 weibo_id/thread_id/note_id/aweme_id）

    # ── 互动指标（统一，各平台映射） ──
    like_count: int = 0     # 点赞数
    comment_count: int = 0  # 评论/回复数
    share_count: int = 0    # 转发/分享数
    collect_count: int = 0  # 收藏数（小红书等）

    # ── 统一互动内容 🆕 ──
    comments: list[dict] = field(default_factory=list)
    """统一评论/回复/答案格式:
    {
        "id": str,              # 评论ID
        "author_uid": str,      # 作者ID
        "author_username": str, # 作者昵称
        "content": str,         # 评论内容
        "like_count": int,      # 评论点赞数
        "reply_to": str,        # 回复对象（用户名或评论ID）
        "created_at": str,      # ISO时间
        "type": str,            # "comment" | "reply" | "answer"
    }
    小红书/抖音: 暂无评论采集，字段预留供后续接入
    """

    # ── 标签 🆕 ──
    tags: list[str] = field(default_factory=list)
    """统一标签/话题/hashtag（各平台映射）"""

    # ── 扩展 ──
    metadata: dict = field(default_factory=dict)
    """平台特定元数据，如:
    weibo:  {weibo_id, has_video, is_long_text}
    tieba:  {thread_id, bar_name, has_emoji, forum_id}
    zhihu:  {question_id, answer_id, voteup_count}
    douyin: {aweme_id, hashtags, play_count, duration}
    xiaohongshu: {note_id, tags_original}
    """

    # ── 市场平台扩展字段（闲鱼等二手/众包平台）──
    price: float = 0.0
    """商品/服务价格（CNY），仅二手/众包平台使用"""
    seller_rating: str = ""
    """卖家信用评级（如芝麻信用），仅市场平台使用"""
    location: str = ""
    """卖家所在地/IP属地"""
    listing_status: str = ""
    """商品状态: active(在售) / sold(已售) / deleted(已删除)"""

    # ── 媒体 ──
    image_urls: list[str] = field(default_factory=list)
    """图片链接列表（小红书图集、抖音封面等）"""
    video_cover_url: str = ""
    """视频封面链接（抖音等）"""


@dataclass
class IMMessageItem:
    """即时通讯消息条目 — QQ群聊/微信群的统一消息格式。

    用于社交IM平台的消息采集，与 IntelItem（用于内容平台帖子/评论）互补。
    通过 im_to_intel() 转换器可合并到统一存储流水线。
    """
    platform: str = "qq_group"
    group_id: str = ""          # 群号
    group_name: str = ""        # 群名称
    sender_uid: str = ""        # 发送者QQ号
    sender_nickname: str = ""   # 发送者昵称
    content_raw: str = ""       # 消息内容
    content_type: str = "text"  # text / image / file / video
    message_id: str = ""        # 消息ID (msgSeq)
    reply_to_id: str = ""       # 回复消息ID
    collected_at: datetime = field(default_factory=now_bjt)
    image_urls: list[str] = field(default_factory=list)
    images: list[dict] = field(default_factory=list)
    """图片/动图/表情包: [{"type": "image/mface/face", "url": "..."}]"""
    metadata: dict = field(default_factory=dict)


class BaseCollector(ABC):
    """采集器抽象基类。

    子类需要实现 collect()，返回 Iterator[IntelItem]。
    每个 platform 对应一个 Collector 子类。
    """

    @abstractmethod
    def collect(self) -> Iterator[IntelItem]:
        """执行采集，逐条产出 IntelItem。

        Yields:
            IntelItem: 统一格式的情报条目
        """
        ...
