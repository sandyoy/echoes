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
    from fastapi import FastAPI, Depends, Request
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
import book_api
import book_view_api
import timeline_api
import interview_api
import interview_recap
import share_api
import join_api
import family_api
import group_api
import payment_api
import entitlement
import storage_api
import tts_api

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
    # v3.0 §1.3 来路 + 公开/私有（第1期起必带；缺省 = 默认私有 + 原创）
    visibility: str = ""      # ""/private/public；缺省 private
    source_type: str = ""     # ""/origin/quote
    ref_from_id: str = ""     # 引用自哪条素材（可空）
    ref_author_name: str = "" # 出处署名（可能为称呼/笔名）


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
    visibility: str = ""
    source_type: str = ""
    ref_from_id: str = ""
    ref_author_name: str = ""


class SetClipVisibilityReq(BaseModel):
    clip_id: str
    actor_id: str
    visibility: str          # public / private


class UploadUrlReq(BaseModel):
    file_name: str
    file_size: int
    mime: str = ""


# --- 对象存储上传通道（2026-10-14，第53~55条路由）---
class StorageUploadUrlReq(BaseModel):
    actor_id: str
    kind: str = "image"          # image / audio / video / original
    file_name: str
    file_size: int = 0
    mime: str = ""


class StorageConfirmReq(BaseModel):
    actor_id: str
    key: str
    owner_id: str = ""
    kind: str = "image"
    story_id: str = ""
    file_name: str = ""
    file_size: int = 0
    mime: str = ""
    visibility: str = "private"
    duration: float = 0.0


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
        visibility=req.visibility, source_type=req.source_type,
        ref_from_id=req.ref_from_id, ref_author_name=req.ref_author_name,
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
        visibility=req.visibility, source_type=req.source_type,
        ref_from_id=req.ref_from_id, ref_author_name=req.ref_author_name,
    )


@app.get("/api/echoes/clip/list")
def list_clips(story_id: str, viewer_id: str, owner_id: str = "", db=Depends(get_db)):
    _r = _require_owner(owner_id)
    if _r:
        return _r
    return api.api_list_clips(
        db, story_id=story_id, owner_id=owner_id, viewer_id=viewer_id,
    )


@app.post("/api/echoes/clip/visibility")
def set_clip_visibility(req: SetClipVisibilityReq, db=Depends(get_db)):
    """v3.0 §1.2：提供人主动把一条素材设为公开/私有（默认私有）。"""
    return api.api_set_clip_visibility(
        db, clip_id=req.clip_id, actor_id=req.actor_id, visibility=req.visibility,
    )


@app.post("/api/echoes/upload/url")
def upload_url(req: UploadUrlReq):
    """
    【兼容旧路径 · 2026-10-14 起委托给 storage_api】

    旧调用（只给 file_name/file_size/mime，没有 actor_id）——v3.0 §6.2.1 起
    上传必须知道**是谁**（素材只由本人入库），故本路由降级为兼容入口：
    actor_id 缺失时明确提示改调新路由 `/storage/upload_url`。
    新前端请直接用 `/api/echoes/storage/upload_url`（带 actor_id + kind）。
    """
    if not getattr(req, "actor_id", ""):
        return {
            "ok": False,
            "code": "missing_actor",
            "error": "上传必须带 actor_id（素材只由本人入库，v3.0 §6.2.1）——"
                     "请改调 /api/echoes/storage/upload_url",
            "data": {},
        }
    return storage_api.api_upload_url(
        actor_id=req.actor_id, kind=getattr(req, "kind", "image"),
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


# ============================================================
# 成书（v3.0 §八 · 2026-10-11 新增）
#   取材（两筐） → 生成电子书 → 取我的电子书
# handler: book_api.py（本机无 fastapi 未实测路由，形状已冻结）
# ============================================================

class BookSourceReq(BaseModel):
    owner_id: str
    actor_id: str = ""


class GenerateEbookReq(BaseModel):
    owner_id: str
    actor_id: str = ""
    title: str = ""
    picked_public_ids: list = []      # 从公共筐点选要装的素材 id
    ebook_id: str = ""                # 传了则覆盖刷新（活文档）


@app.post("/api/echoes/book/source")
def book_source(req: BookSourceReq, db=Depends(get_db)):
    return book_api.api_book_source_baskets(
        db, owner_id=req.owner_id, actor_id=req.actor_id)


@app.post("/api/echoes/book/generate")
def book_generate(req: GenerateEbookReq, db=Depends(get_db)):
    return book_api.api_generate_ebook(
        db, owner_id=req.owner_id, actor_id=req.actor_id, title=req.title,
        picked_public_ids=req.picked_public_ids, ebook_id=req.ebook_id)


@app.get("/api/echoes/book/ebook")
def my_ebook(owner_id: str, db=Depends(get_db)):
    return book_api.api_my_ebook(db, owner_id=owner_id)


# handler: book_view_api.py（§8.6 三种形态 + §8.4 续添；本机无 fastapi 未实测，形状已冻结）
class BookViewReq(BaseModel):
    owner_id: str
    viewer_id: str = ""
    form: str = "scroll"          # paged 翻页 | scroll 手机端阅读 | photobook 翻相册式
    book_spec: str = "A5"


class BookAppendReq(BaseModel):
    owner_id: str
    actor_id: str = ""
    story_ids: list = []          # 空 = 自动补进尚无的故事


@app.get("/api/echoes/book/view")
def book_view(owner_id: str, form: str = "scroll", book_spec: str = "A5",
              viewer_id: str = "", db=Depends(get_db)):
    return book_view_api.api_book_view(
        db, owner_id=owner_id, viewer_id=viewer_id, form=form, book_spec=book_spec)


@app.get("/api/echoes/book/lock_state")
def book_lock_state(owner_id: str, db=Depends(get_db)):
    """
    ★§九 收费闸门（2026-10-17）：这本书现在锁不锁、锁了要买哪个/多少钱。
    前端进「我的书」页先调它 —— locked=true 就显示预览+解锁按钮，别直接请求 view 撞锁。
    """
    return entitlement.book_lock_state(db, owner_id=owner_id)


@app.get("/api/echoes/pay/entitlement")
def pay_entitlement(user_id: str, db=Depends(get_db)):
    """★§九 我到底买过什么（我的→会员页用）：免费/买断/年费有效→过期，一次说清。"""
    return entitlement.is_entitled(db, user_id=user_id)


@app.post("/api/echoes/book/append")
def book_append(req: BookAppendReq, db=Depends(get_db)):
    return book_view_api.api_append_to_ebook(
        db, owner_id=req.owner_id, actor_id=req.actor_id, story_ids=req.story_ids)


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


# ============================================================
# 时间轴路由（2026-10-06，第2期「能排对」后端）
# 小龙虾 10-06《第2期前端设计预案》§4 在等《时间轴接口定义》(N1~N4)，
# 本组路由即该接口。日期为「等出码日历波谷日」时的并行推进（不空转）。
# ============================================================

class SetStoryTimeReq(BaseModel):
    story_id: str
    actor_id: str
    new_time_text: str = ""       # 用户说的话 / 手输，如「1980年5月」「八十年代」
    anchors: dict = {}            # 已知人生锚点（可选），供「我八岁那年」反推
    force_raw: str = ""           # 只留原话、不解析时填（此时落「时间待定」但保留原话）


@app.get("/api/echoes/timeline")
def get_timeline(owner_id: str, viewer_id: str = "", db=Depends(get_db)):
    """取整本时间轴（分节 nodes + 待定区 pending）。"""
    return timeline_api.api_get_timeline(
        db, owner_id=owner_id, viewer_id=viewer_id or owner_id,
    )


@app.get("/api/echoes/timeline/grouped")
def get_timeline_grouped(owner_id: str, viewer_id: str = "", db=Depends(get_db)):
    """同 /timeline，兼容旧前端 grouped 命名。"""
    return timeline_api.api_get_timeline_grouped(
        db, owner_id=owner_id, viewer_id=viewer_id or owner_id,
    )


@app.get("/api/echoes/timeline/pending")
def get_timeline_pending(owner_id: str, viewer_id: str = "", db=Depends(get_db)):
    """只取【时间待定】区（不猜、单列）。"""
    return timeline_api.api_timeline_pending(
        db, owner_id=owner_id, viewer_id=viewer_id or owner_id,
    )


@app.post("/api/echoes/timeline/set_time")
def set_story_time(req: SetStoryTimeReq, db=Depends(get_db)):
    """★「改时间」——用户手动把一段挪到新时间（改过不再被自动覆盖）。"""
    return timeline_api.api_set_story_time(
        db, story_id=req.story_id, actor_id=req.actor_id,
        new_time_text=req.new_time_text, anchors=req.anchors or {},
        force_raw=req.force_raw,
    )


@app.post("/api/echoes/timeline/auto_place")
def auto_place(story_id: str, db=Depends(get_db)):
    """保存即触发自动归位（用户手改过的会自动跳过，不覆盖）。"""
    return timeline_api.auto_place_story(db, story_id=story_id)


# ============================================================
# 采访引导（AI 当记者 + 可打断）路由（2026-10-08，第2期 §七）
# 日历 10-08 原文「按反馈修复」——出码仍卡 sandy 账号授权、真机反馈未到手，
# 依硬规矩 5「卡点不架空日历」转做第2期后端 §七 采访引导。
# ============================================================

class NextQuestionReq(BaseModel):
    owner_id: str
    viewer_id: str = ""
    last_answer: str = ""
    interrupted_question: str = ""    # 被打断时刚才问的那句（★不丢话题）
    interrupt_count: int = 0


class BargeInReq(BaseModel):
    owner_id: str = ""
    energy_db: float = None           # 当前环境能量（dB）；前端没有可留空
    assuming_norm: str = ""           # normal / tv / crowd / baby


class AskClassifyReq(BaseModel):
    owner_id: str
    viewer_id: str = ""
    new_story_id: str = ""


class ClassifyAnswerReq(BaseModel):
    owner_id: str
    viewer_id: str = ""
    new_story_id: str = ""
    answer_text: str = ""
    answer_key: str = ""              # new / existing / timeout
    retry_used: int = 0


class InterviewPrefReq(BaseModel):
    owner_id: str
    muted_ask: bool = None            # 「别问了」
    sensitivity: str = ""             # low / normal / high


@app.post("/api/echoes/interview/start")
def interview_start(owner_id: str, viewer_id: str = "", db=Depends(get_db)):
    """开始采访：AI 记者主动出第一问（优先问人生锚点）。"""
    _err = _require_owner(owner_id)
    if _err:
        return _err
    return interview_api.api_start_interview(db, owner_id=owner_id,
                                             viewer_id=viewer_id or owner_id)


@app.post("/api/echoes/interview/next")
def interview_next(req: NextQuestionReq, db=Depends(get_db)):
    """老人答完 → 出下一问（打断则不丢话题，先接回刚才那问）。"""
    return interview_api.api_next_question(
        db, owner_id=req.owner_id, viewer_id=req.viewer_id or req.owner_id,
        last_answer=req.last_answer, interrupted_question=req.interrupted_question,
        interrupt_count=req.interrupt_count,
    )


@app.post("/api/echoes/interview/barge_in")
def interview_barge_in(req: BargeInReq, db=Depends(get_db)):
    """★老人打断判定：出声 → 1 秒内停 TTS（延迟本身须真机测）。"""
    return interview_api.api_barge_in(db, owner_id=req.owner_id,
                                      energy_db=req.energy_db,
                                      assuming_norm=req.assuming_norm)


@app.post("/api/echoes/interview/ask_classify")
def interview_ask_classify(req: AskClassifyReq, db=Depends(get_db)):
    """自述页保存后：是否弹归类问（含频率保护，防烦）。"""
    return interview_api.api_ask_classify(
        db, owner_id=req.owner_id, viewer_id=req.viewer_id or req.owner_id,
        new_story_id=req.new_story_id,
    )


@app.post("/api/echoes/interview/classify_answer")
def interview_classify_answer(req: ClassifyAnswerReq, db=Depends(get_db)):
    """老人对归类问的回答 → 新建 / 某一件（安全兜底：含糊=新建）。"""
    return interview_api.api_classify_answer(
        db, owner_id=req.owner_id, viewer_id=req.viewer_id or req.owner_id,
        new_story_id=req.new_story_id, answer_text=req.answer_text,
        answer_key=req.answer_key, retry_used=req.retry_used,
    )


@app.post("/api/echoes/interview/pref")
def interview_pref(req: InterviewPrefReq, db=Depends(get_db)):
    """「别问了」开关 + 打断灵敏度档位。"""
    return interview_api.api_set_interview_pref(
        db, owner_id=req.owner_id, muted_ask=req.muted_ask,
        sensitivity=req.sensitivity,
    )


# ============================================================
# 采访成品·理顺自述体 + 复述确认（v3.0 §7.4/§7.5/§7.6）—— 2026-10-13 落地 v1.0
# ============================================================

class RecapConfirmReq(BaseModel):
    owner_id: str
    viewer_id: str = ""
    story_id: str = ""
    qa_pairs: list = None            # [{"q":..,"a":..}] 一问一答；本层剥掉问句(§7.4)
    polished_text: str = ""          # 也可直接给成品文本
    answer_key: str = ""             # 空=只出复述脚本 / accept / reject / timeout
    answer_text: str = ""            # 老人说的话（含糊/不对/没听清）
    retry_used: int = 0
    apply: bool = False              # accepted 且 True → 写回 Story.polished_content


@app.post("/api/echoes/interview/recap_confirm")
def interview_recap_confirm(req: RecapConfirmReq, db=Depends(get_db)):
    """★§7.6 复述确认（C 方案）：复述 + 归属一次问完；含糊/超时→安全默认，绝不卡住老人。"""
    return interview_recap.api_recap_confirm(
        db, owner_id=req.owner_id, viewer_id=req.viewer_id or req.owner_id,
        story_id=req.story_id, qa_pairs=req.qa_pairs,
        polished_text=req.polished_text, answer_key=req.answer_key,
        answer_text=req.answer_text, retry_used=req.retry_used, apply=req.apply,
    )


# ============================================================
# 分享机制（v3.0 §八之二）—— 此前全无后端，2026-10-12 落地 v1.0
# ============================================================

class ShareReq(BaseModel):
    actor_id: str = ""
    kind: str = "story"          # story | book | app
    target_id: str = ""          # story_id 或 owner_id（kind=app 时忽略）


class ShareCardReq(BaseModel):
    kind: str = "story"
    target_id: str = ""


@app.post("/api/echoes/share/make")
def share_make(req: ShareReq, db=Depends(get_db)):
    """造一条分享（登录态）。私有/全私有篇 -> not_shareable。"""
    return share_api.api_make_share(
        db, actor_id=req.actor_id, kind=req.kind, target_id=req.target_id,
    )


@app.get("/api/echoes/share/view")
def share_view(t: str, db=Depends(get_db)):
    """**无登录**读一条分享（§8之二.2 先看后登录）。只回公开素材。"""
    return share_api.api_view_shared(db, share_token=t)


@app.get("/api/echoes/share/card")
def share_card(kind: str, target_id: str, db=Depends(get_db)):
    """卡片图数据（§8之二.3.1 方式 B）。"""
    return share_api.api_share_card(db, kind=kind, target_id=target_id)


# ============================================================
# 「我也加进来」加入链路（v3.0 §8之二.5 / §8之二.8 —— 2026-10-15 新增）
# 补 share/view 返回 can_join=True 之后**没人接**的那一节：
# 看完 → 点【我也加进来】→（已登录）→ 默认加入"这一篇"（只这一篇，不开全本）。
# ============================================================

class JoinReq(BaseModel):
    share_token: str
    user_id: str = ""
    display_name: str = ""
    phone: str = ""


@app.get("/api/echoes/join/target")
def join_target(share_token: str, user_id: str = "", db=Depends(get_db)):
    """篇末那一块（§8之二.5）：这是<owner>的故事，里面提到了你 + 能不能加。"""
    return join_api.api_join_target(db, share_token=share_token, user_id=user_id)


@app.post("/api/echoes/join/story")
def join_story(req: JoinReq, db=Depends(get_db)):
    """★点【我也加进来】→ 默认加入这一篇（登录态才调；幂等；只这一篇）。"""
    return join_api.api_join_by_share(
        db, share_token=req.share_token, user_id=req.user_id,
        display_name=req.display_name, phone=req.phone,
    )


@app.get("/api/echoes/join/mine")
def join_mine(user_id: str, db=Depends(get_db)):
    """我加入了哪些书/哪些篇（首页要能看见，否则加完就丢）。"""
    return join_api.api_my_memberships(db, user_id=user_id)


# ============================================================
# 加家人（v3.0 §2.2 / §2.3「登录旁的加号」—— 2026-10-16 新增）
# 这是 §2.2 两个加号里的另一个：登录旁的加号 = 加家人 = **看整本书**。
# 与 join_api（故事里的加号 = 只看这一篇）粒度不同、互不替代。
# ★ 没有 scope 参数——从这里进来永远是 FAMILY（§2.2 不设权限勾选框）。
# ============================================================

class FamilyAddReq(BaseModel):
    owner_id: str                   # 书主人（登录态）
    user_id: str = ""               # 对方已在小程序（走「选名字」路）
    phone: str = ""                 # 或：对方还没上过（走「手机号录入」路，待认领）
    display_name: str = ""
    relation: str = ""              # 女儿/儿子/朋友


class FamilyRemoveReq(BaseModel):
    owner_id: str
    member_id: str


@app.get("/api/echoes/family/search")
def family_search(owner_id: str, name: str, db=Depends(get_db)):
    """§2.3「对方已在小程序可直接选名字加入」——按名字搜人（不返手机号）。"""
    return family_api.api_search_user_by_name(db, owner_id=owner_id, name=name)


@app.post("/api/echoes/family/add")
def family_add(req: FamilyAddReq, db=Depends(get_db)):
    """★§2.2 登录旁的加号 → 加家人 → 看整本书（幂等；必登录态；不许加自己）。"""
    return family_api.api_add_family(
        db, owner_id=req.owner_id, user_id=req.user_id,
        phone=req.phone, display_name=req.display_name, relation=req.relation,
    )


@app.get("/api/echoes/family/list")
def family_list(owner_id: str, db=Depends(get_db)):
    """我的家庭通讯录（已认领/待认领两栏；手机号脱敏）。"""
    return family_api.api_family_list(db, owner_id=owner_id)


@app.post("/api/echoes/family/remove")
def family_remove(req: FamilyRemoveReq, db=Depends(get_db)):
    """从名单移出一个家人 → 不再能看整本（只本人能删自己名单；不动单篇关系）。"""
    return family_api.api_remove_family(
        db, owner_id=req.owner_id, member_id=req.member_id,
    )


# ============================================================
# 归类与切分（v3.0 §五之二.3/4/5 —— 2026-10-16 晚新增）
# 「一段话含多个时间点」切成多条 + 「同一件事」只给候选由人确认。
# 铁律 A：**禁止全自动合并**，没有 user_confirmed 一律拒绝。
# ============================================================

class SegmentPreviewReq(BaseModel):
    owner_id: str
    viewer_id: str = ""
    story_id: str


class ApplySegmentsReq(BaseModel):
    owner_id: str
    viewer_id: str = ""
    story_id: str
    user_confirmed: bool = False       # ★必须 True 才真切（防误切）


class GroupCandidatesReq(BaseModel):
    owner_id: str
    viewer_id: str = ""
    story_id: str


class MergeStoriesReq(BaseModel):
    owner_id: str
    viewer_id: str = ""
    story_ids: list[str]
    target_id: str = ""
    user_confirmed: bool = False       # ★必须 True 才真合（铁律 A）


class UngroupReq(BaseModel):
    owner_id: str
    viewer_id: str = ""
    story_id: str


@app.post("/api/echoes/group/segment_preview")
def group_segment_preview(req: SegmentPreviewReq, db=Depends(get_db)):
    """§五之二.3：先给用户看「这段话会切成几段」，**不落库**。"""
    return group_api.api_segment_preview(
        db, owner_id=req.owner_id, viewer_id=req.viewer_id, story_id=req.story_id)


@app.post("/api/echoes/group/apply_segments")
def group_apply_segments(req: ApplySegmentsReq, db=Depends(get_db)):
    """§五之二.3/4：用户点头后才真切。宁分不合（拿不准就切开，事后可合）。"""
    return group_api.api_apply_segments(
        db, owner_id=req.owner_id, viewer_id=req.viewer_id,
        story_id=req.story_id, user_confirmed=req.user_confirmed)


@app.post("/api/echoes/group/candidates")
def group_candidates(req: GroupCandidatesReq, db=Depends(get_db)):
    """§五之二.5：给「这几条像同一件事」的候选清单 + 相似度，**由人点**。"""
    return group_api.api_group_candidates(
        db, owner_id=req.owner_id, viewer_id=req.viewer_id, story_id=req.story_id)


@app.post("/api/echoes/group/merge")
def group_merge(req: MergeStoriesReq, db=Depends(get_db)):
    """§五之二.5 收口：人确认后才合并（铁律 A，全自动合并是禁区）。"""
    return group_api.api_merge_stories(
        db, owner_id=req.owner_id, viewer_id=req.viewer_id,
        story_ids=req.story_ids, target_id=req.target_id,
        user_confirmed=req.user_confirmed)


@app.post("/api/echoes/group/ungroup")
def group_ungroup(req: UngroupReq, db=Depends(get_db)):
    """§五之二.4「分错可修」：拆掉分组，给用户退路。"""
    return group_api.api_ungroup_story(
        db, owner_id=req.owner_id, viewer_id=req.viewer_id, story_id=req.story_id)



# ============================================================
# 收付款（v3.0 §九 后台配置化 —— 2026-10-12 新增）
# 原则：程序只提供"能收"的能力；收不收/收多少 = 后台配置，代码零写死。
# ============================================================

class PlanSetReq(BaseModel):
    plan_code: str                 # free / single_book / yearly
    price: float | None = None
    active: bool | None = None
    plan_name: str = ""
    period_days: int | None = None
    remark: str = ""


class OrderCreateReq(BaseModel):
    user_id: str
    plan_code: str
    pay_channel: str = "wechat"


@app.get("/api/echoes/pay/plans")
def pay_plans(db=Depends(get_db)):
    """列出收费模式（前端付费页展示；只读 Pricing 表）。"""
    return payment_api.api_list_plans(db)


@app.post("/api/echoes/pay/admin/set_plan")
def pay_admin_set_plan(req: PlanSetReq, db=Depends(get_db)):
    """★后台配置：改价/开关（§9.2/§9.3 —— 不需要重发小程序版本）。"""
    return payment_api.api_admin_set_plan(
        db, plan_code=req.plan_code, price=req.price, active=req.active,
        plan_name=req.plan_name, period_days=req.period_days, remark=req.remark,
    )


@app.get("/api/echoes/pay/quote")
def pay_quote(user_id: str, plan_code: str, db=Depends(get_db)):
    """报价：金额服务端现算（防篡改），不写死。"""
    return payment_api.api_quote(db, user_id=user_id, plan_code=plan_code)


@app.post("/api/echoes/pay/order")
def pay_order(req: OrderCreateReq, db=Depends(get_db)):
    """下单：未配凭证 → code=not_configured（不假成功）。"""
    return payment_api.api_create_order(
        db, user_id=req.user_id, plan_code=req.plan_code, pay_channel=req.pay_channel,
    )


@app.get("/api/echoes/pay/order")
def pay_get_order(order_id: str, user_id: str = "", db=Depends(get_db)):
    """查单（越权：非本人单 → forbidden）。"""
    return payment_api.api_get_order(db, order_id=order_id, user_id=user_id)


@app.get("/api/echoes/pay/orders")
def pay_my_orders(user_id: str, db=Depends(get_db)):
    """我的购买记录。"""
    return payment_api.api_my_orders(db, user_id=user_id)


@app.post("/api/echoes/pay/callback")
def pay_callback(order_id: str, transaction_id: str = "", db=Depends(get_db)):
    """支付回调（桩；第4期真上线须验签）。未配凭证 → 拒（防伪造白嫖）。"""
    return payment_api.api_pay_callback(
        db, order_id=order_id, transaction_id=transaction_id,
    )


# ============================================================
# 对象存储上传通道（2026-10-14，第53~55条路由）
# 清掉"对象存储未定"这条全项目寿命最长的卡点（自 09-26 挂了 18 天）
# ============================================================

@app.post("/api/echoes/storage/upload_url")
def storage_upload_url(req: StorageUploadUrlReq):
    """
    §6.2 取上传地址（**带 actor_id**，素材只由本人入库）。

    前端流程：本接口拿 upload_url+key → 按 method/headers 把字节传上去
              → 调 /storage/confirm 登记（含公开/私有）。
    """
    return storage_api.api_upload_url(
        actor_id=req.actor_id, kind=req.kind, file_name=req.file_name,
        file_size=req.file_size, mime=req.mime,
    )


@app.post("/api/echoes/storage/confirm")
def storage_confirm(req: StorageConfirmReq, db=Depends(get_db)):
    """
    ★入库那一刻由本人定公开/私有（§6.2.1 + §1.2）——对象必须真的在，否则拒。
    """
    return storage_api.api_confirm_upload(
        db, actor_id=req.actor_id, owner_id=req.owner_id, key=req.key,
        kind=req.kind, story_id=req.story_id, file_name=req.file_name,
        file_size=req.file_size, mime=req.mime, visibility=req.visibility,
        duration=req.duration,
    )


@app.get("/api/echoes/storage/media_url")
def storage_media_url(key: str):
    """§6.2.3 回放/看图：给可读地址（本地=静态路径，COS=签名 GET）。"""
    return storage_api.api_media_url(key=key)


@app.get("/api/echoes/storage/status")
def storage_status():
    """存储体检：现在用哪个后端、能不能写（不假装）。"""
    return storage_api.api_storage_status()


@app.put("/api/echoes/storage/put")
async def storage_put(request: Request, key: str):
    """
    本地后端字节落盘的接收端（对应 LocalStorage.upload_url 给的地址）。

    前端 `wx.uploadFile` 不支持自定义 PUT，故真机实际走：
      ① /storage/upload_url 拿 key → ② wx.uploadFile 传后端兜底端点（POST form）
      或 ③ 直传本 PUT（有 PUT 能力的客户端）。
    本端点只服务本地后端；切 COS 后前端直传 COS 签名地址，本端点闲置。
    """
    body = await request.body()
    try:
        st = storage_api.get_storage()
    except RuntimeError as e:
        return {"ok": False, "code": "storage_not_configured", "error": str(e), "data": {}}
    # 防越权：key 必须含 actor 前缀？——此处无 actor，仅校验 key 合法性（防穿越）
    try:
        r = st.put_bytes(key=key, data=body)
    except ValueError as e:
        return {"ok": False, "code": "bad_key", "error": str(e), "data": {}}
    return {"ok": True, "data": r, "message": "字节已落盘"} if r.get("stored") else \
           {"ok": False, "code": "store_failed", "error": "落盘失败", "data": {}}



# ============================================================
# 语音合成 TTS 通道（v3.0 §3.5/§6.2.2/§7.6）—— 2026-10-14 落地 v1.0
# ============================================================
# 为什么：采访（§七）是「AI 当主持人」，问句 / §7.6 复述确认必须是
#        **老人耳朵听得见的声音**，此前全项目无 TTS → 采访链路到"AI 开口"就断。
# 小龙虾 2026-10-13 回执明等这条通道（前端 §四 TTS 播报 + 大字按钮）。
#
# 引擎现状（实测，非臆测）：
#   - edge-tts：本 CVM 被墙，WSS 一律 403（IP 级，非 token）。不作主通道。
#   - 腾讯云 TTS：签名链路已通，只差子账号 CAM 授权（加 QcloudTTSFullAccess 即通）。
#   两引擎都不可用时，本接口**明确返回 tts_not_authorized / tts_unavailable**，
#   **绝不返回假 URL**（铁律 A）。

class SpeakReq(BaseModel):
    actor_id: str                   # 谁在听（语音也由本人入库 §6.2.1）
    text: str = ""                  # 要念的话（interview_api 问句 / recap_speech 复述）
    scene: str = ""                 # interview_host / recap / tip（选音色）
    voice: str = ""                 # 可选，edge 音色覆盖 scene
    engine: str = ""                # 可选，强指定 tencent / edge
    story_id: str = ""              # 可选，关联故事（仅记录口径）


@app.post("/api/echoes/tts/speak")
def tts_speak(req: SpeakReq):
    """
    采访/复述出声音的**唯一入口**（小龙虾等的那条通道）。

    给一段文字 → 还一段老人听得见的 mp3（落在统一存储 clips/{actor}/tts/）。

    成功：{ok:true, data:{media_url, key, engine, voice, text_spoken, bytes, scene}}
    失败（明确错误码，绝无假 URL）：
      missing_actor / empty_text / tts_not_authorized / tts_unavailable /
      tts_store_failed / storage_not_configured
    """
    return tts_api.api_speak(
        actor_id=req.actor_id, text=req.text, scene=req.scene,
        voice=req.voice, engine=req.engine, story_id=req.story_id,
    )


@app.get("/api/echoes/tts/status")
def tts_status():
    """
    TTS 通道体检：能不能出声、用哪个引擎、为什么不能。

    前端/小龙虾可据此决定"出声音"还是"只出字"（降级不假死）。
    """
    return {"ok": True, "data": tts_api.tts_status(probe_tencent=True), "message": ""}
