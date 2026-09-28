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
import collect_av as av
import claim_api

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


# --- 语音 / 原声 / 视频（2026-09-28，B 线后半，提前完成 09-29 任务）---

class AddAudioReq(BaseModel):
    story_id: str
    actor_id: str
    media_url: str
    file_name: str = ""
    file_size: int = 0
    mime: str = ""
    duration: float = 0.0
    caption: str = ""
    audio_path: str = ""      # 本机原声路径（可选）；传了才可能同步转写
    do_transcribe: bool = True


class AddOriginalReq(BaseModel):
    story_id: str
    actor_id: str
    media_url: str
    file_name: str = ""
    file_size: int = 0
    mime: str = ""
    duration: float = 0.0
    caption: str = ""


class AddVideoReq(BaseModel):
    story_id: str
    actor_id: str
    media_url: str
    file_name: str = ""
    file_size: int = 0
    mime: str = ""
    duration: float = 0.0
    cover_url: str = ""
    caption: str = ""


class TranscribeReq(BaseModel):
    clip_id: str
    actor_id: str
    audio_path: str = ""


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


# ============================================================
# 语音 / 原声 / 视频 路由（2026-09-28）
# 路径沿用既有口径：/api/echoes/clip/<类型>
# ============================================================

@app.post("/api/echoes/clip/audio")
def add_audio(req: AddAudioReq, db=Depends(get_db)):
    return av.api_add_audio_clip(
        db, story_id=req.story_id, owner_id=req.actor_id,   # TODO 登录态注入
        actor_id=req.actor_id, media_url=req.media_url,
        file_name=req.file_name, file_size=req.file_size, mime=req.mime,
        duration=req.duration, caption=req.caption,
        audio_path=req.audio_path, do_transcribe=req.do_transcribe,
    )


@app.post("/api/echoes/clip/original")
def add_original(req: AddOriginalReq, db=Depends(get_db)):
    return av.api_add_original_clip(
        db, story_id=req.story_id, owner_id=req.actor_id,   # TODO 登录态注入
        actor_id=req.actor_id, media_url=req.media_url,
        file_name=req.file_name, file_size=req.file_size, mime=req.mime,
        duration=req.duration, caption=req.caption,
    )


@app.post("/api/echoes/clip/video")
def add_video(req: AddVideoReq, db=Depends(get_db)):
    return av.api_add_video_clip(
        db, story_id=req.story_id, owner_id=req.actor_id,   # TODO 登录态注入
        actor_id=req.actor_id, media_url=req.media_url,
        file_name=req.file_name, file_size=req.file_size, mime=req.mime,
        duration=req.duration, cover_url=req.cover_url, caption=req.caption,
    )


@app.post("/api/echoes/clip/transcribe")
def transcribe_clip(req: TranscribeReq, db=Depends(get_db)):
    return av.api_transcribe_clip(
        db, clip_id=req.clip_id, owner_id=req.actor_id,     # TODO 登录态注入
        viewer_id=req.actor_id, audio_path=req.audio_path,
    )


# ============================================================
# 待认领 / 认领 路由（2026-09-27，第1期 A 线）
# ============================================================

class RegisterClaimReq(BaseModel):
    owner_id: str
    phone: str = ""
    display_name: str = ""
    story_id: str = ""


class ClaimLoginReq(BaseModel):
    user_id: str
    phone: str = ""


class ConfirmClaimReq(BaseModel):
    claim_id: str
    owner_id: str
    user_id: str


class RejectClaimReq(BaseModel):
    claim_id: str
    owner_id: str


@app.post("/api/echoes/claim/register")
def register_claim(req: RegisterClaimReq, db=Depends(get_db)):
    return claim_api.api_register_claim(
        db, owner_id=req.owner_id, phone=req.phone,
        display_name=req.display_name, story_id=req.story_id,
    )


@app.post("/api/echoes/claim/login")
def claim_on_login(req: ClaimLoginReq, db=Depends(get_db)):
    return claim_api.api_claim_on_login(db, user_id=req.user_id, phone=req.phone)


@app.get("/api/echoes/claim/mentioned")
def mentioned(user_id: str, db=Depends(get_db)):
    return claim_api.api_mentioned(db, user_id=user_id)


@app.get("/api/echoes/claim/search")
def search_claim(display_name: str, db=Depends(get_db)):
    return claim_api.api_search_claim_by_name(db, display_name=display_name)


@app.post("/api/echoes/claim/confirm")
def confirm_claim(req: ConfirmClaimReq, db=Depends(get_db)):
    return claim_api.api_confirm_claim(
        db, claim_id=req.claim_id, owner_id=req.owner_id, user_id=req.user_id,
    )


@app.post("/api/echoes/claim/reject")
def reject_claim(req: RejectClaimReq, db=Depends(get_db)):
    return claim_api.api_reject_claim(
        db, claim_id=req.claim_id, owner_id=req.owner_id,
    )


@app.get("/api/echoes/claim/pending")
def pending_claims(owner_id: str, db=Depends(get_db)):
    return claim_api.api_pending_claims(db, owner_id=owner_id)
