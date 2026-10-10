"""
往事可追忆 - 素材采集接口（handler 层）v1.1 —— 语音 / 原声 / 视频
第1期 B 线：文字/图片（09-26 已就绪） → **语音 / 原声 / 视频（本文件，09-28 提前完成 09-29 任务）**

=== 为什么另起一个文件而不是塞进 collect_api.py ===
collect_api.py 已经 275 行、只负责「纯登记类」素材（文字/图片，无转写、无时长）。
语音/视频多了三件麻烦事，混进去会让那个文件变成大杂烩：
  1. **转写**：语音要落 transcript，且要能失败不影响原声落库（v2.4 铁律：原声必留）
  2. **时长校验**：老人常录 30 分钟不松手，必须给上限并回可读中文
  3. **转码/格式**：微信小程序录音默认 mp3 或 silk，视频是 mp4
所以本文件 = collect_api.py 的「重量级素材」分册，共用同一套信封（ok/fail）与权限口径。

=== 对照需求书 v2.4 ===
第2节「一条故事 = 一个素材筐」；铁律「**语音保留原声，不只是转文字**」。
→ 所以本文件里：**原声先落库**（media_url 必填），**转写在原声之后**，
  转写失败/超时/密钥没开，**只影响 text 字段为空，绝不影响这条素材存在**。

=== 讯飞密钥现状（09-28）===
讯飞 IAT 密钥**已作废（sandy 09-25 定案换腾讯云）**，asr.recognize() 三级兜底：
  讯飞跳过 → 百度未配置 → 本地 whisper（本机未装 faster-whisper）
→ 实测 `recognize()` 返回 `{"error": "...", "mock": true, "text": ""}`。
本文件对此的处理是**正确姿势**：转写失败 → transcript 留空 + 给前端一句可读提示
「原声已存下，文字转写暂时没成功（语音识别服务未开通），不影响你的记录」——
**不假装成功、不丢原声、不报错穿到 web 层**。密钥一开通，这里零改动自动生效。

=== 设计铁律（沿用 collect_api.py）===
1. handler 不自己开 session —— db 由调用方传
2. 统一信封 {"ok": bool, "data": {...}, "error": "...", "code": "..."}
3. 原声必留；转写失败不阻断落库
4. 绝不静默丢素材：任何拒绝都带中文原因
"""

import os
import math

from permissions import attach_clip, can_add_clip, can_view_story
from models import ClipType

# 转写引擎：整包 import asr，调 asr.recognize()。asr 内部是三级兜底，不会抛穿。
try:
    import asr as _asr
except Exception as _e:            # 极端情况下（缺依赖）也不能让采集接口 import 失败
    _asr = None
    _ASR_IMPORT_ERR = str(_e)
else:
    _ASR_IMPORT_ERR = ""


# ============================================================
# 一、统一信封（与 collect_api.py 完全同形，前端一套解析走天下）
# ============================================================

def ok(data=None, **extra):
    d = {"ok": True, "data": data if data is not None else {}}
    d.update(extra)
    return d


def fail(msg: str, code: str = "bad_request", **extra):
    d = {"ok": False, "error": msg, "code": code, "data": {}}
    d.update(extra)
    return d


# ============================================================
# 二、常量（物理上限：微信小程序录音/拍视频的实操值）
# ============================================================

MAX_AUDIO_MB = 20                      # 单条语音上限
MAX_AUDIO_BYTES = MAX_AUDIO_MB * 1024 * 1024
ALLOWED_AUDIO_EXT = {".mp3", ".wav", ".m4a", ".aac", ".amr", ".silk", ".pcm", ".ogg", ".webm"}
ALLOWED_AUDIO_MIME = {
    "audio/mpeg", "audio/mp3", "audio/wav", "audio/x-wav", "audio/mp4",
    "audio/m4a", "audio/x-m4a", "audio/aac", "audio/amr", "audio/ogg",
    "audio/webm", "audio/silk",
}

MAX_VIDEO_MB = 200                     # 单条视频上限（老人拍大段，给宽一点）
MAX_VIDEO_BYTES = MAX_VIDEO_MB * 1024 * 1024
ALLOWED_VIDEO_EXT = {".mp4", ".mov", ".m4v", ".3gp", ".webm", ".avi", ".mkv"}
ALLOWED_VIDEO_MIME = {
    "video/mp4", "video/quicktime", "video/x-m4v", "video/3gpp",
    "video/webm", "video/x-msvideo", "video/x-matroska",
}

MAX_AUDIO_SECONDS = 60 * 15            # 单条语音上限 15 分钟（超了提示分段，不是拒收）
MAX_VIDEO_SECONDS = 60 * 10            # 单条视频上限 10 分钟
MIN_AUDIO_SECONDS = 0.5                # 太短 = 误触，给可读提示
MAX_CAPTION_CHARS = 200


# ============================================================
# 三、校验（拆出来单测，不碰库）
# ============================================================

def validate_audio(*, file_name: str = "", file_size: int = 0, mime: str = "",
                   duration: float = 0.0) -> tuple:
    """语音前置校验。返回 (是否通过, 中文原因, 提示语)。"""
    ext = os.path.splitext(file_name or "")[1].lower()
    if ext and ext not in ALLOWED_AUDIO_EXT:
        return False, f"不支持的语音格式：{ext}（支持 mp3/wav/m4a/amr/silk 等）", ""
    if not ext and (mime or "") not in ALLOWED_AUDIO_MIME:
        return False, "认不出这是语音（既没有可识别的扩展名，也没有语音类型标识）", ""

    if file_size is None or file_size <= 0:
        return False, "语音是空的（文件大小为0）", ""
    if file_size > MAX_AUDIO_BYTES:
        got = math.ceil(file_size / 1024 / 1024)
        return False, f"语音太大了（{got}MB，上限{MAX_AUDIO_MB}MB）", ""

    if duration and duration < MIN_AUDIO_SECONDS:
        return False, "这条语音太短了（像是误碰了一下）", "请按住多说几句"
    if duration and duration > MAX_AUDIO_SECONDS:
        # 不是拒收，是提示分段：返回「通过 + 提示」，由调用方决定是否弹窗
        return True, "", f"这条有点长（{int(duration)}秒），建议下次分几段说，听着不累"
    return True, "", ""


def validate_video(*, file_name: str = "", file_size: int = 0, mime: str = "",
                   duration: float = 0.0) -> tuple:
    """视频前置校验。返回 (是否通过, 中文原因, 提示语)。"""
    ext = os.path.splitext(file_name or "")[1].lower()
    if ext and ext not in ALLOWED_VIDEO_EXT:
        return False, f"不支持的视频格式：{ext}（支持 mp4/mov/3gp 等）", ""
    if not ext and (mime or "") not in ALLOWED_VIDEO_MIME:
        return False, "认不出这是视频（既没有可识别的扩展名，也没有视频类型标识）", ""

    if file_size is None or file_size <= 0:
        return False, "视频是空的（文件大小为0）", ""
    if file_size > MAX_VIDEO_BYTES:
        got = math.ceil(file_size / 1024 / 1024)
        return False, f"视频太大了（{got}MB，上限{MAX_VIDEO_MB}MB）", ""

    if duration and duration > MAX_VIDEO_SECONDS:
        return True, "", f"这条视频有点长（{int(duration/60)}分钟），建议分几段拍"
    return True, "", ""


# ============================================================
# 四、转写（原声落库之后的第二步；失败不阻断）
# ============================================================

def try_transcribe(audio_path: str, *, enabled: bool = True) -> dict:
    """
    尝试把语音文件转成文字。**任何情况都不抛异常**。

    返回统一形状：
      {"done": bool, "text": str, "source": str, "reason": str}
      done=False 时 text 为空、reason 是一句**给前端直接用**的中文话。

    铁律：这里失败 = 只是没文字，**不影响原声素材已经存下来**。
    """
    if not enabled:
        return {"done": False, "text": "", "source": "", "reason": "本次未做转写"}
    if _asr is None:
        return {"done": False, "text": "", "source": "",
                "reason": f"语音识别模块不可用（{_ASR_IMPORT_ERR}）"}
    if not audio_path or not os.path.exists(audio_path):
        return {"done": False, "text": "", "source": "",
                "reason": "原声文件不在本机，转写稍后由后台补"}

    try:
        import json as _json
        raw = _asr.recognize(audio_path)
        obj = _json.loads(raw) if isinstance(raw, str) else (raw or {})
    except Exception as e:
        return {"done": False, "text": "", "source": "", "reason": f"转写出错：{e}"}

    text = (obj.get("text") or "").strip()
    if text:
        return {"done": True, "text": text, "source": obj.get("source", ""), "reason": ""}
    return {"done": False, "text": "", "source": obj.get("source", ""),
            "reason": "原声已存下，文字转写暂时没成功（语音识别服务尚未开通），不影响你的记录"}


# ============================================================
# 五、handler：语音素材（保留原声 + 尽量转写）
# ============================================================

def api_add_audio_clip(
    db,
    *,
    story_id: str,
    owner_id: str,
    actor_id: str,
    media_url: str,
    file_name: str = "",
    file_size: int = 0,
    mime: str = "",
    duration: float = 0.0,
    caption: str = "",
    audio_path: str = "",
    do_transcribe: bool = True,
    visibility: str = "",
    provider_id: str = "",
    source_type: str = "",
    ref_from_id: str = "",
    ref_author_name: str = "",
) -> dict:
    """
    往里挂一件**语音**素材。

    关键顺序（v2.4 铁律）：
      1) 先校验权限 + 文件
      2) **先把原声落库**（ClipType.AUDIO，media_url 必填，keep_original_voice 强制 True）
      3) 再尝试转写；转写成功 → 回填 transcript；失败 → transcript 留空并给提示
    这样即使识别全挂，老人的声音也一个字不丢。

    audio_path：本机原声文件路径（可选）。传了才可能同步转写；
                没传（如字节在对象存储）则本条只留原声，转写走后台补。
    """
    if not story_id:
        return fail("缺少 story_id", "missing_story_id")
    if not media_url:
        return fail("缺少语音地址（media_url）——原声必须留下", "missing_media_url")

    passed, why, hint = validate_audio(
        file_name=file_name, file_size=file_size, mime=mime, duration=duration
    )
    if not passed:
        return fail(why, "invalid_audio")

    if not can_add_clip(db, owner_id=owner_id, viewer_id=actor_id, story_id=story_id):
        return fail("你没有权限往这条故事里补充内容", "no_permission")

    # ---- 第 2 步：原声先落库 ----
    try:
        clip = attach_clip(
            db,
            story_id=story_id,
            clip_type=ClipType.AUDIO,
            media_url=media_url,
            media_duration=float(duration or 0.0),
            media_size=file_size,
            caption=(caption or "")[:MAX_CAPTION_CHARS],
            keep_original_voice=True,          # 铁律，permissions 里也会强制为 True
            created_by=actor_id,
            visibility=visibility,
            provider_id=provider_id or actor_id,
            source_type=source_type,
            ref_from_id=ref_from_id,
            ref_author_name=ref_author_name,
        )
    except ValueError as e:
        return fail(str(e), "attach_failed")

    # ---- 第 3 步：转写（失败不阻断，原声已安全落库）----
    tr = try_transcribe(audio_path, enabled=do_transcribe)
    if tr["done"]:
        clip.transcript = tr["text"]
        db.commit()

    data = {
        "clip_id": clip.id,
        "story_id": clip.story_id,
        "clip_type": clip.clip_type.value,
        "sort_order": clip.sort_order,
        "media_url": clip.media_url,
        "media_duration": clip.media_duration,
        "keep_original_voice": bool(clip.keep_original_voice),
        "transcribed": tr["done"],
        "transcript": clip.transcript or "",
        "transcript_source": tr["source"],
    }
    if tr["done"]:
        return ok(data, message="语音已记下，并转成文字了")
    return ok(data, message="原声已存下（转写稍后）", notice=tr["reason"] + (("；" + hint) if hint else ""))


# ============================================================
# 六、handler：原声素材（只留声音，不转写——保留方言/语气）
# ============================================================

def api_add_original_clip(
    db,
    *,
    story_id: str,
    owner_id: str,
    actor_id: str,
    media_url: str,
    file_name: str = "",
    file_size: int = 0,
    mime: str = "",
    duration: float = 0.0,
    caption: str = "",
    visibility: str = "",
    provider_id: str = "",
    source_type: str = "",
    ref_from_id: str = "",
    ref_author_name: str = "",
) -> dict:
    """
    往里挂一件**原声**素材（ClipType.ORIGINAL）。

    与语音的区别（v2.4）：原声**刻意不转写**——方言、口头语、叹气声本身就是内容。
    sandy 要的是「奶奶怎么说的」，不是「标准普通话转写」。
    """
    if not story_id:
        return fail("缺少 story_id", "missing_story_id")
    if not media_url:
        return fail("缺少原声地址（media_url）——原声必须留下", "missing_media_url")

    passed, why, hint = validate_audio(
        file_name=file_name, file_size=file_size, mime=mime, duration=duration
    )
    if not passed:
        return fail(why, "invalid_audio")

    if not can_add_clip(db, owner_id=owner_id, viewer_id=actor_id, story_id=story_id):
        return fail("你没有权限往这条故事里补充内容", "no_permission")

    try:
        clip = attach_clip(
            db,
            story_id=story_id,
            clip_type=ClipType.ORIGINAL,
            media_url=media_url,
            media_duration=float(duration or 0.0),
            media_size=file_size,
            caption=(caption or "")[:MAX_CAPTION_CHARS],
            keep_original_voice=True,
            created_by=actor_id,
        )
    except ValueError as e:
        return fail(str(e), "attach_failed")

    return ok({
        "clip_id": clip.id,
        "story_id": clip.story_id,
        "clip_type": clip.clip_type.value,
        "sort_order": clip.sort_order,
        "media_url": clip.media_url,
        "media_duration": clip.media_duration,
        "keep_original_voice": bool(clip.keep_original_voice),
    }, message="原声已存下", notice=(hint or "这段原声按原样留着，不改一个字"))


# ============================================================
# 七、handler：视频素材
# ============================================================

def api_add_video_clip(
    db,
    *,
    story_id: str,
    owner_id: str,
    actor_id: str,
    media_url: str,
    file_name: str = "",
    file_size: int = 0,
    mime: str = "",
    duration: float = 0.0,
    cover_url: str = "",
    caption: str = "",
    visibility: str = "",
    provider_id: str = "",
    source_type: str = "",
    ref_from_id: str = "",
    ref_author_name: str = "",
) -> dict:
    """
    往里挂一件**视频**素材。

    cover_url：微信 wx.chooseMedia 会给一张缩略图路径/图，前端上传后带回来；
              没给就先用视频地址顶（列表页再取首帧）。
    """
    if not story_id:
        return fail("缺少 story_id", "missing_story_id")
    if not media_url:
        return fail("缺少视频地址（media_url）", "missing_media_url")

    passed, why, hint = validate_video(
        file_name=file_name, file_size=file_size, mime=mime, duration=duration
    )
    if not passed:
        return fail(why, "invalid_video")

    if not can_add_clip(db, owner_id=owner_id, viewer_id=actor_id, story_id=story_id):
        return fail("你没有权限往这条故事里补充内容", "no_permission")

    try:
        clip = attach_clip(
            db,
            story_id=story_id,
            clip_type=ClipType.VIDEO,
            media_url=media_url,
            media_duration=float(duration or 0.0),
            media_size=file_size,
            cover_url=cover_url or media_url,
            caption=(caption or "")[:MAX_CAPTION_CHARS],
            created_by=actor_id,
        )
    except ValueError as e:
        return fail(str(e), "attach_failed")

    return ok({
        "clip_id": clip.id,
        "story_id": clip.story_id,
        "clip_type": clip.clip_type.value,
        "sort_order": clip.sort_order,
        "media_url": clip.media_url,
        "cover_url": clip.cover_url,
        "media_duration": clip.media_duration,
    }, message="视频已存下", notice=(hint or ""))


# ============================================================
# 八、handler：补转写（原声先存、文字后补的统一入口）
# ============================================================

def api_transcribe_clip(
    db,
    *,
    clip_id: str,
    owner_id: str,
    viewer_id: str,
    audio_path: str = "",
) -> dict:
    """
    给一条**已存在**的语音素材补转写（幂等的：已有 transcript 直接返回，不重跑）。

    为什么需要它：老人录完可能马上退出（网络差），此时只落了原声；
    网络好了/密钥开了，前端或后台定时任务调这个把文字补上。**原声永远不会因为转写失败而重录。**
    """
    from models import Clip
    clip = db.get(Clip, clip_id)
    if clip is None:
        return fail("找不到这条素材", "clip_not_found")
    if not can_view_story(db, owner_id=owner_id, viewer_id=viewer_id, story_id=clip.story_id):
        return fail("看不到这条故事", "no_permission")
    if clip.clip_type not in (ClipType.AUDIO, ClipType.ORIGINAL):
        return fail("这条素材不是语音，没有可转写的内容", "not_audio")
    if clip.clip_type == ClipType.ORIGINAL:
        return fail("这是原声素材（按设计不转写，保留方言原样）", "original_not_transcribable")

    if (clip.transcript or "").strip():
        return ok({"clip_id": clip.id, "transcribed": True, "transcript": clip.transcript,
                   "transcript_source": "cached"}, message="已有文字")

    tr = try_transcribe(audio_path)
    if not tr["done"]:
        return fail(tr["reason"], "transcribe_failed", transcribed=False)
    clip.transcript = tr["text"]
    db.commit()
    return ok({"clip_id": clip.id, "transcribed": True, "transcript": tr["text"],
               "transcript_source": tr["source"]}, message="文字已补上")


# ============================================================
# 九、自测建库
# ============================================================

def fresh_db():
    from models import init_db, SessionLocal
    init_db()
    return SessionLocal()
