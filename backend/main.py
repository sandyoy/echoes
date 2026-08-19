"""
往日可追忆 - FastAPI 应用主入口
"""
import os
import uuid
from datetime import datetime
from fastapi import FastAPI, Depends, HTTPException, UploadFile, File, Form
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from sqlalchemy.orm import Session
from pydantic import BaseModel
from typing import Optional, List
from dotenv import load_dotenv

load_dotenv()

from models import init_db, get_db, Story, AudioClip, Event, Photo, Biography
from models import StoryStatus, TranscriptStatus, DatePrecision

app = FastAPI(title="往日可追忆 API", version="1.0.0")

# CORS 配置
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 静态文件目录（上传文件）
UPLOAD_DIR = os.getenv("UPLOAD_DIR", "./uploads")
os.makedirs(UPLOAD_DIR, exist_ok=True)
os.makedirs(os.path.join(UPLOAD_DIR, "audio"), exist_ok=True)
os.makedirs(os.path.join(UPLOAD_DIR, "photos"), exist_ok=True)

app.mount("/uploads", StaticFiles(directory=UPLOAD_DIR), name="uploads")


# === 启动事件 ===
@app.on_event("startup")
def startup():
    init_db()
    print("✅ 数据库初始化完成")


# === Pydantic 请求/响应模型 ===
class StoryCreate(BaseModel):
    title: str
    protagonist: str
    description: Optional[str] = ""

class StoryUpdate(BaseModel):
    title: Optional[str] = None
    protagonist: Optional[str] = None
    description: Optional[str] = None
    cover_image: Optional[str] = None
    status: Optional[str] = None

class EventCreate(BaseModel):
    story_id: str
    title: str
    content: str = ""
    raw_content: str = ""
    date: str = ""
    date_precision: str = "approximate"
    location: str = ""
    people: List[str] = []
    tags: List[str] = []
    emotion: str = ""

class EventUpdate(BaseModel):
    title: Optional[str] = None
    content: Optional[str] = None
    raw_content: Optional[str] = None
    date: Optional[str] = None
    date_precision: Optional[str] = None
    sort_order: Optional[int] = None
    location: Optional[str] = None
    people: Optional[List[str]] = None
    tags: Optional[List[str]] = None
    emotion: Optional[str] = None

class EventReorder(BaseModel):
    event_ids: List[str]  # 新的顺序

class PolishRequest(BaseModel):
    text: str
    style: str = "plain"  # plain, literary, emotional

class ExtractTimelineRequest(BaseModel):
    story_id: str


# === API 路由 ===

@app.get("/")
def root():
    return {"message": "往日可追忆 API v1.0", "status": "running"}


# --- 故事管理 ---
@app.post("/api/story")
def create_story(data: StoryCreate, db: Session = Depends(get_db)):
    story = Story(
        id=str(uuid.uuid4())[:8],
        user_id="default_user",  # TODO: 接入微信登录后替换
        title=data.title,
        protagonist=data.protagonist,
        description=data.description,
        status=StoryStatus.DRAFT
    )
    db.add(story)
    db.commit()
    db.refresh(story)
    return {"code": 0, "data": {"id": story.id, "title": story.title}}

@app.get("/api/story/list")
def list_stories(db: Session = Depends(get_db)):
    stories = db.query(Story).order_by(Story.updated_at.desc()).all()
    return {"code": 0, "data": [{
        "id": s.id,
        "title": s.title,
        "protagonist": s.protagonist,
        "cover_image": s.cover_image,
        "status": s.status.value if hasattr(s.status, 'value') else s.status,
        "event_count": db.query(Event).filter(Event.story_id == s.id).count(),
        "updated_at": s.updated_at.isoformat() if s.updated_at else None
    } for s in stories]}

@app.get("/api/story/{story_id}")
def get_story(story_id: str, db: Session = Depends(get_db)):
    story = db.query(Story).filter(Story.id == story_id).first()
    if not story:
        raise HTTPException(404, "故事不存在")
    events = db.query(Event).filter(Event.story_id == story_id).order_by(Event.sort_order).all()
    photos = db.query(Photo).filter(Photo.story_id == story_id).all()
    return {"code": 0, "data": {
        "story": {
            "id": story.id,
            "title": story.title,
            "protagonist": story.protagonist,
            "description": story.description,
            "cover_image": story.cover_image,
            "status": story.status.value if hasattr(story.status, 'value') else story.status
        },
        "events": [{
            "id": e.id,
            "title": e.title,
            "date": e.date,
            "content": e.content,
            "sort_order": e.sort_order,
            "people": e.people,
            "location": e.location,
            "emotion": e.emotion
        } for e in events],
        "photos": [{"id": p.id, "url": p.url, "caption": p.caption} for p in photos]
    }}

@app.put("/api/story/{story_id}")
def update_story(story_id: str, data: StoryUpdate, db: Session = Depends(get_db)):
    story = db.query(Story).filter(Story.id == story_id).first()
    if not story:
        raise HTTPException(404, "故事不存在")
    for key, val in data.dict(exclude_none=True).items():
        setattr(story, key, val)
    story.updated_at = datetime.utcnow()
    db.commit()
    return {"code": 0, "message": "更新成功"}


# --- 录音管理 ---
@app.post("/api/audio/upload")
async def upload_audio(
    story_id: str = Form(...),
    file: UploadFile = File(...),
    db: Session = Depends(get_db)
):
    ext = file.filename.split(".")[-1] if "." in file.filename else "wav"
    file_id = str(uuid.uuid4())[:8]
    save_path = os.path.join(UPLOAD_DIR, "audio", f"{file_id}.{ext}")
    
    content = await file.read()
    with open(save_path, "wb") as f:
        f.write(content)
    
    clip = AudioClip(
        id=file_id,
        story_id=story_id,
        audio_url=f"/uploads/audio/{file_id}.{ext}",
        duration=0,  # TODO: 从音频文件读取实际时长
        transcript_status=TranscriptStatus.PENDING
    )
    db.add(clip)
    db.commit()
    
    return {"code": 0, "data": {"id": clip.id, "url": clip.audio_url}}

@app.get("/api/audio/list/{story_id}")
def list_audio(story_id: str, db: Session = Depends(get_db)):
    clips = db.query(AudioClip).filter(AudioClip.story_id == story_id).all()
    return {"code": 0, "data": [{
        "id": c.id,
        "duration": c.duration,
        "transcript": c.transcript[:200] + "..." if c.transcript and len(c.transcript) > 200 else c.transcript,
        "transcript_status": c.transcript_status.value if hasattr(c.transcript_status, 'value') else c.transcript_status,
        "created_at": c.created_at.isoformat() if c.created_at else None
    } for c in clips]}


# --- 事件/时间线管理 ---
@app.post("/api/event/create")
def create_event(data: EventCreate, db: Session = Depends(get_db)):
    """手工创建事件"""
    event = Event(
        id=str(uuid.uuid4())[:8],
        story_id=data.story_id,
        title=data.title,
        content=data.content,
        raw_content=data.raw_content,
        date=data.date,
        date_precision=data.date_precision,
        sort_order=0,
        location=data.location,
        people=data.people,
        tags=data.tags,
        emotion=data.emotion
    )
    # 获取当前最大 sort_order
    max_order = db.query(Event.sort_order).filter(Event.story_id == data.story_id).order_by(Event.sort_order.desc()).first()
    if max_order and max_order[0] is not None:
        event.sort_order = max_order[0] + 1
    
    db.add(event)
    db.commit()
    db.refresh(event)
    return {"code": 0, "data": {"id": event.id, "title": event.title, "sort_order": event.sort_order}}

@app.post("/api/event/extract")
def extract_events(data: ExtractTimelineRequest, db: Session = Depends(get_db)):
    """
    AI 时间线提取接口（调用 DeepSeek）
    目前返回模拟数据，后续接入真实 AI
    """
    story = db.query(Story).filter(Story.id == data.story_id).first()
    if not story:
        raise HTTPException(404, "故事不存在")
    
    # 获取所有已完成的转录文本
    clips = db.query(AudioClip).filter(
        AudioClip.story_id == data.story_id,
        AudioClip.transcript_status == TranscriptStatus.DONE
    ).all()
    
    all_text = "\n".join([c.transcript for c in clips if c.transcript])
    
    if not all_text:
        raise HTTPException(400, "没有可用的转录文本，请先完成录音转文字")
    
    # TODO: 调用 DeepSeek API 提取时间线
    # 这里先返回模拟数据，演示数据结构
    mock_events = [
        {
            "title": "童年时光",
            "date": "约1965年",
            "date_precision": "approximate",
            "content": "在乡下度过的童年，家里有一个小院子，种着枣树。",
            "location": "湖南农村",
            "people": ["母亲", "奶奶"],
            "tags": ["童年", "家庭"],
            "emotion": "温馨"
        },
        {
            "title": "第一次进城",
            "date": "1983年",
            "date_precision": "year_only",
            "content": "18岁那年第一次去省城，坐了一整天的长途汽车。",
            "location": "长沙",
            "people": [],
            "tags": ["成长", "城市"],
            "emotion": "兴奋"
        }
    ]
    
    for idx, ev in enumerate(mock_events):
        event = Event(
            id=str(uuid.uuid4())[:8],
            story_id=data.story_id,
            title=ev["title"],
            content=ev["content"],
            date=ev["date"],
            date_precision=ev["date_precision"],
            sort_order=idx,
            location=ev.get("location", ""),
            people=ev.get("people", []),
            tags=ev.get("tags", []),
            emotion=ev.get("emotion", "")
        )
        db.add(event)
    
    story.status = StoryStatus.PROCESSING
    db.commit()
    
    return {"code": 0, "message": f"已提取 {len(mock_events)} 个事件", "data": mock_events}

@app.get("/api/event/list/{story_id}")
def list_events(story_id: str, db: Session = Depends(get_db)):
    events = db.query(Event).filter(Event.story_id == story_id).order_by(Event.sort_order).all()
    return {"code": 0, "data": [{
        "id": e.id,
        "title": e.title,
        "content": e.content,
        "date": e.date,
        "date_precision": e.date_precision.value if hasattr(e.date_precision, 'value') else e.date_precision,
        "sort_order": e.sort_order,
        "location": e.location,
        "people": e.people,
        "tags": e.tags,
        "emotion": e.emotion
    } for e in events]}

@app.put("/api/event/{event_id}")
def update_event(event_id: str, data: EventUpdate, db: Session = Depends(get_db)):
    event = db.query(Event).filter(Event.id == event_id).first()
    if not event:
        raise HTTPException(404, "事件不存在")
    for key, val in data.dict(exclude_none=True).items():
        setattr(event, key, val)
    db.commit()
    return {"code": 0, "message": "更新成功"}

@app.post("/api/event/reorder")
def reorder_events(data: EventReorder, db: Session = Depends(get_db)):
    for idx, eid in enumerate(data.event_ids):
        event = db.query(Event).filter(Event.id == eid).first()
        if event:
            event.sort_order = idx
    db.commit()
    return {"code": 0, "message": "排序已更新"}

@app.post("/api/event/{event_id}/delete")
def delete_event(event_id: str, db: Session = Depends(get_db)):
    event = db.query(Event).filter(Event.id == event_id).first()
    if event:
        db.delete(event)
        db.commit()
    return {"code": 0, "message": "已删除"}


# --- AI 能力 ---
@app.post("/api/ai/polish")
def polish_text(data: PolishRequest):
    """
    AI 润色文字
    TODO: 接入 DeepSeek API
    """
    text = data.text
    style = data.style
    
    # 模拟润色结果
    polished = text
    if style == "literary":
        polished = f"记忆深处，{text[:1]}{text[1:]}，如同一幅泛黄的老照片，静静诉说着岁月的故事。"
    elif style == "emotional":
        polished = f"每每想起{text[:1]}{text[1:]}，心中便涌起一阵暖流，那是再也回不去的时光。"
    
    return {"code": 0, "data": {"original": text, "polished": polished, "style": style}}


# --- 照片管理 ---
@app.post("/api/photo/upload")
async def upload_photo(
    story_id: str = Form(...),
    event_id: Optional[str] = Form(None),
    caption: Optional[str] = Form(""),
    file: UploadFile = File(...),
    db: Session = Depends(get_db)
):
    ext = file.filename.split(".")[-1] if "." in file.filename else "jpg"
    file_id = str(uuid.uuid4())[:8]
    save_path = os.path.join(UPLOAD_DIR, "photos", f"{file_id}.{ext}")
    
    content = await file.read()
    with open(save_path, "wb") as f:
        f.write(content)
    
    photo = Photo(
        id=file_id,
        story_id=story_id,
        event_id=event_id,
        url=f"/uploads/photos/{file_id}.{ext}",
        caption=caption
    )
    db.add(photo)
    db.commit()
    
    return {"code": 0, "data": {"id": photo.id, "url": photo.url}}


# --- 传记生成 ---
@app.post("/api/biography/generate/{story_id}")
def generate_biography(story_id: str, style: str = "plain", db: Session = Depends(get_db)):
    """
    基于事件和时间线，生成完整传记
    TODO: 接入 DeepSeek API
    """
    story = db.query(Story).filter(Story.id == story_id).first()
    if not story:
        raise HTTPException(404, "故事不存在")
    
    events = db.query(Event).filter(Event.story_id == story_id).order_by(Event.sort_order).all()
    photos = db.query(Photo).filter(Photo.story_id == story_id).all()
    
    # 模拟传记内容
    bio_content = f"# {story.title}\n\n"
    bio_content += f"## 主人公：{story.protagonist}\n\n"
    if story.description:
        bio_content += f"{story.description}\n\n"
    
    for e in events:
        bio_content += f"### {e.date} - {e.title}\n\n"
        bio_content += f"{e.content}\n\n"
        if e.location:
            bio_content += f"📍 {e.location}\n\n"
    
    bio = Biography(
        id=str(uuid.uuid4())[:8],
        story_id=story_id,
        title=story.title,
        content=bio_content,
        style=style,
        status="completed"
    )
    db.add(bio)
    story.status = StoryStatus.COMPLETED
    db.commit()
    
    return {"code": 0, "data": {"id": bio.id, "title": bio.title, "content": bio_content}}

@app.get("/api/biography/{bio_id}")
def get_biography(bio_id: str, db: Session = Depends(get_db)):
    bio = db.query(Biography).filter(Biography.id == bio_id).first()
    if not bio:
        raise HTTPException(404, "传记不存在")
    return {"code": 0, "data": {
        "id": bio.id,
        "title": bio.title,
        "content": bio.content,
        "style": bio.style,
        "status": bio.status,
        "created_at": bio.created_at.isoformat() if bio.created_at else None
    }}


# === 启动入口 ===
if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
