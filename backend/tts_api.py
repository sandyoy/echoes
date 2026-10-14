#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
语音合成（TTS）通道 —— 往事可追忆 · 后端
============================================
为什么要有这一块：
  采访（§七）是「AI 当主持人」——它出的问句、§7.6 的复述确认，
  都必须是**老人的耳朵听得见的声音**，不是屏幕上的字。
  此前 `interview_recap` 只产出**文本脚本**（`recap_speech`），
  真出声音这件事**全项目一行代码都没有** → 采访链路到"AI 开口"就断。
  小龙虾 2026-10-13 回执明写：「**前端接 §四（TTS 播报 + 大字按钮）** 仍归我，
  待你有空补 `recap_speech` 的 TTS 通道后我接手」——本文件就是补这个口。

⚠️ 2026-10-14 实测结论（不臆测，有实锤）：
  · **edge-tts 在本 CVM 上被墙**——`speech.platform.bing.com` WSS 握手一律 **403**
    （试了 5 个 Chromium 版本号、手算 Sec-MS-GEC 全 403 → 是 **IP/region 级封锁**，
     不是 token bug，换版本号救不了）。**结论：edge-tts 不能作为本服务器主通道。**
  · **腾讯云 TTS**：签名链路**已实测可用**（同一套 TC3 签名、同一份凭证，
    能拿到规范的 `AuthFailure.UnauthorizedOperation` 响应＝**签名对、只差 CAM 授权**）。
    → 当前 ASR 子账号 `bianch...` 的 CAM 策略**未含 TTS 权限**，
      需在腾讯云控制台给该子账号加 `QcloudTTSFullAccess`（**sandy 控制台一步**）。

因此本层照 `asr.py` 的老规矩做**多引擎兜底**：
  引擎顺序：腾讯云 TTS（凭证+授权齐则首选）→ edge-tts（本机/代理可达时用）
  两个都不可用 → 明确抛 `tts_unavailable`，**绝不返回假 URL / 空文件**。

铁律（与全项目一致）：
  A. **不静默假装**：合成不出声 → 明确报错码，不返回假 URL / 不返回空文件。
  B. **老人口径**：给老人听的话必须**念得出、断得开**——本层做文本规整
     （去 markdown/符号、长句按标点切短），不让 AI 把 "§7.6"、"**"、"1." 直接念出来。
  C. **声音是资产**：合成件也进统一存储（`tts/` 前缀），可复用可回放。
  D. **只做声音，不抢麦**：本层不碰打断逻辑（那是 interview_api 的 `stop_tts`），
     只负责"给一段文字，还一段声音"。

用法：
  python3 tts_api.py "要说的话" [场景]        # 命令行试听
  python3 tts_api.py --status                 # 体检：哪个引擎可用
"""

import os
import re
import sys
import base64
import asyncio
import tempfile
import subprocess

# ============================================================
# 一、音色表（按场景选，不写死在调用方）
# ============================================================

# edge-tts 默认音色：女声、普通话、语速偏慢（老人听）
DEFAULT_VOICE = "zh-CN-XiaoxiaoNeural"

# 场景 → edge-tts 音色
VOICE_BY_SCENE = {
    "interview_host": "zh-CN-XiaoxiaoNeural",   # AI 主持人的问句（亲切）
    "recap": "zh-CN-XiaoxiaoNeural",            # §7.6 复述确认
    "tip": "zh-CN-XiaoxiaoNeural",              # 界面提示音
    "male": "zh-CN-YunxiNeural",                # 备选男声
}

# 场景 → 腾讯云 TTS VoiceType（101001=智瑜 女声/101002=智美/101003=智甜；
# 100510000=智逍遥 男声）。老人听选亲和女声。
TENCENT_VOICE_BY_SCENE = {
    "interview_host": 101001,
    "recap": 101001,
    "tip": 101001,
    "male": 100510000,
}
TENCENT_DEFAULT_VOICE = 101001

# 老人听的默认语速：偏慢一档（§十「摁一下，哒哒就说」+ 老人听感）
DEFAULT_RATE = "-12%"      # edge-tts rate
DEFAULT_VOLUME = "+0%"
DEFAULT_PITCH = "+0Hz"

# 腾讯云 Speed：-2..2（0 正常）。老人听 → 略慢。
TENCENT_SPEED = -1

# 复述/长段允许的最大字符（防一次合成超长卡住）
MAX_TEXT_LEN = 1200

# 引擎名
ENGINE_TENCENT = "tencent"
ENGINE_EDGE = "edge"


class TTSError(Exception):
    """合成失败。不静默——上层据此返回明确错误码。"""


# ============================================================
# 二、文本规整（铁律 B：给老人念的话必须念得出）
# ============================================================

# 不念出来的符号（markdown/项目内部符号/§ 等）
_STRIP_PATTERNS = [
    (re.compile(r"`{1,3}"), ""),                # 反引号
    (re.compile(r"\*{1,3}"), ""),               # 加粗/斜体星号
    (re.compile(r"^\s*#{1,6}\s*", re.M), ""),   # 标题井号
    (re.compile(r"§\s*[\d一二三四五六七八九十点之.]+"), ""),  # 章节号 §7.6（含英文点）
    (re.compile(r"[—–]{2,}"), "，"),             # 破折号
    (re.compile(r"[~～]{1,}"), ""),              # 波浪号
    (re.compile(r"[\u2500-\u257F]"), ""),       # 制表符号
    (re.compile(r"\[(.{0,12}?)\]\(.*?\)"), r"\1"),  # [文字](链接) → 只留文字
    (re.compile(r"[ \t]{2,}"), " "),            # 多空格合一
]


def normalize_for_speech(text: str) -> str:
    """
    把一段"给人看的文字"整理成"给耳朵听的话"。

    做四件事：
      1. 剥掉不念的符号（markdown/章节号/链接）
      2. 换行 → 句号（不然 TTS 会连读）
      3. 长句按标点切短（老人听长句会断片）
      4. 收尾去空白

    **不改动词句本身**——只处理符号与停顿（与 §7.5「理顺≠改写」同一条纪律）。
    """
    if not text:
        return ""
    s = str(text)
    for pat, rep in _STRIP_PATTERNS:
        s = pat.sub(rep, s)
    # 换行/连续空白 → 一个停顿
    s = re.sub(r"\s*\n+\s*", "。", s)
    s = re.sub(r"[ \t]+", " ", s)
    # 尾部重复点号合并（避免停顿过长）
    s = re.sub(r"([。！？；，])\1{1,}", r"\1", s)
    return s.strip()


def split_long_sentences(text: str, *, max_len: int = 38) -> str:
    """
    把超长"句子"（无标点的一长串）在逗号/顿号处断开，
    让 TTS 有自然停顿。已经短的句子不动。

    老人听力对"一口气念 60 字"是灾难——这一步是听感保命线。
    """
    if not text:
        return ""
    out = []
    for seg in re.split(r"(?<=[。！？])", text):
        if not seg:
            continue
        if len(seg) <= max_len:
            out.append(seg)
            continue
        # 在逗号/顿号处二次切（保标点）
        parts = re.split(r"(?<=[，、；])", seg)
        buf = ""
        for p in parts:
            if len(buf) + len(p) > max_len and buf:
                out.append(buf)
                buf = p
            else:
                buf += p
        if buf:
            out.append(buf)
    return "".join(out)


def prepare_text(text: str) -> str:
    """规整 + 切句，合成前统一走这里。"""
    s = normalize_for_speech(text)
    s = split_long_sentences(s)
    s = s.strip()
    if len(s) > MAX_TEXT_LEN:
        s = s[:MAX_TEXT_LEN]
    return s


# ============================================================
# 三、引擎可用性探测（铁律 A：没有就明说）
# ============================================================

def _edge_tts_available() -> bool:
    try:
        import edge_tts  # noqa: F401
        return True
    except Exception:
        return False


def _tencent_credentials_ok() -> bool:
    """有没有腾讯云凭证（有凭证 ≠ 有 TTS 授权，授权要真调才知道）。"""
    try:
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        import tencent_asr as T
        return bool(T.has_credentials())
    except Exception:
        return False


def tencent_tts_probe() -> dict:
    """
    真调一次腾讯云 TTS（1 个字），判定"签名对 + 授权有"。

    返回 {ok, engine, code, message}
      · ok=True            → 真能用
      · code=tts_not_authorized → 签名对但 CAM 没给 TTS 权限（sandy 控制台加策略）
      · code=tts_unavailable    → 其它（网络/凭证）
    """
    if not _tencent_credentials_ok():
        return {"ok": False, "code": "tts_unavailable",
                "message": "腾讯云凭证未配，不能合成"}
    try:
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        import tencent_asr as T
        params = {
            "Text": "好",
            "SessionId": "echoes-tts-probe",
            "ModelType": 1, "VoiceType": TENCENT_DEFAULT_VOICE,
            "PrimaryLanguage": 1, "SampleRate": 16000,
            "Codec": "mp3", "Speed": 0, "Volume": 0,
        }
        resp = T._call_api("TextToVoice", params, service="tts",
                           host="tts.tencentcloudapi.com", version="2019-08-23")
        if resp.get("Audio"):
            return {"ok": True, "code": "", "message": "腾讯云 TTS 可用"}
        return {"ok": False, "code": "tts_empty_output",
                "message": "腾讯云 TTS 返回空音频"}
    except Exception as e:
        msg = str(e)
        if "UnauthorizedOperation" in msg or "not authorized" in msg:
            return {"ok": False, "code": "tts_not_authorized",
                    "message": "腾讯云凭证没有 TTS 授权（控制台给子账号加 QcloudTTSFullAccess 即可）"}
        if "InvalidAction" in msg:
            return {"ok": False, "code": "tts_unavailable", "message": msg[:200]}
        return {"ok": False, "code": "tts_unavailable", "message": msg[:200]}


def tts_status(*, probe_tencent: bool = False) -> dict:
    """
    体检：TTS 通道能不能用、用哪个引擎。

    返回 {available, engine, voices, notes:[...]}
      · available=True   → 至少一个引擎真能出声
      · available=False  → 都不可用（附原因，供排查）

    probe_tencent=True 时才真调腾讯云（默认只查本地依赖，省一次外网调用；
    体检接口 /tts/status 用 True）。
    """
    notes = []
    engine = ""

    # 1) 腾讯云 TTS
    t = tencent_tts_probe() if probe_tencent else {
        "ok": False, "code": "", "message": "未探测（需授权确认）"}
    if t["ok"]:
        engine = ENGINE_TENCENT
    else:
        if t.get("code"):
            notes.append(f"腾讯云 TTS：{t['message']}")

    # 2) edge-tts（本机依赖在，但**本 CVM 实测被墙 403**）
    edge_dep = _edge_tts_available()
    if not engine and edge_dep:
        if _edge_reachable():
            engine = ENGINE_EDGE
        else:
            notes.append("edge-tts：本机已装，但 speech.platform.bing.com 握手 403"
                         "（本服务器 IP 被拦，非 token 问题）")
    elif not edge_dep:
        notes.append("edge-tts：本机未装")

    return {
        "available": bool(engine),
        "engine": engine,
        "edge_voice": DEFAULT_VOICE,
        "tencent_voice": TENCENT_DEFAULT_VOICE,
        "notes": notes,
    }


_EDGE_CACHE = {"checked": False, "ok": False}


def _edge_reachable() -> bool:
    """
    真连一次 edge-tts 的 WSS，判可达。缓存结果（同进程不重复握手）。

    2026-10-14 实测：本 CVM 一律 403 → 返回 False。
    """
    if _EDGE_CACHE["checked"]:
        return _EDGE_CACHE["ok"]
    _EDGE_CACHE["checked"] = True
    if not _edge_tts_available():
        _EDGE_CACHE["ok"] = False
        return False
    try:
        asyncio.run(_edge_handshake_probe())
        _EDGE_CACHE["ok"] = True
    except Exception:
        _EDGE_CACHE["ok"] = False
    return _EDGE_CACHE["ok"]


async def _edge_handshake_probe():
    import edge_tts
    c = edge_tts.Communicate("好", DEFAULT_VOICE)
    async for ch in c.stream():
        if ch.get("type") == "audio":
            return
    raise RuntimeError("edge-tts 无音频返回")


# ============================================================
# 四、核心合成：两个引擎各自的实现
# ============================================================

def _voice_for_scene(scene: str, voice: str = "") -> str:
    if voice:
        return voice
    return VOICE_BY_SCENE.get(scene or "", DEFAULT_VOICE)


def _tencent_voice_for_scene(scene: str, voice_type=None) -> int:
    if voice_type:
        return int(voice_type)
    return TENCENT_VOICE_BY_SCENE.get(scene or "", TENCENT_DEFAULT_VOICE)


async def _edge_synth_async(text: str, out_path: str, *,
                            voice: str, rate: str, volume: str, pitch: str) -> None:
    import edge_tts
    communicate = edge_tts.Communicate(
        text, voice, rate=rate, volume=volume, pitch=pitch,
    )
    with open(out_path, "wb") as f:
        async for chunk in communicate.stream():
            if chunk.get("type") == "audio":
                f.write(chunk["data"])


def _synth_tencent(text: str, out_path: str, *, scene: str,
                   voice_type=None) -> None:
    """腾讯云 TTS：TextToVoice，返回 base64 mp3 → 落盘。"""
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import tencent_asr as T
    params = {
        "Text": text,
        "SessionId": "echoes-tts",
        "ModelType": 1,
        "VoiceType": _tencent_voice_for_scene(scene, voice_type),
        "PrimaryLanguage": 1,
        "SampleRate": 16000,
        "Codec": "mp3",
        "Speed": TENCENT_SPEED,
        "Volume": 0,
    }
    resp = T._call_api("TextToVoice", params, service="tts",
                       host="tts.tencentcloudapi.com", version="2019-08-23")
    audio_b64 = resp.get("Audio")
    if not audio_b64:
        raise TTSError("tts_empty_output：腾讯云 TTS 返回空音频")
    with open(out_path, "wb") as f:
        f.write(base64.b64decode(audio_b64))


def synth_to_file(text: str, out_path: str, *, scene: str = "",
                  engine: str = "", voice: str = "", voice_type=None,
                  rate: str = DEFAULT_RATE, volume: str = DEFAULT_VOLUME,
                  pitch: str = DEFAULT_PITCH) -> dict:
    """
    合成文本 → mp3 文件（写到 out_path）。

    engine="" 时按兜底顺序选（腾讯云 → edge）。可强制指定 engine。

    **不静默假装**：
      - 空文本/规整后为空 → TTSError
      - 指定/兜底引擎都不可用或失败 → TTSError（带明确 code）

    返回 {path, bytes, engine, voice, text_spoken}
    """
    spoken = prepare_text(text)
    if not spoken:
        raise TTSError("empty_text：没有可念的内容")

    engines = [engine] if engine else [ENGINE_TENCENT, ENGINE_EDGE]
    errs = []
    for eng in engines:
        try:
            if eng == ENGINE_TENCENT:
                if not _tencent_credentials_ok():
                    errs.append("腾讯云 TTS：无凭证")
                    continue
                _synth_tencent(spoken, out_path, scene=scene, voice_type=voice_type)
                used_voice = _tencent_voice_for_scene(scene, voice_type)
            elif eng == ENGINE_EDGE:
                if not _edge_tts_available():
                    errs.append("edge-tts：本机未装")
                    continue
                v = _voice_for_scene(scene, voice)
                asyncio.run(_edge_synth_async(
                    spoken, out_path, voice=v, rate=rate, volume=volume, pitch=pitch,
                ))
                used_voice = v
            else:
                continue

            if not os.path.isfile(out_path) or os.path.getsize(out_path) == 0:
                errs.append(f"{eng}：合成返回空文件")
                continue
            return {
                "path": out_path,
                "bytes": os.path.getsize(out_path),
                "engine": eng,
                "voice": used_voice,
                "text_spoken": spoken,
            }
        except TTSError as e:
            errs.append(str(e))
        except Exception as e:
            errs.append(f"{eng}：{type(e).__name__}: {str(e)[:120]}")

    # 全部失败 → 归类报错（授权问题单列，好让 sandy 一眼看到要去控制台点一下）
    joined = " | ".join(errs)
    if "not authorized" in joined or "UnauthorizedOperation" in joined:
        raise TTSError("tts_not_authorized：腾讯云凭证缺 TTS 授权，且 edge-tts 不可用。"
                       "去控制台给子账号加 QcloudTTSFullAccess 即通")
    raise TTSError(f"tts_unavailable：所有引擎都不可用（{joined[:200]}）")


def synth(text: str, *, scene: str = "", voice: str = "", engine: str = "") -> bytes:
    """合成文本 → mp3 **字节**（不落盘，纯函数，测试友好）。"""
    fd, tmp = tempfile.mkstemp(suffix=".mp3", prefix="echoes_tts_")
    os.close(fd)
    try:
        synth_to_file(text, tmp, scene=scene, voice=voice, engine=engine)
        with open(tmp, "rb") as f:
            return f.read()
    finally:
        try:
            os.remove(tmp)
        except OSError:
            pass


# ============================================================
# 五、对内 handler：给接口用的（会落统一存储）
# ============================================================
# 注意：本函数**不改** storage_api 的其它路由，只借用其统一存储层。
#      key 前缀 `clips/{actor}/tts/...`（KIND_TTS）——合成音也算"他名下的资产"。

def api_speak(*, actor_id: str, text: str, scene: str = "",
              voice: str = "", story_id: str = "", engine: str = "") -> dict:
    """
    ★采访/复述出声音的**唯一入口**（小龙虾等的那条通道）。

    入参：
      actor_id 谁在听（语音也走同一存储前缀，只由本人入库 §6.2.1）
      text     要念的话（interview_api 的问句 / interview_recap 的 recap_speech）
      scene    interview_host / recap / tip（选音色）
      voice    可选，edge 音色（覆盖 scene）
      engine   可选，强指定 tencent/edge（默认按兜底顺序）
      story_id 可选，关联故事（仅记录口径）

    返回 {ok, data:{media_url, key, engine, voice, text_spoken, bytes, scene}}

    失败 → 明确错误码：`tts_not_authorized` / `tts_unavailable` / `empty_text` /
           `missing_actor` / `storage_not_configured`。**绝不返回假 URL**。
    """
    import storage_api

    if not str(actor_id or "").strip():
        return storage_api.fail("不知道是谁在听（actor_id 必填）", "missing_actor")

    spoken = prepare_text(text)
    if not spoken:
        return storage_api.fail("没有可念的内容", "empty_text")

    try:
        st = storage_api.get_storage()
    except RuntimeError as e:
        return storage_api.fail(str(e), "storage_not_configured")

    fd, tmp = tempfile.mkstemp(suffix=".mp3", prefix="echoes_tts_")
    os.close(fd)
    try:
        try:
            info = synth_to_file(spoken, tmp, scene=scene, voice=voice, engine=engine)
        except TTSError as e:
            code = str(e).split("：", 1)[0].strip() or "tts_failed"
            return storage_api.fail(str(e), code)
        with open(tmp, "rb") as f:
            data = f.read()
    finally:
        try:
            os.remove(tmp)
        except OSError:
            pass

    key = storage_api.build_key(
        actor_id=actor_id, kind=storage_api.KIND_TTS, file_name="speech.mp3",
    )
    try:
        st.put_bytes(key=key, data=data)
    except Exception as e:
        return storage_api.fail(f"tts_store_failed：合成件入库失败（{e}）", "tts_store_failed")

    # public_url 在各后端返回**字符串**（本地=静态路径 / COS=签名 GET 地址）；
    # 防御性兼容：万一将来某后端返 {url:...} 也认。
    url = st.public_url(key=key)
    if isinstance(url, dict):
        url = url.get("url", "")

    return storage_api.ok({
        "media_url": url or "",
        "key": key,
        "engine": info["engine"],
        "voice": str(info["voice"]),
        "text_spoken": info["text_spoken"],
        "bytes": len(data),
        "scene": scene or "default",
        "story_id": story_id or "",
        "backend": getattr(st, "name", "unknown"),
    }, message="语音合成好了")


# ============================================================
# 六、命令行试听
# ============================================================

def main():
    if len(sys.argv) >= 2 and sys.argv[1] == "--status":
        r = tts_status(probe_tencent=True)
        print("available:", r["available"], "| engine:", r["engine"] or "(none)")
        for n in r["notes"]:
            print(" -", n)
        return 0 if r["available"] else 2

    if len(sys.argv) < 2:
        print('用法：python3 tts_api.py "要说的话" [场景]   |   python3 tts_api.py --status')
        return 1
    text = sys.argv[1]
    scene = sys.argv[2] if len(sys.argv) > 2 else "recap"
    root = os.path.expanduser("~/.echoes_media/tts")
    os.makedirs(root, exist_ok=True)
    out = os.path.join(root, "tts_cli_demo.mp3")
    try:
        info = synth_to_file(text, out, scene=scene)
    except TTSError as e:
        print("❌", e)
        return 3
    print(f"✅ 合成成功：{info['path']}（{info['bytes']} 字节，引擎 {info['engine']}，音色 {info['voice']}）")
    print(f"   实际念的：{info['text_spoken']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
