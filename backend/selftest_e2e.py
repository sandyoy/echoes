#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
全链路端到端自测（第1期收口件）—— 往事可追忆
====================================================
为什么要有这一份：
  09-25~09-29 五套自测（20/34/44/42/37）都是**按模块**测的，
  没有人把「一个新用户从进小程序到看见自己的故事」这条完整链路串起来跑过。
  10-03 首次联调要的就是这条链路——前端点一步、后端走一步。
  本文件就是**把联调那天要走的路径，先在纯 Python 里跑一遍**，
  把接口之间的缝（id 口径、信封形状、字段名）提前找出来，
  免得 10-03 当天卡在「不知道调哪个 id」。

跑法：
  cd /home/ubuntu/echoes/backend && /usr/bin/python3 selftest_e2e.py
  （注意：不要用 .venv/bin/python —— 它是空壳，见 README_运行环境.md）

它不碰 memory_story.db（用内存库），可反复跑。

覆盖这条真实动线（对应前端 4 个页面）：
  [首页]      ① 新用户 wx.login → api_login → 拿到 user_id / 双界面 / 「有N篇提到我」
  [采集页]    ② 建一本书 → 5 类素材（文字/照片/语音/原声/视频）挂到**同一件事**
              ③ 反复取筐 → 顺序稳、条数对、原声必留
  [家人分享]  ④ 加家人（看整本）→ 家人登录后能看到全部素材
  [故事里的人]⑤ 加故事成员（只看这一篇）→ 看不到别的故事
  [待认领]    ⑥ 老人登记手机号 → 亲属用同手机号登录 → 自动认领生效
  [首页红点]  ⑦ 被提及的人登录 → 「有 N 篇提到了你」数字正确、不翻倍
"""

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from models import Base, Story, Clip, ClipType, SessionLocal
import login_api as L
import collect_api as C
import collect_av as AV
import claim_api as CL
import permissions as P

PASS = 0
FAIL = 0
FAILED_NAMES = []


def check(name, cond, extra=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"✅ {name}  {extra}")
    else:
        FAIL += 1
        FAILED_NAMES.append(name)
        print(f"❌ {name}  {extra}")


def section(title):
    print(f"\n--- {title} ---")


def fresh_db():
    """独立内存库，不碰 memory_story.db。"""
    eng = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(eng)
    return sessionmaker(bind=eng)()


def make_story(db, owner_id, title="我的前半生"):
    """建一本书（第1期没有 story 创建接口，直接落库；联调时由前端建书接口承担）。"""
    s = Story(id=P._new_id("story"), owner_id=owner_id, title=title)
    db.add(s)
    db.commit()
    db.refresh(s)
    return s


print("=" * 64)
print("全链路端到端自测（第1期 · 一条真实动线走到底）")
print("=" * 64)

db = fresh_db()

# ============================================================
# ① 首页：新用户登录
# ============================================================
section("① 首页｜新用户登录（api_login）")

login = L.api_login(db, code="wx_code_laoli", nick_name="老李", force_stub=True)
check("①1 登录信封 ok=True", login.get("ok") is True, str(login.get("code", "")))
d = login.get("data", {})
MY_ID = d.get("user_id") or d.get("profile", {}).get("user_id", "")
check("①2 拿到 user_id（前端此后所有请求都靠它）", bool(MY_ID), str(MY_ID))
check("①3 标记为新用户 is_new_user=True", d.get("is_new_user") is True, str(d.get("is_new_user")))
ui_mode = d.get("profile", {}).get("ui_mode", "")
check("①4 双界面默认 standard", ui_mode == "standard", ui_mode)

# 切大字版（老人最常用的第一步设置）
r_ui = L.api_set_ui_mode(db, user_id=MY_ID, ui_mode="大字版")
check("①5 切「大字版」成功（别名归一化）", r_ui.get("ok") is True, str(r_ui.get("code", "")))
prof = L.api_profile(db, user_id=MY_ID).get("data", {})
check("①6 profile 持久为 large", prof.get("ui_mode") == "large", str(prof.get("ui_mode")))

# ============================================================
# ② 采集页：建书 + 5 类素材挂同一件事
# ============================================================
section("② 采集页｜5 类素材挂到同一件事")

story = make_story(db, owner_id=MY_ID, title="1968年我下乡")
SID = story.id
check("②1 建书成功", bool(SID), SID)

r1 = C.api_add_text_clip(db, story_id=SID, owner_id=MY_ID, actor_id=MY_ID,
                         text="那年我十六岁，坐了三天的绿皮车到北大荒。", caption="出发")
check("②2 文字挂上", r1.get("ok") is True, str(r1.get("code", "")))

r2 = C.api_add_photo_clip(db, story_id=SID, owner_id=MY_ID, actor_id=MY_ID,
                          media_url="https://cdn.example.com/p1.jpg",
                          file_name="p1.jpg", file_size=204800, mime="image/jpeg",
                          caption="车站合影")
check("②3 照片挂上", r2.get("ok") is True, str(r2.get("code", "")))

r3 = AV.api_add_audio_clip(db, story_id=SID, owner_id=MY_ID, actor_id=MY_ID,
                           media_url="https://cdn.example.com/a1.m4a",
                           file_name="a1.m4a", file_size=102400, mime="audio/m4a",
                           duration=28.5, caption="口述", do_transcribe=True)
check("②4 语音挂上（转写可失败但不阻断）", r3.get("ok") is True, str(r3.get("code", "")))

r4 = AV.api_add_original_clip(db, story_id=SID, owner_id=MY_ID, actor_id=MY_ID,
                              media_url="https://cdn.example.com/o1.m4a",
                              file_name="o1.m4a", file_size=102400, mime="audio/m4a",
                              duration=12.0, caption="原声保留")
check("②5 原声挂上（不转写）", r4.get("ok") is True, str(r4.get("code", "")))

r5 = AV.api_add_video_clip(db, story_id=SID, owner_id=MY_ID, actor_id=MY_ID,
                           media_url="https://cdn.example.com/v1.mp4",
                           file_name="v1.mp4", file_size=3145728, mime="video/mp4",
                           duration=45.0, cover_url="https://cdn.example.com/v1_cov.jpg",
                           caption="老屋前的院子")
check("②6 视频挂上", r5.get("ok") is True, str(r5.get("code", "")))

# ============================================================
# ③ 取筐：顺序稳、条数对、原声必留
# ============================================================
section("③ 取筐｜一个筐里 5 件素材（api_list_clips）")

box = C.api_list_clips(db, story_id=SID, owner_id=MY_ID, viewer_id=MY_ID)
check("③1 取筐 ok=True", box.get("ok") is True, str(box.get("code", "")))
clips = box.get("data", {}).get("clips", [])
check("③2 一个筐 5 件（5类都挂在同一件事）", len(clips) == 5, f"实际 {len(clips)}")
orders = [c.get("sort_order") for c in clips]
check("③3 顺序按 sort_order 递增、无重复", orders == sorted(orders) and len(set(orders)) == 5, str(orders))
types = {c.get("clip_type") for c in clips}
check("③4 5 种类型齐（text/photo/audio/original/video）",
      types == {"text", "photo", "audio", "original", "video"}, str(sorted(types)))
audio_clip = [c for c in clips if c.get("clip_type") == "audio"]
check("③5 语音必须保留原声 keep_original_voice=True",
      bool(audio_clip) and audio_clip[0].get("keep_original_voice") is True,
      str(audio_clip[0].get("keep_original_voice") if audio_clip else "无语音"))

# 再取一次，确认稳定（前端下拉刷新/二次进页）
box2 = C.api_list_clips(db, story_id=SID, owner_id=MY_ID, viewer_id=MY_ID)
check("③6 二次取筐条数一致（幂等）",
      len(box2.get("data", {}).get("clips", [])) == 5)

# ============================================================
# ④ 家人：看整本（v3.0 §1.2 两维闸门：可见范围 × 公开/私有）
# ============================================================
# v3.0 起默认私有（只有提供人本人可见）。故先验证「私有默认挡住家人」，
# 再把 5 件设公开，验证「可见范围」这一维家人能看整本——两维都要过。
section("④ 家人｜默认私有挡住 → 公开后看得到整本")

_owner_box = C.api_list_clips(db, story_id=SID, owner_id=MY_ID, viewer_id=MY_ID)
_owner_clips = _owner_box.get("data", {}).get("clips", [])

PRIVATE_ID = _owner_clips[0]["clip_id"] if _owner_clips else ""
_pv = C.api_set_clip_visibility(db, clip_id=PRIVATE_ID, actor_id=MY_ID, visibility="private")
check("④0a 主人主动设为私有成功", _pv.get("ok") is True, str(_pv.get("code", "")))

# 把其余 4 件设为公开（保留一件私有，用于测「私有对家人不可见」）
for _c in _owner_clips[1:]:
    C.api_set_clip_visibility(db, clip_id=_c["clip_id"], actor_id=MY_ID, visibility="public")

FAMILY_ID = L.code2session("code_family", force_stub=True)["openid"]
P.add_family_member(db, owner_id=MY_ID, display_name="小芳", user_id=FAMILY_ID, relation="女儿")

fam_box = C.api_list_clips(db, story_id=SID, owner_id=MY_ID, viewer_id=FAMILY_ID)
fam_clips = fam_box.get("data", {}).get("clips", [])
check("④1 家人看得到【公开】的素材（4 件），私有那件被挡",
      fam_box.get("ok") is True and len(fam_clips) == 4,
      f"adult={len(fam_clips)}")
check("④2 私有素材对家人不可见（v3.0 §1.2：私有库给提到人也不看）",
      all(c.get("clip_id") != PRIVATE_ID for c in fam_clips),
      f"private_id={PRIVATE_ID}")

# 家人能添
story2 = make_story(db, owner_id=MY_ID, title="1980年返城")
fam_add = C.api_add_text_clip(db, story_id=story2.id, owner_id=MY_ID, actor_id=FAMILY_ID,
                              text="（女儿补记）爸那天特别高兴。")
check("④2 家人能往书里补内容（v2.4：能看就能添）", fam_add.get("ok") is True, str(fam_add.get("code", "")))

# ============================================================
# ⑤ 故事里的人：只看这一篇
# ============================================================
section("⑤ 故事里的成员｜只看被点名的那一篇")

MEMBER_ID = L.code2session("code_member", force_stub=True)["openid"]
P.add_story_member(db, owner_id=MY_ID, story_id=SID, display_name="老张", user_id=MEMBER_ID)

mem_box = C.api_list_clips(db, story_id=SID, owner_id=MY_ID, viewer_id=MEMBER_ID)
check("⑤1 故事成员看得到公开的素材（4 件，私有那件不给看）",
      mem_box.get("ok") is True and len(mem_box.get("data", {}).get("clips", [])) == 4,
      str(mem_box.get("code", "")))

other_box = C.api_list_clips(db, story_id=story2.id, owner_id=MY_ID, viewer_id=MEMBER_ID)
check("⑤2 故事成员看不到别的故事（应当被拒）", other_box.get("ok") is False,
      f"code={other_box.get('code')}")

# ============================================================
# ⑥ 待认领：登记手机号 → 亲属同号登录 → 自动认领
# ============================================================
section("⑥ 待认领｜手机号登记 → 亲属登录自动认领")

r_reg = CL.api_register_claim(db, owner_id=MY_ID, phone="138-0013-8000", display_name="老李")
check("⑥1 登记手机号（归一化 +86 横线）", r_reg.get("ok") is True, str(r_reg.get("code", "")))

KIN_ID = L.code2session("code_kin", force_stub=True)["openid"]
r_claim = CL.api_claim_on_login(db, user_id=KIN_ID, phone="+8613800138000")
check("⑥2 亲属用同手机号登录 → 自动认领成功", r_claim.get("ok") is True, str(r_claim.get("code", "")))
owners = r_claim.get("data", {}).get("owners", [])
check("⑥3 认领后拿到这本书的归属（owners 非空）", len(owners) >= 1, f"owners={len(owners)}")

kin_box = C.api_list_clips(db, story_id=SID, owner_id=MY_ID, viewer_id=KIN_ID)
check("⑥4 认领后能看这本书的【公开】素材（4 件，私有那件不给看）",
      kin_box.get("ok") is True and len(kin_box.get("data", {}).get("clips", [])) == 4)

# ============================================================
# ⑦ 首页红点：「有 N 篇提到了你」
# ============================================================
section("⑦ 首页红点｜被提及者登录 → 数字正确、不翻倍")

mentions = P.add_story_member(db, owner_id=MY_ID, story_id=SID,
                              display_name="老王", phone="13900139000")
MENTION_ID = L.code2session("code_mention", force_stub=True)["openid"]
P.add_story_member(db, owner_id=MY_ID, story_id=SID,
                   display_name="老王", user_id=MENTION_ID)

m1 = CL.api_mentioned(db, user_id=MENTION_ID)
n1 = m1.get("data", {}).get("count", m1.get("data", {}).get("count_stories", 0))
check("⑦1 「有 N 篇提到了你」能查到", m1.get("ok") is True, str(m1.get("data", {})))
check("⑦2 数字 = 1（只被这一篇提到）", n1 == 1, f"实际 {n1}")

m2 = CL.api_mentioned(db, user_id=MENTION_ID)
n2 = m2.get("data", {}).get("count", m2.get("data", {}).get("count_stories", 0))
check("⑦3 连查两次不翻倍（前端会反复拉）", n1 == n2 == 1, f"{n1} vs {n2}")

# ============================================================
# 汇总
# ============================================================
print("\n" + "=" * 64)
print(f"全链路自测结果：{PASS} / {PASS + FAIL} 通过")
if FAILED_NAMES:
    print("失败项：")
    for n in FAILED_NAMES:
        print(f"  ❌ {n}")
print("=" * 64)
sys.exit(0 if FAIL == 0 else 1)
