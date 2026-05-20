"""
往日可追忆 - 数据库模型
"""
from datetime import datetime
from sqlalchemy import create_engine, Column, String, Text, Integer, Float, DateTime, Enum as SAEnum, JSON
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
import os
import enum

# 数据库连接
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./memory_story.db")
engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False} if "sqlite" in DATABASE_URL else {})
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


# === 枚举类型 ===
class StoryStatus(str, enum.Enum):
    DRAFT = "draft"                 # 草稿
    RECORDING = "recording"         # 录音中
    PROCESSING = "processing"       # AI 处理中
    COMPLETED = "completed"         # 已完成

class TranscriptStatus(str, enum.Enum):
    PENDING = "pending"
    PROCESSING = "processing"
    DONE = "done"
    FAILED = "failed"

class DatePrecision(str, enum.Enum):
    EXACT = "exact"                 # 精确日期
    YEAR_MONTH = "year_month"       # 年月
    YEAR_ONLY = "year_only"         # 仅年份
    APPROXIMATE = "approximate"     # 大约


# === 数据表模型 ===
class User(Base):
    __tablename__ = "users"
    
    id = Column(String(128), primary_key=True)  # 微信 openid
    nick_name = Column(String(128))
    avatar_url = Column(String(512))
    created_at = Column(DateTime, default=datetime.utcnow)


class Story(Base):
    __tablename__ = "stories"
    
    id = Column(String(64), primary_key=True)
    user_id = Column(String(128), index=True)
    title = Column(String(256))
    protagonist = Column(String(128))       # 主人公
    cover_image = Column(String(512))
    description = Column(Text)
    status = Column(SAEnum(StoryStatus), default=StoryStatus.DRAFT)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class AudioClip(Base):
    __tablename__ = "audio_clips"
    
    id = Column(String(64), primary_key=True)
    story_id = Column(String(64), index=True)
    duration = Column(Float)                # 秒
    audio_url = Column(String(512))
    transcript = Column(Text, default="")
    transcript_status = Column(SAEnum(TranscriptStatus), default=TranscriptStatus.PENDING)
    created_at = Column(DateTime, default=datetime.utcnow)


class Event(Base):
    __tablename__ = "events"
    
    id = Column(String(64), primary_key=True)
    story_id = Column(String(64), index=True)
    title = Column(String(256))
    content = Column(Text)                  # 润色后内容
    raw_content = Column(Text)              # 原始对话原文
    date = Column(String(64))               # 如 "1985-03" 或 "约1980年"
    date_precision = Column(SAEnum(DatePrecision), default=DatePrecision.APPROXIMATE)
    sort_order = Column(Integer, default=0)
    location = Column(String(256), default="")
    people = Column(JSON, default=list)     # ["父亲", "张三"]
    tags = Column(JSON, default=list)
    emotion = Column(String(64), default="")
    created_at = Column(DateTime, default=datetime.utcnow)


class Photo(Base):
    __tablename__ = "photos"
    
    id = Column(String(64), primary_key=True)
    story_id = Column(String(64), index=True)
    event_id = Column(String(64), index=True, nullable=True)
    url = Column(String(512))
    caption = Column(String(512), default="")
    people_tagged = Column(JSON, default=list)
    created_at = Column(DateTime, default=datetime.utcnow)


class Biography(Base):
    __tablename__ = "biographies"
    
    id = Column(String(64), primary_key=True)
    story_id = Column(String(64), index=True)
    title = Column(String(256))
    content = Column(Text)                  # 完整传记内容（含图片引用标记）
    style = Column(String(64), default="plain")
    pdf_url = Column(String(512))
    status = Column(String(32), default="draft")
    created_at = Column(DateTime, default=datetime.utcnow)


# === 工具函数 ===
def init_db():
    """初始化数据库，创建所有表"""
    Base.metadata.create_all(bind=engine)

def get_db():
    """获取数据库会话（用于 FastAPI 依赖注入）"""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
