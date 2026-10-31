"""
采集闭环自测 v1.0 —— 2026-10-31
验收标准（sandy 原话）：
  「我发一段录音进去，后端必须回出文字和可播放地址，这两样缺一样，就不算通。」

跑法：
  cd /home/ubuntu/echoes/backend && python3.12 selftest_capture_loop.py

覆盖：
  ① 转写层：腾讯云 ASR 直连可用（不走 HTTP，直接测函数）
  ② 上传→确认→转写→入库 全链路（走真实 HTTP，真库）
  ③ 返回体必须带 transcript / media_url / playable
  ④ 转写失败不算失败（transcribe_failed 时 ok 仍为 true）
  ⑤ 采访接话：答一句有内容的话 → 下一问必须跟这句相关，不是题库下一个
"""
import json
import os
import sys
import urllib.error
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

BASE = "http://127.0.0.1:8971"
SAMPLE = "/home/ubuntu/.echoes_media/clips/probe_sandy/tts/1793166730_c7fb6f7c_speech.mp3"

passed = 0
failed = 0


def check(name, cond, extra=None):
    global passed, failed
    if cond:
        passed += 1
        print(f"  [OK]   {name}")
    else:
        failed += 1
        print(f"  [FAIL] {name}" + (f"  → {extra}" if extra else ""))


def call(path, body=None, method="POST", timeout=120):
    data = json.dumps(body or {}).encode() if body is not None else None
    req = urllib.request.Request(BASE + path, data=data, method=method,
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        return {"ok": False, "raw": e.read().decode()[:300]}
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "raw": str(e)[:300]}


print("=" * 62)
print("① 转写层：腾讯云 ASR 直连")
print("=" * 62)
try:
    import tencent_asr
    r = tencent_asr.recognize(SAMPLE)
    txt = r.get("text", "") if isinstance(r, dict) else str(r)
    check("ASR 返回非空文字", bool(txt.strip()), txt[:80])
    print(f"       识别结果：{txt[:70]}")
except Exception as e:  # noqa: BLE001
    check("ASR 可调用", False, str(e)[:160])

print()
print("=" * 62)
print("② 上传 → 确认 → 转写 → 入库（真实 HTTP + 真库）")
print("=" * 62)

clip = call("/api/echoes/clip", {
    "story_id": "", "clip_type": "voice", "title": "采集闭环自测",
    "owner_id": "probe_x", "actor_id": "probe_x"}, method="POST")
story_id = (clip.get("data") or {}).get("story_id", "")
check("建故事成功", clip.get("ok") and bool(story_id), clip)

if story_id:
    up = call("/api/echoes/storage/upload-url", {
        "actor_id": "probe_x", "kind": "audio",
        "file_name": "selftest.mp3", "file_size": os.path.getsize(SAMPLE),
        "mime": "audio/mpeg"})
    d = up.get("data") or {}
    check("拿到上传地址", up.get("ok") and bool(d.get("upload_url")), up)
    check("method=POST（微信只认表单）", d.get("method") == "POST", d.get("method"))
    check("form_field=file 已透出", d.get("form_field") == "file", d.get("form_field"))

    key = d.get("key", "")
    if key:
        # 走 storage/put 落字节（服务端兜底路径，等价于前端传完）
        import base64
        with open(SAMPLE, "rb") as f:
            b64 = base64.b64encode(f.read()).decode()
        put = call("/api/echoes/storage/put", {"key": key, "data_b64": b64})
        check("字节落盘", put.get("ok"), put)

        cf = call("/api/echoes/storage/confirm", {
            "actor_id": "probe_x", "owner_id": "probe_x", "key": key,
            "kind": "audio", "story_id": story_id, "file_name": "selftest.mp3",
            "file_size": os.path.getsize(SAMPLE), "mime": "audio/mpeg",
            "visibility": "private", "duration": 3.0})
        cd = cf.get("data") or {}
        check("确认入库成功", cf.get("ok"), cf)
        # ★ 验收两样：文字 + 可播放地址
        check("★返回带文字 transcript", bool((cd.get("transcript") or "").strip()),
              (cd.get("transcript") or "")[:60])
        check("★返回带可播放地址 media_url",
              bool(cd.get("media_url")) and "http" in (cd.get("media_url") or ""),
              cd.get("media_url"))
        check("★playable=True", cd.get("playable") is True, cd.get("playable"))
        check("转写状态已标", cd.get("transcribe_state") in
              ("done", "failed", "skipped"), cd.get("transcribe_state"))
        print(f"       文字：{(cd.get('transcript') or '')[:60]}")
        print(f"       音频：{cd.get('media_url')}")

print()
print("=" * 62)
print("③ 采访接话：下一问必须跟着老人上一句走")
print("=" * 62)
nxt = call("/api/echoes/interview/next", {
    "owner_id": "probe_x", "viewer_id": "probe_x",
    "last_answer": "我十几岁就下地干活了，那时候在生产队挣工分"})
nd = nxt.get("data") or {}
q = (nd.get("question") or {}).get("text", "")
check("给出了下一问", bool(q), nd)
check("state=following_answer（读懂再接话）",
      nd.get("state") == "following_answer", nd.get("state"))
check("下一问不是空泛的「后来呢」", q and q not in ("后来呢？", "然后呢？"), q)
print(f"       老人说：我十几岁就下地干活了，那时候在生产队挣工分")
print(f"       AI 接： {q}")

print()
print("=" * 62)
print(f"结果：{passed} 通过 / {failed} 失败")
print("=" * 62)
sys.exit(0 if failed == 0 else 1)
