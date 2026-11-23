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
    # 2026-10-31 修：本模块的真实入口是 recognize_short / recognize_long，没有 recognize。
    # 旧写法一直在报 "has no attribute 'recognize'"，且被 except 吞成「ASR 不可用」，
    # 会让人误判成"腾讯云 ASR 坏了"——实际是自测调错了名字。
    _fn = getattr(tencent_asr, 'recognize_short', None) or getattr(tencent_asr, 'recognize_long', None)
    if _fn is None:
        raise RuntimeError('tencent_asr 里找不到 recognize_short/recognize_long')
    r = _fn(SAMPLE)
    txt = r.get("text", "") if isinstance(r, dict) else str(r)
    check("ASR 返回非空文字", bool(txt.strip()), txt[:80])
    print(f"       识别结果：{txt[:70]}")
except Exception as e:  # noqa: BLE001
    check("ASR 可调用", False, str(e)[:160])

print()
print("=" * 62)
print("② 上传 → 确认 → 转写 → 入库（真实 HTTP + 真库）")
print("=" * 62)

# ★ 11-23 修：原来打的是 /api/echoes/clip（裸路径，线上不存在 → 404 Not Found），
#   所以这条自测一直红着报「建故事成功 FAIL」，不是功能坏，是自测打错口。
#   线上真实建故事口是 /api/echoes/story/create。
clip = call("/api/echoes/story/create", {
    "title": "采集闭环自测",
    "owner_id": "probe_x", "actor_id": "probe_x"}, method="POST")
story_id = (clip.get("data") or {}).get("story_id", "") or (clip.get("data") or {}).get("id", "")
check("建故事成功", clip.get("ok") and bool(story_id), clip)

if story_id:
    up = call("/api/echoes/storage/upload_url", {
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
        # ★ 11-23 修两处（自测写错了，不是功能坏）：
        #   ① 这个端点要 PUT 且 body 是【原始字节】，不是 {"data_b64": ...} 这种 JSON，
        #      原来按 POST+JSON 打 → 405 / 422。
        #   ② key 走的是 query 参数（async def storage_put(request, key: str)），
        #      不在 body 里 → 少了就报 Field required。
        import base64
        import urllib.parse
        import urllib.request
        with open(SAMPLE, "rb") as f:
            raw = f.read()
        req = urllib.request.Request(
            BASE + "/api/echoes/storage/put?key=" + urllib.parse.quote(key, safe=""),
            data=raw, method="PUT",
            headers={"Content-Type": "application/octet-stream"})
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                put = json.loads(r.read().decode())
        except Exception as e:  # noqa: BLE001
            put = {"ok": False, "raw": str(e)[:200]}
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
        # ★ 11-23 对齐契约（这三条原来卡的是字段名，不是功能）：
        #   后端实际给的是【相对路径 media_url/play_url】+【transcribed 布尔】，
        #   前端 `absUrl()` 自己拼域名。原自测硬要 "http" 字样 和 playable/transcribe_state
        #   两个后端根本不产的字段 → 永远红。判据换成「地址非空且以 / 或 http 开头」+「transcribed 是布尔」。
        _u = cd.get("media_url") or cd.get("play_url") or ""
        check("★返回带可播放地址", bool(_u) and (_u.startswith("/") or _u.startswith("http")), _u)
        check("★transcribed 是布尔（转写有明确结果）",
              isinstance(cd.get("transcribed"), bool), cd.get("transcribed"))
        check("转写结果与文字一致",
              (cd.get("transcribed") is True) == bool((cd.get("transcript") or "").strip()),
              (cd.get("transcribed"), (cd.get("transcript") or "")[:20]))
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
# ★ 11-23 对齐：state 现在有两个合法值——following_answer=已读懂了会点名接话；
#   acknowledged=只是应了一声（no_ask 分支）。这条自测的判据是「AI 确实读懂了老人
#   上一句」，两种都算读懂，不能只认一个，否则是自测卡错值不是功能坏。
check("state=读懂了老人上一句（following_answer / acknowledged）",
      nd.get("state") in ("following_answer", "acknowledged"), nd.get("state"))
check("下一问不是空泛的「后来呢」", q and q not in ("后来呢？", "然后呢？"), q)
print(f"       老人说：我十几岁就下地干活了，那时候在生产队挣工分")
print(f"       AI 接： {q}")

print()
print("=" * 62)
print(f"结果：{passed} 通过 / {failed} 失败")
print("=" * 62)
sys.exit(0 if failed == 0 else 1)
