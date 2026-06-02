"""Project-level constants, schemas, and shared utilities."""

from enum import Enum
from typing import Optional
from datetime import datetime
from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

class Platform(str, Enum):
    TELEGRAM = "telegram"
    TIEBA = "tieba"
    WEIBO = "weibo"
    ZHIHU = "zhihu"
    XIAOHONGSHU = "xiaohongshu"
    DOUYIN = "douyin"
    FORUM = "forum"
    RSS = "rss"
    OTHER = "other"


class ContentType(str, Enum):
    TEXT = "text"
    IMAGE = "image"
    GIF = "gif"
    VIDEO = "video"
    AUDIO = "audio"


class Priority(str, Enum):
    NORMAL = "normal"
    HIGH = "high"
    CRITICAL = "critical"


class IntelStatus(str, Enum):
    PENDING = "pending"
    CLEANED = "cleaned"
    ANALYZED = "analyzed"
    DISCARDED = "discarded"


class RawIntelStatus(str, Enum):
    RAW_COLLECTED = "RAW_COLLECTED"
    CLEANED = "CLEANED"
    ANALYZING = "ANALYZING"
    ANALYZED = "ANALYZED"
    FAILED = "FAILED"
    DISCARDED = "DISCARDED"


RAW_PENDING_STATUSES = (
    RawIntelStatus.RAW_COLLECTED.value,
    RawIntelStatus.CLEANED.value,
)


RAW_TERMINAL_STATUSES = (
    RawIntelStatus.ANALYZED.value,
    RawIntelStatus.FAILED.value,
    RawIntelStatus.DISCARDED.value,
)


class IntentLabel(str, Enum):
    FRAUD = "诈骗"
    TRAFFIC_DRIVEN = "引流"
    CHEATING = "作弊"
    ACCOUNT_BLACK = "账号黑产"
    CONTENT_VIOLATION = "内容违规"
    TOOL_TRADE = "工具交易"
    LIVE_VIOLATION = "直播违规"


SUBLABEL_MAP = {
    IntentLabel.FRAUD: ["电信诈骗", "金融诈骗", "虚假中奖"],
    IntentLabel.TRAFFIC_DRIVEN: ["色情引流", "赌博引流", "诈骗引流", "站外导流"],
    IntentLabel.CHEATING: ["刷量刷单", "营销套利", "游戏外挂"],
    IntentLabel.ACCOUNT_BLACK: ["批量注册/养号", "撞库盗号", "账号买卖"],
    IntentLabel.CONTENT_VIOLATION: ["色情低俗", "违法信息", "谣言"],
    IntentLabel.TOOL_TRADE: ["黑卡/接码", "脚本/外挂", "数据买卖"],
    IntentLabel.LIVE_VIOLATION: ["数字人欺诈", "无人直播", "赌博直播"],
}


class EntityType(str, Enum):
    PHONE = "phone"
    WECHAT = "wechat"
    QQ = "qq"
    TELEGRAM = "telegram"
    EMAIL = "email"
    URL = "url"
    DOMAIN = "domain"
    IP = "ip"
    BANK_CARD = "bank_card"
    ALIPAY = "alipay"
    SLANG = "slang"
    TOOL = "tool"
    CRYPTO_WALLET = "crypto_wallet"
    FEATURE = "feature"


class ExtractionMethod(str, Enum):
    REGEX = "regex"
    DICT = "dict"
    EMBEDDING = "embedding"
    LLM = "llm"


class ClassificationMethod(str, Enum):
    KEYWORD = "keyword"
    ROBERTA = "roberta"
    LLM = "llm"


# ---------------------------------------------------------------------------
# Domain Models
# ---------------------------------------------------------------------------

class RawIntel(BaseModel):
    """Single raw intelligence item collected from a source."""
    id: Optional[int] = None
    source_platform: Platform
    source_url: Optional[str] = None
    author_uid: Optional[str] = None
    author_username: Optional[str] = None
    content_type: ContentType = ContentType.TEXT
    content_raw: str
    content: str = ""  # filled after cleaning
    image_hash: Optional[str] = None
    simhash: Optional[str] = None
    priority: Priority = Priority.NORMAL
    status: IntelStatus = IntelStatus.PENDING
    collected_at: datetime = Field(default_factory=datetime.utcnow)
    group_id: Optional[str] = None
    message_id: Optional[int] = None
    metadata: dict = Field(default_factory=dict)


class ClassificationResult(BaseModel):
    raw_data_id: int
    intent_label: IntentLabel
    sub_label: str
    confidence: float
    method: ClassificationMethod


class ExtractedEntity(BaseModel):
    raw_data_id: int
    entity_type: EntityType
    entity_value: str
    extraction_method: ExtractionMethod
    context: Optional[str] = None  # surrounding text
    metadata: dict = Field(default_factory=dict)


class SlangEntry(BaseModel):
    slang: str
    normalized_meaning: str
    category: Optional[str] = None
    source: str = "manual"  # threathunter / manual / llm / embedding
    status: str = "active"  # active / candidate / deprecated


class CheatScript(BaseModel):
    title: str
    risk_type: str
    abuse_chain: str
    tools_used: list[str] = Field(default_factory=list)
    related_entities: list[dict] = Field(default_factory=list)
    defense_suggestions: list[str] = Field(default_factory=list)
    related_intel_ids: list[int] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# High-risk keywords for priority marking
# ---------------------------------------------------------------------------

HIGH_RISK_KEYWORDS = [
    "刷单", "诈骗", "接码", "出号", "出抖号", "日结", "套现", "洗钱",
    "博彩", "赌博", "色情", "裸聊", "招嫖", "枪支", "毒品",
    "假币", "伪基站", "撞库", "盗号", "猫池", "卡商",
    "代理IP", "VPN翻墙", "暗网", "数据买卖", "隐私泄露",
    "薅羊毛", "批量注册", "群控", "云手机", "模拟器",
    "代收", "代付", "跑分", "四件套", "八件套",
]
