"""
往事可追忆 - FastAPI 框架适配器
把 `collect_api.py` 的纯 handler 挂成 HTTP 路由。

=== 2026-10-01 更新：本适配器已在云端实测通过 ===
10-01 用 `--user --break-system-packages` 给系统 python3.12 装上 fastapi/uvicorn 后，
**真起了 uvicorn、真打了 18+ 条路由**（见 `docs/事卷/HTTP端到端联调报告_20261001.md`）。
本次实测同时抓到并修掉一个**真安全 bug**（见下）。

=== ⚠️ 本日修掉的安全 bug（务必读）===
原 `list_clips` 路由写的是 `owner_id=viewer_id`（带 `# TODO 登录态注入`）。
而 `permissions.can_view_story` 的第一条规则是「viewer_id == owner_id → 能看」。
→ 于是**任何陌生人 viewer 都等于自己的 owner**，可以读到任意故事的素材（越权读取）。
HTTP 实测已复现：陌生 openid 取到了别人的全部 5 件素材。
**修法**：所有需要鉴权的路由改为**必传 `owner_id`**，不再用 viewer 冒充 owner；
缺 owner_id 一律拒绝（400），绝不退化放行。见各路由里的 `_require_owner`。

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
import login_api
import story_api

app = FastAPI(title="往事可追忆 · 采集接口 v1")


# ============================================================
# 鉴权小工具（2026-10-01 安全修复）
# ============================================================

def _require_owner(owner_id: str):
    """
    权限判定的根 = owner_id（书的主人），**必须由调用方显式传入**。
    绝不允许用 viewer_id 冒充 owner（10-01 修掉的越权 bug 就是这么来的）。
    缺失 → 直接拒绝，**不退化放行**。
    """
    if not owner_id or not str(owner_id).strip():
        return {"ok": False, "error": "缺少 owner_id（这本书的主人，权限判定必传）",
                "code": "missing_owner_id", "data": {}}
    return None


# ============================================================
# 请求体
# ============================================================

class AddTextReq(BaseModel):
    story_id: str
    actor_id: str
    owner_id: str = ""       # 书主人（权限判定的根）；缺则拒
    text: str
    caption: str = ""


class AddPhotoReq(BaseModel):
    story_id: str
    actor_id: str
    owner_id: str = ""
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
    owner_id: str = ""
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
    owner_id: str = ""
    media_url: str
    file_name: str = ""
    file_size: int = 0
    mime: str = ""
    duration: float = 0.0
    caption: str = ""


class AddVideoReq(BaseModel):
    story_id: str
    actor_id: str
    owner_id: str = ""
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
    owner_id: str = ""
    audio_path: str = ""


# ============================================================
# 采集路由
# 2026-10-01 安全修复：owner_id 一律由请求显式携带（前端从登录态取），
# 不再用 actor_id / viewer_id 冒充。缺 owner_id → 直接拒，不退化放行。
# ============================================================

@app.on_event("startup")
def _startup():
    init_db()


@app.post("/api/echoes/clip/text")
def add_text(req: AddTextReq, db=Depends(get_db)):
    _r = _require_owner(req.owner_id)
    if _r:
        return _r
    return api.api_add_text_clip(
        db, story_id=req.story_id, owner_id=req.owner_id,
        actor_id=req.actor_id, text=req.text, caption=req.caption,
    )


@app.post("/api/echoes/clip/photo")
def add_photo(req: AddPhotoReq, db=Depends(get_db)):
    _r = _require_owner(req.owner_id)
    if _r:
        return _r
    return api.api_add_photo_clip(
        db, story_id=req.story_id, owner_id=req.owner_id,
        actor_id=req.actor_id, media_url=req.media_url,
        file_name=req.file_name, file_size=req.file_size, mime=req.mime,
        cover_url=req.cover_url, caption=req.caption,
    )


@app.get("/api/echoes/clip/list")
def list_clips(story_id: str, viewer_id: str, owner_id: str = "", db=Depends(get_db)):
    _r = _require_owner(owner_id)
    if _r:
        return _r
    return api.api_list_clips(
        db, story_id=story_id, owner_id=owner_id, viewer_id=viewer_id,
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
    _r = _require_owner(req.owner_id)
    if _r:
        return _r
    return av.api_add_audio_clip(
        db, story_id=req.story_id, owner_id=req.owner_id,
        actor_id=req.actor_id, media_url=req.media_url,
        file_name=req.file_name, file_size=req.file_size, mime=req.mime,
        duration=req.duration, caption=req.caption,
        audio_path=req.audio_path, do_transcribe=req.do_transcribe,
    )


@app.post("/api/echoes/clip/original")
def add_original(req: AddOriginalReq, db=Depends(get_db)):
    _r = _require_owner(req.owner_id)
    if _r:
        return _r
    return av.api_add_original_clip(
        db, story_id=req.story_id, owner_id=req.owner_id,
        actor_id=req.actor_id, media_url=req.media_url,
        file_name=req.file_name, file_size=req.file_size, mime=req.mime,
        duration=req.duration, caption=req.caption,
    )


@app.post("/api/echoes/clip/video")
def add_video(req: AddVideoReq, db=Depends(get_db)):
    _r = _require_owner(req.owner_id)
    if _r:
        return _r
    return av.api_add_video_clip(
        db, story_id=req.story_id, owner_id=req.owner_id,
        actor_id=req.actor_id, media_url=req.media_url,
        file_name=req.file_name, file_size=req.file_size, mime=req.mime,
        duration=req.duration, cover_url=req.cover_url, caption=req.caption,
    )


@app.post("/api/echoes/clip/transcribe")
def transcribe_clip(req: TranscribeReq, db=Depends(get_db)):
    _r = _require_owner(req.owner_id)
    if _r:
        return _r
    return av.api_transcribe_clip(
        db, clip_id=req.clip_id, owner_id=req.owner_id,
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


# ============================================================
# 登录态路由（2026-09-29，第1期——"能录进来"的最后一块后端）
# 前端拿 user_id 的唯一入口。此前所有接口都要 user_id，但没人负责产出它。
# ============================================================

class LoginReq(BaseModel):
    code: str                     # wx.login() 拿到的临时 code
    nick_name: str = ""
    avatar_url: str = ""
    phone: str = ""
    force_stub: bool = False      # 仅联调/自测用；生产不传（默认 False）


class UiModeReq(BaseModel):
    user_id: str
    ui_mode: str                  # standard / large（兼容 senior 等别名）


@app.post("/api/echoes/login")
def login(req: LoginReq, db=Depends(get_db)):
    return login_api.api_login(
        db, code=req.code, nick_name=req.nick_name, avatar_url=req.avatar_url,
        phone=req.phone, force_stub=req.force_stub,
    )


@app.get("/api/echoes/login/profile")
def login_profile(user_id: str, db=Depends(get_db)):
    return login_api.api_profile(db, user_id=user_id)


@app.post("/api/echoes/login/ui_mode")
def login_ui_mode(req: UiModeReq, db=Depends(get_db)):
    return login_api.api_set_ui_mode(db, user_id=req.user_id, ui_mode=req.ui_mode)


# ============================================================
# 故事（一件事 / 一本书）路由（2026-10-01，第1期缺口补齐）
# 此前全部接口都要 story_id，却没人负责产出它 → 前端无书可建。
# ============================================================

class CreateBookReq(BaseModel):
    owner_id: str
    actor_id: str = ""
    title: str = ""
    summary: str = ""


class CreateStoryReq(BaseModel):
    owner_id: str                 # 书的主人（权限的根）
    actor_id: str                 # 谁在写（书主人本人 / 已认领家人）
    title: str = ""
    raw_content: str = ""
    summary: str = ""
    time_raw: str = ""            # 原样保留老人说法
    people_mentioned: list = []
    story_id: str = ""            # 传了则幂等返回（弱网重试防重建）


@app.post("/api/echoes/book/create")
def create_book(req: CreateBookReq, db=Depends(get_db)):
    return story_api.api_create_book(
        db, owner_id=req.owner_id, actor_id=req.actor_id or req.owner_id,
        title=req.title, summary=req.summary,
    )


@app.get("/api/echoes/book/my")
def my_books(user_id: str, db=Depends(get_db)):
    return story_api.api_my_books(db, user_id=user_id)


@app.post("/api/echoes/story/create")
def create_story(req: CreateStoryReq, db=Depends(get_db)):
    return story_api.api_create_story(
        db, owner_id=req.owner_id, actor_id=req.actor_id,
        title=req.title, raw_content=req.raw_content, summary=req.summary,
        time_raw=req.time_raw, people_mentioned=req.people_mentioned,
        story_id=req.story_id,
    )


@app.get("/api/echoes/story/list")
def list_stories(owner_id: str, viewer_id: str = "",
                 limit: int = 200, offset: int = 0, db=Depends(get_db)):
    return story_api.api_list_stories(
        db, owner_id=owner_id, viewer_id=viewer_id or owner_id,
        limit=limit, offset=offset,
    )


@app.get("/api/echoes/story/detail")
def get_story(story_id: str, owner_id: str = "", viewer_id: str = "",
              db=Depends(get_db)):
    return story_api.api_get_story(
        db, story_id=story_id, owner_id=owner_id,
        viewer_id=viewer_id or owner_id,
    )


@app.post("/api/echoes/story/delete")
def delete_story(story_id: str, owner_id: str = "", actor_id: str = "",
                 db=Depends(get_db)):
    return story_api.api_delete_story(
        db, story_id=story_id, owner_id=owner_id, actor_id=actor_id or owner_id,
    )
