"""
往事可追忆 - 数据库模型 v3.0（按需求书 v2.4 重写）

=== 本次重构的根因（v2.4 第二节）===
旧模型：以「人」为数据主体（Story.user_id 指向一个人），权限越做越绕。
新模型：以「故事」为数据主体。一个人一生有很多故事，每段故事参与者都不同。

=== v2.4 已拍板事项在模型里的落点 ===
1. 数据主体 = 故事（不是人）          → Story + StoryParticipant
2. 一条故事 = 一个素材筐                → Clip（文字/语音/照片/视频/原声 统一挂)
3. 时间 vs 故事 两个维度独立            → Story.time_* 管排序；Story.group_id 管归属
4. 保留原声（不只是转文字）             → Clip.audio_url + Clip.transcript
5. 时间精度分级 年/季/月/模糊，不影响排序 → TimePrecision + Story.time_sort_key
6. 「待认领」机制                      → Claimable（手机号/名字登记 → 注册后自动认领）
7. 权限由入口决定，不设权限勾选框        → Member.granted_via + StoryPermission（单篇）
8. 高权限覆盖低权限；家人自动可见新增    → StoryPermission 判定逻辑
9. 双界面 标准版/大字版                → User.ui_mode
10. 收费后台化                        → Pricing（后台可配）
11. 先电子书 → 再实体书                → Ebook / PrintOrder
12. 打断/续添/活文档                   → Clip 可续挂，Story 无「定稿」硬锁
13. 归类原则：宁可分错，不可错并        → Story.group_id + ai_group_confidence

=== 铁律（v2.4 第十四节）===
- 静态核验 ≠ 通过；本文档【待后端复核】项未实测不得写成"已实现"
- 模糊时间表述原样保留：老人说"七几年" → 记「1970年代（老人说的）」
  绝不凑整成"1975年3月"
"""

from datetime import datetime
from sqlalchemy import (
    create_engine, Column, String, Text, Integer, Float, Boolean,
    DateTime, Date, Enum as SAEnum, JSON, ForeignKey, Index, UniqueConstraint
)
from sqlalchemy.orm import declarative_base, sessionmaker, relationship
import os
import enum

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./memory_story.db")
engine = create_engine(
    DATABASE_URL,
    connect_args={"check_same_thread": False} if "sqlite" in DATABASE_URL else {}
)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


# ============================================================
# 枚举
# ============================================================

class TimePrecision(str, enum.Enum):
    """时间精度分级（v2.4：年/季/月/模糊；精度不影响排序）"""
    YEAR = "year"           # 1979年
    SEASON = "season"       # 1979年春
    MONTH = "month"         # 1979年3月
    DAY = "day"             # 1979年3月5日
    FUZZY = "fuzzy"         # "七几年" / "文革那会儿" / "我八岁那年"
    UNKNOWN = "unknown"     # 时间待定（不瞎猜）


class ClipType(str, enum.Enum):
    """素材筐里的素材类型（v2.4：一个筐 = 文字/语音/照片/视频/原声）"""
    TEXT = "text"           # 文字
    AUDIO = "audio"         # 语音（保留原声 + 转写文字）
    PHOTO = "photo"         # 照片
    VIDEO = "video"         # 视频
    ORIGINAL = "original"   # 原声（仅存声音，不转写，用于保留方言/语气）


class GrantVia(str, enum.Enum):
    """
    权限来源（v2.4 铁律：权限由「从哪个入口加进来」决定）
      登录旁的加号 → 加家人 → 看整本书
      故事里的加号 → 加这个故事的人 → 只看这一篇
    """
    FAMILY = "family"           # 家人（全本）
    STORY = "story"             # 故事成员（单篇）
    PUBLIC_LINK = "public_link"  # 分享链进来的（看完再登录）


class ClaimStatus(str, enum.Enum):
    """待认领状态（v2.4：加人时对方可能还没账号）"""
    PENDING = "pending"         # 已登记，等对方注册
    CLAIMED = "claimed"         # 已认领（手机号匹配成功）
    BY_NAME = "by_name"         # 按名字搜索认领（写故事方已确认）
    REJECTED = "rejected"       # 拒绝


class UiMode(str, enum.Enum):
    """双界面（v2.4：同一程序，标准版/大字版）"""
    STANDARD = "standard"
    LARGE = "large"


class EbookStatus(str, enum.Enum):
    DRAFT = "draft"
    GENERATED = "generated"
    PAID = "paid"


# ============================================================
# 一、人（User）—— 注意：不是数据主体，只是账号
# ============================================================

class User(Base):
    """
    用户账号。**不是数据主体**（v2.1 重大修正：主体是故事）。
    这里只放登录态与展示态。
    """
    __tablename__ = "users"

    id = Column(String(128), primary_key=True)      # 微信 openid
    nick_name = Column(String(128), default="")
    avatar_url = Column(String(512), default="")
    phone = Column(String(32), index=True, default="")   # 手机号（认领钥匙）
    real_name = Column(String(64), index=True, default="")  # 真实姓名（按名字搜索认领用）
    ui_mode = Column(SAEnum(UiMode), default=UiMode.STANDARD)  # 双界面
    created_at = Column(DateTime, default=datetime.utcnow)
    last_login_at = Column(DateTime, default=datetime.utcnow)

    # 注：phone / real_name 已由 Column(index=True) 建索引，此处不重复声明


# ============================================================
# 二、故事（Story）—— 数据主体
# ============================================================

class Story(Base):
    """
    数据主体 = 一条故事（一件事）。
    素材（文字/语音/照片/视频）都挂在这一条上 —— 一个「素材筐」。

    === 两个维度独立（v2.4 第二节）===
    - 时间维度 = 排序维度  → time_* 字段 + time_sort_key
    - 故事维度 = 归属维度  → group_id（同组的算同一件事）
    - 同一时间点允许多个故事
    """
    __tablename__ = "stories"

    id = Column(String(64), primary_key=True)
    owner_id = Column(String(128), index=True, default="")  # 书的主人（讲述人）——权限判定的根
    title = Column(String(256), default="")            # 可为空，AI 后补
    summary = Column(Text, default="")                 # 一句话摘要（列表展示用）

    # ---- 归属维度 ----
    group_id = Column(String(64), index=True, nullable=True)   # 同一件事的分组
    ai_group_confidence = Column(Float, default=0.0)           # AI 判"是否同一件事"的置信度
    ai_group_source = Column(String(64), default="")           # 判定来源（rule / llm / manual）

    # ---- 时间维度（排序）----
    time_raw = Column(String(128), default="")          # **原样保留**用户/老人说法，如"七几年"
    time_start = Column(Date, nullable=True)            # 归一化起点（可空）
    time_end = Column(Date, nullable=True)              # 归一化终点（季节/模糊区间用）
    time_label = Column(String(128), default="")        # 展示用，如 "1970年代（老人说的）"
    time_precision = Column(SAEnum(TimePrecision), default=TimePrecision.UNKNOWN)
    time_sort_key = Column(Integer, default=0, index=True)   # 排序键；精度不影响排序
    time_extract_method = Column(String(32), default="")     # 显式年代 / 历史事件 / 人生锚点 / 待定
    time_confirmed_by_user = Column(Boolean, default=False)  # 用户是否手动改过（改过则不再自动覆盖）

    # ---- 内容 ----
    raw_content = Column(Text, default="")              # 原始自述/对话原文
    polished_content = Column(Text, default="")         # 润色后内容

    # ---- 参与者（v2.1：讲述人/记录者/参与者）----
    narrator_id = Column(String(128), index=True, nullable=True)   # 讲述人
    recorder_id = Column(String(128), index=True, nullable=True)   # 记录者
    people_mentioned = Column(JSON, default=list)       # 被提及的人 [{"name":..,"phone":..,"user_id":..}]

    location = Column(String(256), default="")
    tags = Column(JSON, default=list)
    emotion = Column(String(64), default="")

    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    clips = relationship("Clip", back_populates="story", cascade="all, delete-orphan")
    permissions = relationship("StoryPermission", back_populates="story", cascade="all, delete-orphan")

    __table_args__ = (
        Index("ix_stories_sort", "time_sort_key", "created_at"),
        # group_id / narrator_id 已由 Column(index=True) 建索引，此处不重复声明
    )


# ============================================================
# 三、素材（Clip）—— 一个筐里的各件素材
# ============================================================

class Clip(Base):
    """
    素材筐里的一件素材。
    铁律：**语音保留原声，不只是转文字**（v2.4）。
    """
    __tablename__ = "clips"

    id = Column(String(64), primary_key=True)
    story_id = Column(String(64), ForeignKey("stories.id", ondelete="CASCADE"), index=True)
    clip_type = Column(SAEnum(ClipType), default=ClipType.TEXT)

    # 文字
    text = Column(Text, default="")

    # 音频 / 视频 / 照片
    media_url = Column(String(512), default="")         # 原声/原片地址
    media_duration = Column(Float, default=0.0)         # 秒
    media_size = Column(Integer, default=0)             # 字节
    cover_url = Column(String(512), default="")         # 视频首帧 / 图片缩略

    # 转写（仅语音类；原声类可为空）
    transcript = Column(Text, default="")
    transcript_status = Column(String(32), default="pending")  # pending/processing/done/failed
    transcript_source = Column(String(32), default="")         # xfyun / baidu / whisper
    keep_original_voice = Column(Boolean, default=True)        # 是否保留原声（默认保留）

    caption = Column(String(512), default="")           # 照片说明
    sort_order = Column(Integer, default=0)
    created_by = Column(String(128), default="")        # 谁传的（老人自己/子女/故事里的人）
    created_at = Column(DateTime, default=datetime.utcnow)

    story = relationship("Story", back_populates="clips")

    __table_args__ = (
        Index("ix_clips_story", "story_id", "sort_order"),
    )


# ============================================================
# 四、权限（v2.4 铁律：由入口决定，不设勾选框）
# ============================================================

class Member(Base):
    """
    这本书的成员（家人 / 故事成员）。
    granted_via 决定能看多少：
      FAMILY → 整本书（全部故事 + 后续新增）
      STORY  → 只看被加进来的那一篇
    """
    __tablename__ = "members"

    id = Column(String(64), primary_key=True)
    owner_id = Column(String(128), index=True)          # 书的主人（讲述人）
    user_id = Column(String(128), index=True, nullable=True)   # 已认领则指向 User
    phone = Column(String(32), index=True, default="")  # 未认领时的认领钥匙
    display_name = Column(String(64), default="")       # 显示名（未注册也能显示）
    relation = Column(String(32), default="")           # 称呼：女儿/儿子/朋友
    granted_via = Column(SAEnum(GrantVia), default=GrantVia.STORY)
    claim_status = Column(SAEnum(ClaimStatus), default=ClaimStatus.PENDING)
    story_id = Column(String(64), nullable=True)        # granted_via=STORY 时，绑定的那一篇
    can_add = Column(Boolean, default=True)             # 能看就能补充（看与写同一权限）
    created_at = Column(DateTime, default=datetime.utcnow)
    claimed_at = Column(DateTime, nullable=True)

    # 注：owner_id / user_id / phone 已由 Column(index=True) 建索引


class StoryPermission(Base):
    """
    单篇级权限（细粒度）。
    说明：家人的「全本」权限不逐篇写在这张表里（靠 Member.granted_via 判定），
    这张表只记**例外**与**单篇授权**，避免行数爆炸。
    """
    __tablename__ = "story_permissions"

    id = Column(String(64), primary_key=True)
    story_id = Column(String(64), ForeignKey("stories.id", ondelete="CASCADE"), index=True)
    user_id = Column(String(128), index=True, nullable=True)
    phone = Column(String(32), index=True, default="")
    can_view = Column(Boolean, default=True)
    can_edit = Column(Boolean, default=False)
    granted_via = Column(SAEnum(GrantVia), default=GrantVia.STORY)
    created_at = Column(DateTime, default=datetime.utcnow)

    story = relationship("Story", back_populates="permissions")

    __table_args__ = (
        # 同一个人对同一篇只应有一条有效授权
        Index("ix_story_perm_unique", "story_id", "user_id", "phone"),
    )


# ============================================================
# 五、待认领（v2.4 新增，重要）
# ============================================================

class Claim(Base):
    """
    「待认领」机制。
    加人时对方可能还没账号 → 先按手机号/名字登记 → 对方注册后用同一手机号
    自动认领 → 首页出现「有 N 篇故事提到了你」。

    走两条路：
      ① 手机号匹配 → 自动认领
      ② 手机号对不上 → 按名字搜索认领（需写故事方确认）
    """
    __tablename__ = "claims"

    id = Column(String(64), primary_key=True)
    story_id = Column(String(64), ForeignKey("stories.id", ondelete="CASCADE"), index=True)
    owner_id = Column(String(128), index=True)          # 登记人（写故事的人）
    phone = Column(String(32), index=True, default="")
    display_name = Column(String(64), index=True, default="")
    match_type = Column(String(16), default="phone")    # phone / name
    status = Column(SAEnum(ClaimStatus), default=ClaimStatus.PENDING)
    claimed_user_id = Column(String(128), nullable=True)
    confirmed_by_owner = Column(Boolean, default=False)  # 按名字认领时须写故事方确认
    created_at = Column(DateTime, default=datetime.utcnow)
    claimed_at = Column(DateTime, nullable=True)

    __table_args__ = (
        Index("ix_claims_phone_status", "phone", "status"),
        Index("ix_claims_name_status", "display_name", "status"),
    )


# ============================================================
# 六、成书（先电子书 → 再实体书）
# ============================================================

class Ebook(Base):
    __tablename__ = "ebooks"

    id = Column(String(64), primary_key=True)
    owner_id = Column(String(128), index=True)
    title = Column(String(256), default="")
    content = Column(Text, default="")                  # 完整内容（含素材引用标记）
    style = Column(String(64), default="plain")
    pdf_url = Column(String(512), default="")
    status = Column(SAEnum(EbookStatus), default=EbookStatus.DRAFT)
    story_count = Column(Integer, default=0)
    generated_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)


class PrintOrder(Base):
    """实体书订单（sandy：印刷厂多家比价，现在不决定）"""
    __tablename__ = "print_orders"

    id = Column(String(64), primary_key=True)
    ebook_id = Column(String(64), index=True)
    owner_id = Column(String(128), index=True)
    book_spec = Column(String(64), default="")          # 开本/工艺
    copies = Column(Integer, default=1)
    price = Column(Float, default=0.0)
    vendor = Column(String(128), default="")
    status = Column(String(32), default="pending")
    created_at = Column(DateTime, default=datetime.utcnow)


# ============================================================
# 七、收费（后台配置化 —— sandy：收费规则后台配置，后续告知再补）
# ============================================================

class Pricing(Base):
    """价格配置。**不在代码里写死价格**，后台可改。"""
    __tablename__ = "pricing"

    id = Column(String(64), primary_key=True)
    plan_code = Column(String(32), index=True)          # free / single_book / yearly
    plan_name = Column(String(64), default="")
    price = Column(Float, default=0.0)
    period_days = Column(Integer, default=0)            # 0=一次性
    active = Column(Boolean, default=True)
    remark = Column(String(256), default="")
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class Order(Base):
    __tablename__ = "orders"

    id = Column(String(64), primary_key=True)
    user_id = Column(String(128), index=True)
    plan_code = Column(String(32), default="")
    amount = Column(Float, default=0.0)
    pay_channel = Column(String(32), default="wechat")  # 先微信支付，后加其他
    status = Column(String(32), default="pending")
    transaction_id = Column(String(128), default="")
    created_at = Column(DateTime, default=datetime.utcnow)
    paid_at = Column(DateTime, nullable=True)


# ============================================================
# 八、人生锚点（时间轴算法用：从锚点反推其他时间）
# ============================================================

class LifeAnchor(Base):
    """
    人生锚点（v2.4 时间轴算法）。
    一旦采到锚点（出生年/结婚年等），后续同类表述可自动换算。
    例："我八岁那年" + 锚点(出生年=1950) → 1958
    """
    __tablename__ = "life_anchors"

    id = Column(String(64), primary_key=True)
    owner_id = Column(String(128), index=True)          # 谁的锚点
    anchor_type = Column(String(32), default="")        # birth / marriage / work / move / child_birth
    anchor_name = Column(String(64), default="")        # 展示名，如"出生"
    year = Column(Integer, nullable=True)               # 锚点年份
    time_precision = Column(SAEnum(TimePrecision), default=TimePrecision.YEAR)
    source_story_id = Column(String(64), nullable=True) # 从哪条故事采到的
    confirmed = Column(Boolean, default=False)          # 用户确认过才可信
    created_at = Column(DateTime, default=datetime.utcnow)


# ============================================================
# 工具函数
# ============================================================

def init_db():
    """初始化数据库，创建所有表"""
    Base.metadata.create_all(bind=engine)


def get_db():
    """获取数据库会话（FastAPI 依赖注入用）"""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
