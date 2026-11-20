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


def _sync_raw_content_from_clips(db, story_id: str) -> None:
    """把这条故事下所有素材的原话按顺序拼进 stories.raw_content。

    ★ 2026-11-18 新增（治「故事正文永远为空」）
    规则：
      1) **只补空位，不覆盖已加工内容**——raw_content 已有字就只在末尾追加
         本次新增的段落；绝不整段重写（避免冲掉用户/润色改过的正文）。
      2) **幂等**——同一段原话已经在正文里就不再追加。判据用「该段是否
         已作为子串存在」，重复调用不会叠出两遍。
      3) 顺序按 clips.sort_order，保证「先说的在前」。
      4) 空白转写跳过（录音没识别出字的，不塞空行）。
    失败不抛——回写正文是锦上添花，不能反过来把「原声已存下」这件事搞挂。
    """
    try:
        from models import Story, Clip
        s = db.query(Story).filter(Story.id == story_id).first()
        if s is None:
            return
        clips = (db.query(Clip)
                   .filter(Clip.story_id == story_id)
                   .order_by(Clip.sort_order.asc())
                   .all())
        base = (s.raw_content or "")
        added = []
        for c in clips:
            txt = (getattr(c, "text", "") or getattr(c, "transcript", "") or "").strip()
            if not txt:
                continue
            # 幂等：这段原话已经在正文里了 → 跳过
            if txt in base or txt in "\n".join(added):
                continue
            added.append(txt)
        if not added:
            return
        joined = "\n".join(added)
        s.raw_content = (base.rstrip() + "\n" + joined) if base.strip() else joined
        db.commit()
    except Exception:
        # 静默不抛，但不能吞得毫无痕迹：留给日志
        try:
            import logging
            logging.getLogger(__name__).warning(
                "sync raw_content 失败 story_id=%s", story_id, exc_info=True)
        except Exception:
            pass


def _make_title(raw: str) -> str:
    """从原话里提炼一句能当标题的人话。

    规则（宁缺毋滥，编不出来就返回空，让界面显示「还没起名字」）：
      1) 剥掉口语起手式（「我是」「我出生在」「现在呢」「我觉得」…），
         这些词占了标题位却不带信息。
      2) 取第一句，长度控制在 6~16 字。
      3) 太短（<4 字，如「我们家是砖房」被剥完只剩俩字）就保留原句。
      4) 剥完啥也不剩 → 返回原句前 16 字。
    **绝不添加原文里没有的词**——标题的每个字都必须来自老人自己说的话。
    """
    import re
    text = (raw or "").strip()
    if not text:
        return ""
    first = text.split("\n")[0].strip()

    # 只剥起手式，不碰后面的内容
    leaders = (
        "我是", "我出生在", "我出生", "我生在", "我来自",
        "现在呢", "现在", "然后呢", "然后", "就是", "其实",
        "我觉得", "我记得", "应该说", "所以", "后来",
    )
    body = first
    changed = True
    while changed:
        changed = False
        for ld in leaders:
            if body.startswith(ld) and len(body) > len(ld) + 3:
                body = body[len(ld):]
                changed = True

    # 截到第一个句读
    for sep in ("。", "，", "！", "？", "；"):
        if sep in body:
            body = body.split(sep)[0]
            break
    body = body.strip(" ，。！？；、")

    # 按句读切成小块，再逐块拼接（避免「1973年」这种纯时间占标题位）
    pieces = [p.strip() for p in re.split(r"[，。！？；]", first) if p.strip()]

    # 剥掉开头的信息量极低的块：纯年份/纯「属牛的」这类短语
    def _low_value(p):
        # 纯年份 / 纯岁数
        if re.fullmatch(r"\d{4}\s*年?", p):
            return True
        if re.fullmatch(r"\d{1,2}\s*岁", p):
            return True
        # 「1973年生的」「1973年出生的」这类：带年份但不带任何事
        if re.search(r"\d{4}\s*年(出生|生|出生在)?(的)?$", p) and len(p) <= 12:
            return True
        # 纯口语填充词
        if p in ("现在", "现在呢", "然后", "然后呢", "我觉得", "就是", "其实", "所以", "后来"):
            return True
        return False

    while pieces and _low_value(pieces[0]):
        pieces = pieces[1:]

    if pieces:
        body = pieces[0]
    else:
        body = first

    # ★ 2026-11-20：抽句只许抽**肯定句**。
    #   "不是在村子里，是在镇上" 抽出来是"不是在村子里"——一句否定，单独看像反问，
    #   当标题是错的。所以优先选不带"不是/没/别"的块；全是否定就退回原句整句。
    _NEG = ("不", "没", "别", "甭")
    if pieces and any(p.startswith(_NEG) for p in pieces[:1]) and len(pieces) > 1:
        positive = [p for p in pieces if not p.startswith(_NEG)]
        if positive:
            body = positive[0]

    # 块以"是/在/有"打头 = 从句，单独拿出来不成句（"是在镇上"）。
    # 这时用**整句**（去掉开头语气词），比硬抠半句强。
    if body.startswith(("是", "在", "有", "就", "也", "都", "才")) and len(first) <= 22:
        body = first

    # 尾巴上的连词/未完成语气词 → 去掉（「…但是」「…所以」「…的话」）
    for tail in ("但是", "所以", "然后", "而且", "因为", "的话", "就是", "并且"):
        if body.endswith(tail):
            body = body[: -len(tail)].rstrip(" ，、")

    # 太短 ⇒ 用原句（剥过头了）
    if len(body) < 4:
        body = first
        for sep in ("。", "，", "！", "？", "；"):
            if sep in body:
                body = body.split(sep)[0]
                break
        body = body.strip(" ，。！？；、")

    # ★ 2026-11-20 补三条（sandy 真机实测出来的坏标题）：
    #   ① 「我是1973年出生的，我想问」——"我想问一个问题"属于**聊天过程**，
    #      不是老人讲的事；这类"提问/抱怨/寒暄"块一律不当标题。
    #   ② 「我爸是一就」——ASR 把「我爸是1939年出生的」切碎成「我爸是一就」，
    #      残句当标题像系统故障；**没讲完的句子不许当标题**。
    #   ③ 兜底：剥完还是碎块（≤5 字且不含动词/名词信息）→ 交给模型另起，
    #      模型不可用就**宁可留空**（留空由界面引导起名），也不印一句残话。
    _CHATTY = ("我想问", "我问一下", "我想说", "你听", "是不是", "为什么",
               "怎么", "你说", "我不知道", "别问", "不要问")
    def _is_chatty(p: str) -> bool:
        return any(p.startswith(c) or c in p for c in _CHATTY)

    if _is_chatty(body):
        pieces = [p for p in pieces if not _is_chatty(p)]
        body = pieces[0] if pieces else ""

    # 残句判定：以「一就」「是」「就」这类断掉的口语收尾，或长度 < 5 且无句读
    _BROKEN_TAILS = ("一就", "就是", "那个", "然后", "可是", "因为", "的", "了")
    if body and (len(body) <= 5 or body.endswith(_BROKEN_TAILS)) and "，" not in first:
        body = ""

    if body:
        return body[:16] if len(body) > 16 else body

    # ★ 残句/寒暄 都剥不出标题 → 让模型起一个（只准用原话里的信息）
    ai = _ai_title(raw)
    return ai or ""


def _ai_title(raw: str) -> str:
    """★ 2026-11-20：残句/寒暄剥不出标题时，让模型另起一句。

    铁律（和老标题规则一致）：**只准用原话里出现过的信息**，不许加原文没有的
    人名/地名/年份/事件。模型不可用 → 返回空串（宁可留空让界面引导起名，
    也不印一句残话）。
    """
    text = (raw or "").strip()
    if not text:
        return ""
    try:
        import llm_brain
        if not llm_brain.llm_available():
            return ""
        msgs = [
            {"role": "system", "content":
             "你是帮老人整理回忆的编辑。给下面这段口述起一个标题。\n"
             "规矩：\n"
             "1) 6~14 个字，像一句人话，不要书名号、不要引号、不要句号。\n"
             "2) **只能用这段话里已经出现过的信息**，不许加原文没有的人名、地名、"
             "年份、事件。\n"
             "3) 标题要**读得通**：不许把几个词硬拼在一起。"
             "反例（都是错的）：『1973年出生孩子10岁属牛』『有一个哥有个姐』。\n"
             "4) 好标题长这样：『我出生在1973年』『我爸是1939年出生的』"
             "『我们家住在镇上的砖房』。\n"
             "5) 如果这段话本身就是没讲完的碎句、或者只是聊天（问问题、抱怨），"
             "不要硬起，直接回两个字：留空。\n"
             "只输出标题本身。"},
            {"role": "user", "content": text[:400]},
        ]
        raw_out, _why = llm_brain._chat(msgs, temperature=0.3, max_tokens=40)
        t = (raw_out or "").strip().strip('"').strip("“”").strip("《》")
        t = t.split("\n")[0].strip().rstrip("。，、")
        if not t or "留空" in t or len(t) < 4 or len(t) > 16:
            return ""
        # 防拼贴：模型爱把两句压成一个"读不通"的短句，如"我出生在1939年的镇上"。
        # 判据——标题里出现"在…的…"这种把地点/时间硬塞进定语的结构，就不要了，
        # 退回规则抽句（宁可标题朴素，也不印一句别扭的话）。
        import re as _re
        if _re.search(r"在\d{4}年的", t) or _re.search(r"出生在.{2,8}的(镇|村|城|家)", t):
            return ""
        # 防拼贴：一串名词直接怼在一起（没有动词/虚词）也判失败
        if not _re.search(r"[是在有了到去和跟把被让给说住]", t):
            return ""
        return t
    except Exception:
        import logging
        logging.getLogger(__name__).warning("AI 起标题失败", exc_info=True)
        return ""


def _enrich_story_meta(db, story_id: str) -> None:
    """给故事补「时间」和「标题」——录完话就自动做，不等用户手填。

    ★ 2026-11-18 新增（治「（无题）· 时间待定」）
    铁律（sandy 定的口径，逐条执行）：
      1) **不编年份**。时间一律走 timeline.extract_time，它认不出就落
         「时间待定」，绝不替老人凑一个年份。
      2) **只在空位写**。用户/家人已经填过 title/time 的，一律不动。
      3) 标题从原话里取**头一句**（截到逗号/句号，≤14 字），
         取不到就留空——留空比编一个假标题好。
    失败不抛。
    """
    try:
        from models import Story
        from timeline import extract_time
        s = db.query(Story).filter(Story.id == story_id).first()
        if s is None:
            return
        raw = (s.raw_content or "").strip()

        # ---- 时间：只补空位 ----
        if not (s.time_label or "").strip() and raw:
            r = extract_time(raw)
            if r is not None:
                if getattr(r, "label", ""):
                    s.time_label = r.label
                if getattr(r, "raw", ""):
                    s.time_raw = r.raw
                if getattr(r, "sort_key", None) is not None:
                    try:
                        s.time_sort_key = int(r.sort_key)
                    except (TypeError, ValueError):
                        pass
                if getattr(r, "method", ""):
                    s.time_extract_method = str(r.method)

        # ---- 标题：只补空位 ----
        # 病根：机械截前 14 字会切出「我出生在1973年，我有一个」这种残句，
        # 老人看了不知道这篇讲什么。标题要是一句完整的人话。
        if not (s.title or "").strip() and raw:
            t = _make_title(raw)
            if t:
                s.title = t

        db.commit()
    except Exception:
        try:
            import logging
            logging.getLogger(__name__).warning(
                "enrich story meta 失败 story_id=%s", story_id, exc_info=True)
        except Exception:
            pass


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
    # ★ 11-10 sandy 实测：转写原始文本不能直接显示/入库
    #   ①「2020年」被认成「二零。020年」②「啊，我在，嗯。」当正文
    #   统一走 asr_text_clean.clean()，只清洗文本、不动原声
    if text:
        try:
            from asr_text_clean import clean as _clean_asr
            text = _clean_asr(text)
        except Exception:
            pass
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
        # ★ 2026-11-18 补：转写成功后回写故事正文。
        #   病根：此前只写 clips.transcript，stories.raw_content 永远空 →
        #   成书页拿到空壳，只能显示「（无题）时间待定」，用户看到的就是
        #   "共2篇·7段"但其实一段话都没有。原话必须在故事正文里能看见。
        _sync_raw_content_from_clips(db, story_id)
        _enrich_story_meta(db, story_id)

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
