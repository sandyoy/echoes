#!/usr/bin/env python3.12
"""provenance 自测（2026-10-10 新建，v3.0 §1.3「来路 + 公开/私有」全局接口预埋）

覆盖：
  ① 默认私有：采集时不传 visibility → 落库为 private（v3.0 §1.2 默认私有）
  ② provider_id 默认取 created_by（谁放的谁提供）；显式传则用显式值
  ③ source_type 默认 origin；显式 quote + ref_from_id/ref_author_name 落库
  ④ 公开/私有闸门 —— 单条素材可见性：
       私有素材：提供人本人可见；别人（含被提及者/家人）看不到
       公开素材：家人/故事成员按可见范围能看到
  ⑤ api_list_clips 读侧过滤：私有素材对非提供人不出现；对提供人出现
  ⑥ 主动动作：提供人可把私有改公开（api_set_clip_visibility），改后别人可见
  ⑦ 只有提供人本人能改公开/私有；非本人被拒
  ⑧ can_quote_clip：公开素材别人可引用；私有素材别人不可引用；自己永远可
  ⑨ 越权边界：看不到故事 → list_clips 直接 no_permission；不泄露存在性
  ⑩ 全文回归：文字/照片两类 handler 均落新字段
"""
import sys, os, uuid
sys.path.insert(0, "/home/ubuntu/echoes/backend")

TEST_DB = f"/tmp/echoes_selftest_prov_{uuid.uuid4().hex[:8]}.db"
# ⚠️ 铁律（10-01 踩过）：库地址取自 DATABASE_URL，必须在 import models 之前设。
os.environ["DATABASE_URL"] = f"sqlite:///{TEST_DB}"

import models
from models import (SessionLocal, init_db, Story, Clip, ClipType,
                    Visibility, SourceType, GrantVia)
import collect_api as C
import permissions as P

init_db()
db = SessionLocal()

passed = 0; failed = 0; fails = []

def check(name, cond, detail=""):
    global passed, failed
    if cond:
        passed += 1; print(f"  [PASS] {name}")
    else:
        failed += 1; fails.append(name); print(f"  [FAIL] {name}  {detail}")

OWNER = "openid_prov_owner"      # 老人（书的主人）
DAUGHTER = "openid_prov_daughter"  # 家人（看整本）
MEMBER = "openid_prov_member"    # 故事成员（只看一篇）
STRANGER = "openid_prov_stranger"


def mk_story(story_id, *, owner=OWNER, title="", summary=""):
    s = Story(id=story_id, owner_id=owner, title=title, summary=summary)
    db.add(s); db.commit(); db.refresh(s)
    return s


def add_family(display="女儿"):
    m = P.add_family_member(db, owner_id=OWNER, display_name=display,
                            phone="", user_id=None)
    if isinstance(m, tuple):
        m = m[0]
    return m


print("=== provenance 自测（v3.0 §1.3）===")

# ---- 建书 + 一条故事 ----
SID = "story_prov_001"
mk_story(SID, title="1979年那场大水")

# ---- ① 默认私有 ----
r = C.api_add_text_clip(db, story_id=SID, owner_id=OWNER, actor_id=OWNER,
                        text="那年发大水，我们全家搬到了山上。")
check("① 采集默认私有", r["ok"] and r["data"]["visibility"] == "private", r)
check("①b provider_id 默认=created_by", r["data"]["provider_id"] == OWNER, r)
check("①c source_type 默认 origin", r["data"]["source_type"] == "origin", r)
clip_default_id = r["data"]["clip_id"]

# ---- ② / ③ 显式来路 + 引用 ----
r2 = C.api_add_text_clip(db, story_id=SID, owner_id=OWNER, actor_id=OWNER,
                         text="（引用邻居张大叔的话）我家屋顶被水掀了。",
                         visibility="public", source_type="quote",
                         ref_from_id=clip_default_id, ref_author_name="张大叔")
check("② 显式 public 落库", r2["ok"] and r2["data"]["visibility"] == "public", r2)
check("③ source_type=quote 落库", r2["data"]["source_type"] == "quote", r2)
c2 = db.get(Clip, r2["data"]["clip_id"])
check("③b 引用出处落库", c2.ref_from_id == clip_default_id and c2.ref_author_name == "张大叔",
      f"ref_from={c2.ref_from_id} author={c2.ref_author_name}")

# ---- 非法 source_type 被拒 ----
r_bad = C.api_add_text_clip(db, story_id=SID, owner_id=OWNER, actor_id=OWNER,
                            text="x", source_type="copy")
check("③c 非法 source_type 被拒", (not r_bad["ok"]) and r_bad.get("code") == "bad_source_type", r_bad)

# ---- ④ 公开/私有闸门（单条）----
# 私有素材：提供人本人可见；别人不可见
c_priv = db.get(Clip, clip_default_id)
check("④a 私有素材 提供人本人可见", P.can_show_clip(db, clip=c_priv, viewer_id=OWNER))
check("④b 私有素材 家人看不到", not P.can_show_clip(db, clip=c_priv, viewer_id=DAUGHTER))
check("④c 私有素材 陌生人看不到", not P.can_show_clip(db, clip=c_priv, viewer_id=STRANGER))
# 公开素材：非提供人可过公开闸门（可见范围另由 can_view_story 判）
check("④d 公开素材 非提供人过公开闸门", P.can_show_clip(db, clip=c2, viewer_id=DAUGHTER))

# ---- ⑤ api_list_clips 读侧过滤 ----
# 让 DAUGHTER 成为家人（看整本）——直接建 Member(FAMILY, 已认领)
db.add(models.Member(id="mem_prov_daughter", owner_id=OWNER, user_id=DAUGHTER,
                     phone="", display_name="女儿",
                     granted_via=GrantVia.FAMILY,
                     claim_status=models.ClaimStatus.CLAIMED,
                     story_id=None))
db.commit()

r_owner = C.api_list_clips(db, story_id=SID, owner_id=OWNER, viewer_id=OWNER)
check("⑤a 主人看到全部 2 条", r_owner["ok"] and r_owner["data"]["count"] == 2, r_owner)

r_daughter = C.api_list_clips(db, story_id=SID, owner_id=OWNER, viewer_id=DAUGHTER)
check("⑤b 家人只看到公开的 1 条", r_daughter["ok"] and r_daughter["data"]["count"] == 1, r_daughter)
if r_daughter["ok"] and r_daughter["data"]["clips"]:
    check("⑤c 家人看到的是那条公开素材",
          r_daughter["data"]["clips"][0]["visibility"] == "public", r_daughter["data"]["clips"])

# ---- ⑥ 主动动作：私有改公开 ----
r_set = C.api_set_clip_visibility(db, clip_id=clip_default_id, actor_id=OWNER, visibility="public")
check("⑥a 提供人可把私有改公开", r_set["ok"] and r_set["data"]["visibility"] == "public", r_set)
r_daughter2 = C.api_list_clips(db, story_id=SID, owner_id=OWNER, viewer_id=DAUGHTER)
check("⑥b 改公开后家人看到 2 条", r_daughter2["ok"] and r_daughter2["data"]["count"] == 2, r_daughter2)

# 收回为私有
r_set2 = C.api_set_clip_visibility(db, clip_id=clip_default_id, actor_id=OWNER, visibility="private")
check("⑥c 可收回为私有", r_set2["ok"] and r_set2["data"]["visibility"] == "private", r_set2)

# ---- ⑦ 只有提供人本人能改 ----
r_set3 = C.api_set_clip_visibility(db, clip_id=clip_default_id, actor_id=DAUGHTER, visibility="public")
check("⑦a 非提供人改被拒", (not r_set3["ok"]) and r_set3.get("code") == "no_permission", r_set3)
r_set4 = C.api_set_clip_visibility(db, clip_id=clip_default_id, actor_id=OWNER, visibility="secret")
check("⑦b 非法 visibility 被拒", (not r_set4["ok"]) and r_set4.get("code") == "bad_visibility", r_set4)

# ---- ⑧ can_quote_clip ----
c_pub = db.get(Clip, c2.id)   # 公开素材
check("⑧a 公开素材别人可引用", P.can_quote_clip(db, clip=c_pub, viewer_id=DAUGHTER))
c_pri = db.get(Clip, clip_default_id)  # 已收回私有
check("⑧b 私有素材别人不可引用", not P.can_quote_clip(db, clip=c_pri, viewer_id=DAUGHTER))
check("⑧c 自己无论公私都可引用（私有）", P.can_quote_clip(db, clip=c_pri, viewer_id=OWNER))

# ---- ⑨ 越权边界：看不到故事 ----
r_stranger = C.api_list_clips(db, story_id=SID, owner_id=OWNER, viewer_id=STRANGER)
check("⑨ 陌生人看不到故事(no_permission)", (not r_stranger["ok"]) and r_stranger.get("code") == "no_permission", r_stranger)

# ---- ⑩ 照片 handler 也落新字段 ----
r_photo = C.api_add_photo_clip(db, story_id=SID, owner_id=OWNER, actor_id=OWNER,
                               media_url="http://x/p.jpg", file_name="p.jpg",
                               file_size=1024, mime="image/jpeg",
                               visibility="public")
check("⑩ 照片 handler 落 visibility", r_photo["ok"] and r_photo["data"]["visibility"] == "public", r_photo)
check("⑩b 照片 handler 落 provider_id", r_photo["data"]["provider_id"] == OWNER, r_photo)

# ============================================================
print(f"\n结果：{passed}/{passed+failed} 通过")
if fails:
    print("失败项：", fails)
    sys.exit(1)
print("EXIT=0")
sys.exit(0)
