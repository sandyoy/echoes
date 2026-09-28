"""
往事可追忆 - 语音/原声/视频采集接口 自测（09-28）
运行：cd /home/ubuntu/echoes/backend && /usr/bin/python3 selftest_collect_av.py

铁律（v2.4 第十四节）：静态核验 ≠ 通过。本脚本**真跑**每个 handler
（真建库、真落库、真读回），全过才算"接口能调通"。

覆盖：
  1. validate_audio / validate_video  --- 格式/空文件/超限/时长，纯函数
  2. api_add_audio_clip               --- 原声必落库；转写失败不阻断；权限拦截
  3. api_add_original_clip            --- 原声不转写
  4. api_add_video_clip               --- 视频 + 封面兜底
  5. api_transcribe_clip              --- 幂等；原声不可转写；非语音拒绝
  6. 与已有接口回归：混合素材同筐顺序、list_clips 能取回
"""

import os
import sys
import uuid
import traceback

# 独立测试库，绝不碰 memory_story.db（与 selftest_collect_api.py 同法）
TEST_DB = os.path.join("/tmp", f"echoes_selftest_av_{uuid.uuid4().hex[:8]}.db")
os.environ["DATABASE_URL"] = f"sqlite:///{TEST_DB}"

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from models import init_db, SessionLocal, Story, Clip, ClipType   # noqa: E402
from permissions import add_family_member, add_story_member       # noqa: E402
import collect_av as av                                           # noqa: E402
from collect_api import api_add_text_clip, api_list_clips         # noqa: E402

PASS = 0
FAIL = 0
FAILED_NAMES = []


def check(label, cond, extra=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"✅ {label}" + (f"  [{extra}]" if extra else ""))
    else:
        FAIL += 1
        FAILED_NAMES.append(label)
        print(f"❌ {label}" + (f"  [{extra}]" if extra else ""))


def new_story(db, story_id, owner_id="u_owner"):
    s = Story(id=story_id, owner_id=owner_id, title=f"故事{story_id}")
    db.add(s)
    db.commit()
    return s


def main():
    init_db()
    db = SessionLocal()

    OWNER = "u_owner"
    FAMILY = "u_daughter"
    INNER = "u_uncle"
    STRANGER = "u_stranger"

    # ============ 1. 纯校验函数 ============
    print("=== 1. validate_audio / validate_video ===")
    p, w, h = av.validate_audio(file_name="a.mp3", file_size=1024, duration=10)
    check("正常 mp3 通过", p and not w, w)
    p, w, h = av.validate_audio(file_name="a.txt", file_size=1024)
    check("非音频格式被拒且有中文原因", (not p) and ("不支持" in w), w)
    p, w, h = av.validate_audio(file_name="a.mp3", file_size=0)
    check("空文件被拒", (not p) and ("空" in w), w)
    p, w, h = av.validate_audio(file_name="a.mp3", file_size=av.MAX_AUDIO_BYTES + 1)
    check("超 20MB 被拒", (not p) and ("太大" in w), w)
    p, w, h = av.validate_audio(file_name="a.mp3", file_size=1024, duration=0.2)
    check("过短语音被拒（误触）", (not p) and ("太短" in w), w)
    p, w, h = av.validate_audio(file_name="a.mp3", file_size=1024,
                                duration=av.MAX_AUDIO_SECONDS + 60)
    check("过长语音=通过并给分段提示", p and bool(h), h)
    p, w, h = av.validate_audio(file_name="", file_size=1024, mime="audio/mpeg")
    check("无扩展名但 mime 正确 → 通过", p, w)
    p, w, h = av.validate_audio(file_name="", file_size=1024, mime="")
    check("无扩展名也无 mime → 拒", not p, w)

    p, w, h = av.validate_video(file_name="v.mp4", file_size=1024, duration=30)
    check("正常 mp4 通过", p and not w, w)
    p, w, h = av.validate_video(file_name="v.txt", file_size=1024)
    check("非视频格式被拒", (not p) and ("不支持" in w), w)
    p, w, h = av.validate_video(file_name="v.mp4", file_size=av.MAX_VIDEO_BYTES + 1)
    check("超 200MB 被拒", (not p) and ("太大" in w), w)
    p, w, h = av.validate_video(file_name="v.mp4", file_size=1024,
                                duration=av.MAX_VIDEO_SECONDS + 60)
    check("过长视频=通过并给提示", p and bool(h), h)

    # ============ 2. 语音 handler ============
    print("\n=== 2. api_add_audio_clip（语音，保留原声）===")
    st = new_story(db, "s_audio", OWNER)

    r = av.api_add_audio_clip(db, story_id=st.id, owner_id=OWNER, actor_id=OWNER,
                              media_url="", file_name="a.mp3", file_size=100)
    check("无 media_url 被拒（原声必须留）",
          (not r["ok"]) and r["code"] == "missing_media_url")

    r = av.api_add_audio_clip(db, story_id=st.id, owner_id=OWNER, actor_id=OWNER,
                              media_url="http://x/a.mp3", file_name="a.txt", file_size=100)
    check("格式非法被拒（invalid_audio）",
          (not r["ok"]) and r["code"] == "invalid_audio")

    r = av.api_add_audio_clip(db, story_id="s_none", owner_id=OWNER, actor_id=OWNER,
                              media_url="http://x/a.mp3", file_name="a.mp3", file_size=100, duration=5)
    check("故事不存在 → attach_failed 不抛穿", (not r["ok"]) and r["code"] == "attach_failed", str(r.get("error")))

    # 无 audio_path → 转写跳过，但原声必须落库
    r = av.api_add_audio_clip(db, story_id="s_audio", owner_id=OWNER, actor_id=OWNER,
                              media_url="http://cdn/a1.mp3", file_name="a1.mp3",
                              file_size=5000, duration=12.0, caption="奶奶讲小时候")
    check("合法语音 ok", r["ok"], str(r.get("error", "")))
    check("原声地址已落库", r["ok"] and r["data"]["media_url"] == "http://cdn/a1.mp3")
    check("keep_original_voice=True（铁律）",
          r["ok"] and r["data"]["keep_original_voice"] is True)
    check("无音频文件时 transcribed=False 且给可读 notice",
          r["ok"] and r["data"]["transcribed"] is False and bool(r.get("notice")),
          str(r.get("notice"))[:60])
    audio_clip_id = r["data"]["clip_id"] if r["ok"] else ""
    c = db.get(Clip, audio_clip_id) if audio_clip_id else None
    check("落库查得到，且类型=AUDIO", c is not None and c.clip_type == ClipType.AUDIO)

    r = av.api_add_audio_clip(db, story_id="s_audio", owner_id=OWNER, actor_id=OWNER,
                              media_url="http://cdn/a2.mp3", file_name="a2.mp3",
                              file_size=5000, duration=av.MAX_AUDIO_SECONDS + 120)
    check("超长语音仍收下，但带分段提示", r["ok"] and bool(r.get("notice")),
          str(r.get("notice"))[:60])

    # 权限：外人不能添
    r = av.api_add_audio_clip(db, story_id="s_audio", owner_id=OWNER, actor_id=STRANGER,
                              media_url="http://cdn/x.mp3", file_name="x.mp3", file_size=100, duration=5)
    check("无权限者被拒（no_permission）",
          (not r["ok"]) and r["code"] == "no_permission", str(r.get("error")))

    # 家人（全本）可添
    add_family_member(db, owner_id=OWNER, user_id=FAMILY, display_name="女儿")
    r = av.api_add_audio_clip(db, story_id="s_audio", owner_id=OWNER, actor_id=FAMILY,
                              media_url="http://cdn/f.mp3", file_name="f.mp3", file_size=200, duration=6)
    check("家人可添语音", r["ok"], str(r.get("error", "")))

    # 故事成员（单篇）可添
    add_story_member(db, owner_id=OWNER, story_id="s_audio", user_id=INNER, display_name="二叔")
    r = av.api_add_audio_clip(db, story_id="s_audio", owner_id=OWNER, actor_id=INNER,
                              media_url="http://cdn/m.mp3", file_name="m.mp3", file_size=200, duration=6)
    check("故事成员可添语音", r["ok"], str(r.get("error", "")))

    # ============ 3. 原声 handler ============
    print("\n=== 3. api_add_original_clip（原声，不转写）===")
    r = av.api_add_original_clip(db, story_id="s_audio", owner_id=OWNER, actor_id=OWNER,
                                 media_url="http://cdn/o1.mp3", file_name="o1.mp3",
                                 file_size=8000, duration=20.0, caption="原声：方言版")
    check("原声 ok", r["ok"], str(r.get("error", "")))
    oid = r["data"]["clip_id"] if r["ok"] else ""
    check("原声类型=ORIGINAL", db.get(Clip, oid).clip_type == ClipType.ORIGINAL if oid else False)
    check("原声 keep_original_voice=True", r["ok"] and r["data"]["keep_original_voice"] is True)
    check("原声不返回 transcript（按设计不转写）", "transcript" not in r["data"])

    r = av.api_add_original_clip(db, story_id="s_audio", owner_id=OWNER, actor_id=OWNER,
                                 media_url="", file_name="o2.mp3", file_size=100)
    check("原声无 media_url 被拒", (not r["ok"]) and r["code"] == "missing_media_url")

    # ============ 4. 视频 handler ============
    print("\n=== 4. api_add_video_clip ===")
    r = av.api_add_video_clip(db, story_id="s_audio", owner_id=OWNER, actor_id=OWNER,
                              media_url="http://cdn/v1.mp4", file_name="v1.mp4",
                              file_size=1024 * 1024, duration=45.0, cover_url="http://cdn/v1.jpg")
    check("视频 ok", r["ok"], str(r.get("error", "")))
    check("封面用传入的", r["ok"] and r["data"]["cover_url"] == "http://cdn/v1.jpg")
    r = av.api_add_video_clip(db, story_id="s_audio", owner_id=OWNER, actor_id=OWNER,
                              media_url="http://cdn/v2.mp4", file_name="v2.mp4",
                              file_size=1024, duration=10.0)
    check("无封面时兜底用视频地址", r["ok"] and r["data"]["cover_url"] == "http://cdn/v2.mp4")
    r = av.api_add_video_clip(db, story_id="s_audio", owner_id=OWNER, actor_id=STRANGER,
                              media_url="http://cdn/v3.mp4", file_name="v3.mp4", file_size=1024)
    check("无权限者不能传视频", (not r["ok"]) and r["code"] == "no_permission")

    # ============ 5. 补转写 ============
    print("\n=== 5. api_transcribe_clip（补转写）===")
    r = av.api_transcribe_clip(db, clip_id=oid, owner_id=OWNER, viewer_id=OWNER)
    check("原声素材不可转写（按设计）",
          (not r["ok"]) and r["code"] == "original_not_transcribable")

    r = av.api_transcribe_clip(db, clip_id="nonexistent", owner_id=OWNER, viewer_id=OWNER)
    check("不存在的素材被拒", (not r["ok"]) and r["code"] == "clip_not_found")

    r = av.api_transcribe_clip(db, clip_id=audio_clip_id, owner_id=OWNER, viewer_id=STRANGER)
    check("看不了故事的人不能补转写",
          (not r["ok"]) and r["code"] == "no_permission")

    r = av.api_transcribe_clip(db, clip_id=audio_clip_id, owner_id=OWNER, viewer_id=OWNER)
    check("无音频文件时补转写=明确失败+可读中文（不假装成功）",
          (not r["ok"]) and r["code"] == "transcribe_failed", str(r.get("error"))[:70])

    c = db.get(Clip, audio_clip_id)
    c.transcript = "奶奶说：那时候家里穷……"
    db.commit()
    r = av.api_transcribe_clip(db, clip_id=audio_clip_id, owner_id=OWNER, viewer_id=OWNER)
    check("已有文字时幂等返回（不重跑）",
          r["ok"] and r["data"]["transcript_source"] == "cached", str(r.get("error")))

    # ============ 6. 混合素材回归 ============
    print("\n=== 6. 混合素材回归（与 collect_api 同筐）===")
    new_story(db, "s_mix", OWNER)
    api_add_text_clip(db, story_id="s_mix", owner_id=OWNER, actor_id=OWNER, text="第一件：文字")
    av.api_add_audio_clip(db, story_id="s_mix", owner_id=OWNER, actor_id=OWNER,
                          media_url="http://cdn/mix1.mp3", file_name="mix1.mp3", file_size=100, duration=8)
    av.api_add_original_clip(db, story_id="s_mix", owner_id=OWNER, actor_id=OWNER,
                             media_url="http://cdn/mix2.mp3", file_name="mix2.mp3", file_size=100, duration=8)
    av.api_add_video_clip(db, story_id="s_mix", owner_id=OWNER, actor_id=OWNER,
                          media_url="http://cdn/mix3.mp4", file_name="mix3.mp4", file_size=100, duration=8)
    r = api_list_clips(db, story_id="s_mix", owner_id=OWNER, viewer_id=OWNER)
    check("list_clips 取回 4 件", r["ok"] and r["data"]["count"] == 4,
          str(r.get("data", {}).get("count")))
    check("四类各1件",
          r["ok"] and set(r["data"]["count_by_type"].keys()) == {"text", "audio", "original", "video"},
          str(r["data"].get("count_by_type")))
    orders = [c["sort_order"] for c in r["data"]["clips"]]
    check("顺序递增且连续", orders == sorted(orders) and len(set(orders)) == 4, str(orders))
    check("语音保留原声字段在 list 里可见",
          all("keep_original_voice" in c for c in r["data"]["clips"]))

    print("\n" + "=" * 56)
    print(f"通过 {PASS} / 共 {PASS + FAIL}")
    if FAILED_NAMES:
        print("失败项：")
        for n in FAILED_NAMES:
            print("   -", n)
    print("=" * 56)
    try:
        os.remove(TEST_DB)
    except OSError:
        pass
    return 0 if FAIL == 0 else 1


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:
        traceback.print_exc()
        sys.exit(2)
