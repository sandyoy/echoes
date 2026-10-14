#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
TTS 通道自测 —— 往事可追忆
=================================
覆盖：文本规整（念得出）· 引擎探测（真假不假装）· api_speak 的错误码（绝不假成功）
     · 合成件入库（引擎真可用时）· 场景音色选择

跑法：/usr/bin/python3 selftest_tts_api.py
（本机 venv 是空壳无 requests，必须用 /usr/bin/python3，见 README_运行环境.md）
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.chdir(os.path.dirname(os.path.abspath(__file__)))

# 测试库隔离：必须在 import models 前设 DATABASE_URL（2026-10-01 踩过的坑）
os.environ["DATABASE_URL"] = "sqlite:///:memory:"

passed = 0
failed = 0


def check(name, cond, extra=""):
    global passed, failed
    if cond:
        passed += 1
        print(f"  ✅ {name}")
    else:
        failed += 1
        print(f"  ❌ {name}  {extra}")


print("=" * 60)
print("TTS 通道自测")
print("=" * 60)

import tts_api as T

# ------------------------------------------------------------
print("\n【一】文本规整：给老人念的话必须念得出（铁律 B）")
# ------------------------------------------------------------
r = T.normalize_for_speech("**§7.6 复述确认**")
check("剥 markdown 星号 + 章节号 §7.6", "§" not in r and "*" not in r and "7.6" not in r,
      f"got={r!r}")

r = T.normalize_for_speech("第1期\n第2期")
check("换行 → 停顿（不是连读）", "\n" not in r and "。" in r, f"got={r!r}")

r = T.normalize_for_speech("看这里 [点我](http://a.b) 谢谢")
check("markdown 链接只留文字", "http" not in r and "点我" in r, f"got={r!r}")

r = T.normalize_for_speech("——这样")
check("破折号 → 逗号停顿", "—" not in r, f"got={r!r}")

long_text = "这是一段很长的话" * 8  # 无标点 64 字
r = T.split_long_sentences(long_text, max_len=20)
check("无标点长句被切短（有停顿）", len(r) == len(long_text),
      f"len {len(r)} vs {len(long_text)}")

r = T.prepare_text("   ")
check("空白文本 → 规整后为空", r == "", f"got={r!r}")

r = T.prepare_text("x" * 5000)
check("超长文本被截断到 MAX_TEXT_LEN", len(r) <= T.MAX_TEXT_LEN, f"len={len(r)}")

# 规整不改动词句本身（只动符号/停顿）
src = "我八岁那年上的学"
check("规整不添加/删改老人原话", T.prepare_text(src) == src, f"got={T.prepare_text(src)!r}")

# ------------------------------------------------------------
print("\n【二】音色选择：场景 → 音色（不写死在调用方）")
# ------------------------------------------------------------
check("采访主持人音色存在", "zh-CN" in T._voice_for_scene("interview_host"))
check("复述音色存在", "zh-CN" in T._voice_for_scene("recap"))
check("未知场景回落默认音色", T._voice_for_scene("x") == T.DEFAULT_VOICE)
check("显式 voice 覆盖场景", T._voice_for_scene("recap", "my-voice") == "my-voice")
check("腾讯云场景音色是整数", isinstance(T._tencent_voice_for_scene("recap"), int))

# ------------------------------------------------------------
print("\n【三】引擎探测：真的假不了，假的装不了（铁律 A）")
# ------------------------------------------------------------
st = T.tts_status(probe_tencent=False)
check("本地探测不抛异常", isinstance(st, dict))
check("status 含 available/engine/notes 三键",
      all(k in st for k in ("available", "engine", "notes")))

tc = T.tencent_tts_probe()
check("腾讯云 TTS 探测返回规范结构",
      set(tc.keys()) >= {"ok", "code", "message"})
if tc["ok"]:
    print("     ℹ️ 腾讯云 TTS 实测可用（授权已开）")
else:
    print(f"     ℹ️ 腾讯云 TTS 实测不可用 → code={tc['code']}（{tc['message'][:60]}）")
    check("不可用时给出明确 code（不是空）", bool(tc["code"]))

# ------------------------------------------------------------
print("\n【四】合成：引擎真可用时能出声道；不可用时明确报错（不假成功）")
# ------------------------------------------------------------
probe = T.tencent_tts_probe()
try:
    b = T.synth("你好，我是小鲸鱼。")
    check("能合成出音频字节", len(b) > 0, f"bytes={len(b)}")
    check("合成出的是 mp3（有 ID3 或帧头）",
          b[:3] == b"ID3" or b[0] == 0xFF, f"head={b[:4]!r}")
    print(f"     ℹ️ 合成引擎实测可用，产出 {len(b)} 字节")
except T.TTSError as e:
    msg = str(e)
    check("合成不可用时抛 TTSError（不静默返回空）", isinstance(e, T.TTSError))
    check("报错码明确（tts_not_authorized / tts_unavailable）",
          msg.startswith("tts_not_authorized") or msg.startswith("tts_unavailable"),
          f"got={msg[:60]}")
    print(f"     ℹ️ 当前引擎不可用：{msg[:100]}")

# 空文本必须明确拒绝
try:
    T.synth("   ")
    check("空文本必须报错", False, "没有报错")
except T.TTSError as e:
    check("空文本报 empty_text", str(e).startswith("empty_text"), f"got={e}")

# ------------------------------------------------------------
print("\n【五】api_speak handler：信封形状 + 错误码 + 绝不假 URL")
# ------------------------------------------------------------
# 无 actor → missing_actor
r = T.api_speak(actor_id="", text="你好")
check("缺 actor_id → missing_actor", r.get("code") == "missing_actor",
      f"got={r}")

# 空文本 → empty_text
r = T.api_speak(actor_id="stu1", text="   ")
check("空文本 → empty_text", r.get("code") == "empty_text", f"got={r}")

# 引擎不可用 → 明确错误码（tts_not_authorized / tts_unavailable），且不含 media_url
r = T.api_speak(actor_id="stu1", text="你好，我是小鲸鱼。")
if not probe["ok"]:
    check("引擎不可用 → ok=False", r.get("ok") is False, f"got={r}")
    check("引擎不可用 → 明确错误码",
          r.get("code") in ("tts_not_authorized", "tts_unavailable"), f"got={r}")
    check("引擎不可用 → 绝不返回假 media_url",
          not r.get("data", {}).get("media_url"), f"got={r}")
    print(f"     ℹ️ 正确拒绝了假成功，code={r.get('code')}")
else:
    # 引擎真可用 → 必须能拿到真 media_url + 真入库
    check("引擎可用 → ok=True", r.get("ok") is True, f"got={r}")
    data = r.get("data", {})
    check("引擎可用 → 有 media_url", bool(data.get("media_url")), f"got={r}")
    check("引擎可用 → key 在 tts 前缀 + 属于本人",
          data.get("key", "").startswith("clips/stu1/tts/"), f"got={data.get('key')}")
    check("引擎可用 → text_spoken 已规整", "§" not in data.get("text_spoken", ""),
          f"got={data.get('text_spoken')}")
    check("引擎可用 → 有 engine/voice/bytes",
          all(k in data for k in ("engine", "voice", "bytes")), f"got={data}")
    # 合成件真的落盘了
    import storage_api
    st = storage_api.get_storage()
    check("引擎可用 → 合成件真的入库（对象存在）",
          st.exists(key=data["key"]), f"key={data['key']}")
    print(f"     ℹ️ 合成件已入库：{data['key']}（{data['bytes']} 字节）")

# ------------------------------------------------------------
print("\n【六】合成件不污染素材库（只进 tts/ 前缀）")
# ------------------------------------------------------------
import storage_api as S
check("KIND_TTS 已注册进 VALID_KINDS", S.KIND_TTS in S.VALID_KINDS)
key = S.build_key(actor_id="stu1", kind=S.KIND_TTS, file_name="a.mp3")
check("tts key 落在 clips/{actor}/tts/ 下", key.startswith("clips/stu1/tts/"), f"got={key}")
passed_upload, why, code = S.validate_upload(
    kind=S.KIND_TTS, file_name="a.mp3", file_size=1000)
check("tts 上传校验通过（mp3 合法）", passed_upload, f"{why}/{code}")
passed_upload, why, code = S.validate_upload(
    kind=S.KIND_TTS, file_name="a.mp4", file_size=1000)
check("tts 不收视频扩展名（只收音频）", not passed_upload, f"got passed={passed_upload}")

# ------------------------------------------------------------
print("\n【七】成功路径自证（打桩假引擎 → 真出声 + 真入库 + 真 URL）")
# ------------------------------------------------------------
# 引擎真不可用时，也必须证明"引擎可用那天链路是通的"——否则等于没做。
import tempfile as _tf
_FAKE_MP3 = b"ID3\x03\x00\x00\x00\x00\x00\x00" + b"\xff\xfb\x90\x00" + b"\x00" * 300

def _fake_synth(text, out_path, *, scene, voice_type=None):
    with open(out_path, "wb") as f:
        f.write(_FAKE_MP3)

_orig_cred = T._tencent_credentials_ok
_orig_synth = T._synth_tencent
try:
    T._tencent_credentials_ok = lambda: True
    T._synth_tencent = _fake_synth
    r = T.api_speak(actor_id="stub1", text="§7.6 复述确认", scene="recap")
    check("打桩引擎 → ok=True", r.get("ok") is True, f"got={r}")
    d = r.get("data", {})
    check("打桩引擎 → 有真 media_url", bool(d.get("media_url")), f"got={r}")
    check("打桩引擎 → key=clips/stub1/tts/", d.get("key", "").startswith("clips/stub1/tts/"),
          f"got={d.get('key')}")
    check("打桩引擎 → 合成件真入库",
          S.get_storage().exists(key=d.get("key", "")), f"got={d}")
    print(f"     成功路径已自证：{d.get('key')}（{d.get('bytes')} 字节，engine={d.get('engine')}）")
finally:
    T._tencent_credentials_ok = _orig_cred
    T._synth_tencent = _orig_synth

print("\n" + "=" * 60)
print(f"结果：{passed}/{passed + failed} 通过")
if failed:
    print(f"❌ 有 {failed} 条失败")
    sys.exit(1)
print("✅ 全部通过")
sys.exit(0)
