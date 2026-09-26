"""
往事可追忆 - FastAPI 框架适配器
把 `collect_api.py` 的纯 handler 挂成 HTTP 路由。

=== 重要：本文件在本机【跑不了】===
实测：这台服务器没有 fastapi / pydantic，系统 pip 被锁装不上（见 README_运行环境.md）。
所以本文件**没在本机实测过** —— 按 v2.4 铁律「静态核验 ≠ 通过」，
本文件标注为【未实测】，不得当成"接口已经能调"。

真正被测过的、能跑的是：`collect_api.py` + `selftest_collect_api.py`（34/34 过）。

=== 谁用、怎么用 ===
小龙虾（或任何有 fastapi 的机器）：
    pip install fastapi uvicorn
    uvicorn api_adapter_fastapi:app --host 0.0.0.0 --port 8000

业务逻辑一行不改 —— 改全在 collect_api.py 里，两端共用一个真源。
"""

try:
    from fastapi import FastAPI, Depends
    from pydantic import BaseModel
except ImportError as e:  # pragma: no cover
    raise ImportError(
        "本机没有 fastapi/pydantic，这是预期内的（见 README_运行环境.md）。"
        "请在能 pip install fastapi uvicorn 的机器上跑本适配器。"
    ) from e

from models import SessionLocal, get_db, init_db
import collect_api as api

app = FastAPI(title="往事可追忆 · 采集接口 v1")


# ============================================================
# 请求体
# ============================================================

class AddTextReq(BaseModel):
    story_id: str
    actor_id: str
    text: str
    caption: str = ""


class AddPhotoReq(BaseModel):
    story_id: str
    actor_id: str
    media_url: str
    file_name: str = ""
    file_size: int = 0
    mime: str = ""
    cover_url: str = ""
    caption: str = ""


class UploadUrlReq(BaseModel):
    file_name: str
    file_size: int
    mime: str = ""


# ============================================================
# 路由（owner_id 暂用同一个 actor_id 的会话态，实测接入登录后替换为鉴权中间件注入）
# ============================================================

@app.on_event("startup")
def _startup():
    init_db()


@app.post("/api/echoes/clip/text")
def add_text(req: AddTextReq, db=Depends(get_db)):
    return api.api_add_text_clip(
        db, story_id=req.story_id, owner_id=req.actor_id,   # TODO 登录态注入
        actor_id=req.actor_id, text=req.text, caption=req.caption,
    )


@app.post("/api/echoes/clip/photo")
def add_photo(req: AddPhotoReq, db=Depends(get_db)):
    return api.api_add_photo_clip(
        db, story_id=req.story_id, owner_id=req.actor_id,   # TODO 登录态注入
        actor_id=req.actor_id, media_url=req.media_url,
        file_name=req.file_name, file_size=req.file_size, mime=req.mime,
        cover_url=req.cover_url, caption=req.caption,
    )


@app.get("/api/echoes/clip/list")
def list_clips(story_id: str, viewer_id: str, db=Depends(get_db)):
    return api.api_list_clips(
        db, story_id=story_id, owner_id=viewer_id, viewer_id=viewer_id,  # TODO 登录态注入
    )


@app.post("/api/echoes/upload/url")
def upload_url(req: UploadUrlReq):
    return api.api_upload_url(
        file_name=req.file_name, file_size=req.file_size, mime=req.mime,
    )
