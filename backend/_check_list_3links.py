"""验证 clip/list 三链路字段：transcript / media_url / playable 真实产出。"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
import models
from models import Base
import collect_api

engine = create_engine("sqlite:///:memory:")
Base.metadata.create_all(engine)
db = sessionmaker(bind=engine)()

# 建故事 + 语音/原声/照片各一条
import uuid
from models import Clip, Story, ClipType, Visibility

sid = "s_" + uuid.uuid4().hex[:8]
owner = "u_owner"
st = models.make_story if False else Story(id=sid, owner_id=owner, title="测试")
db.add(st)
db.commit()

def add(t, transcript="", media="", dur=0):
    c = Clip(
        id="c_" + uuid.uuid4().hex[:8], story_id=sid,
        created_by=owner, provider_id=owner, clip_type=t,
        transcript=transcript, media_url=media, media_duration=dur,
        keep_original_voice=True, visibility=Visibility.PUBLIC, sort_order=0,
    )
    db.add(c); db.commit(); return c

add(ClipType.AUDIO, transcript="我小时候住在河边上", media="https://x/a.mp3", dur=12.5)
add(ClipType.ORIGINAL, transcript="", media="https://x/b.mp3", dur=8)
add(ClipType.PHOTO, transcript="", media="https://x/c.jpg")

r = collect_api.api_list_clips(db, story_id=sid, owner_id=owner, viewer_id=owner)
print("ok =", r.get("ok"), "| count =", (r.get("data") or {}).get("count"))
print()
ok = True
for c in (r.get("data") or {}).get("clips", []):
    print(f"  type={c['clip_type']:<9} transcript={c['transcript']!r:<26} "
          f"playable={c['playable']!s:<5} dur={c['media_duration']}")

print("\n--- 断言 ---")
clips = (r.get("data") or {}).get("clips", [])
by = {c["clip_type"]: c for c in clips}

def chk(name, cond):
    global ok
    print(("  PASS  " if cond else "  FAIL  ") + name)
    if not cond: ok = False

chk("语音带 transcript 上屏", by["audio"]["transcript"] == "我小时候住在河边上")
chk("语音 playable=True（能画音频条）", by["audio"]["playable"] is True)
chk("语音时长给到前端", by["audio"]["media_duration"] == 12.5)
chk("原声 playable=True（原声也要能回放）", by["original"]["playable"] is True)
chk("照片 playable=False（不该画播放条）", by["photo"]["playable"] is False)

print("\n结论:", "ALL PASS" if ok else "HAS FAILURE")
sys.exit(0 if ok else 1)
