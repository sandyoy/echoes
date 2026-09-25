"""
往事可追忆 · 第1期数据底座自测（2026-09-26）

跑法（必须用 /usr/bin/python3，见文件末注释）：
    cd /home/ubuntu/echoes/backend && /usr/bin/python3 selftest_story_clip_perm.py

自测什么（真跑真查库，不是静态核验）：
  A. 素材挂故事：4 类素材挂到同一条故事，顺序对；挂到不存在的故事要报错
  B. 双权限：家人看整本 / 故事成员只看一篇 / 被提及者无需授权 / 移除后失效
"""
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# 用临时库跑，不污染真库
_tmp = tempfile.mktemp(suffix=".db")
os.environ["DATABASE_URL"] = f"sqlite:///{_tmp}"

from models import (  # noqa: E402
    SessionLocal, init_db, Story, Clip, Member,
    ClipType, GrantVia, ClaimStatus,
)
from permissions import (  # noqa: E402
    attach_clip, list_clips, add_family_member, add_story_member,
    can_view_story, can_add_clip, visible_stories, remove_member,
)

PASS, FAIL = [], []


def check(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    print(f"{'✅' if cond else '❌'} {name}" + (f"  [{detail}]" if detail else ""))


def main():
    init_db()
    db = SessionLocal()

    OWNER = "u_laoren"      # 李桂芳（老人）
    DAUGHTER = "u_nver"     # 小李（女儿）→ 家人
    OLDWANG = "u_wang"      # 老王（被提起的人）→ 被提及者
    STRANGER = "u_stranger"

    # 两条故事
    s1 = Story(id="s_1979", owner_id=OWNER, title="1979年那场大水",
               people_mentioned=[{"name": "老王", "user_id": OLDWANG}])
    s2 = Story(id="s_work", owner_id=OWNER, title="进厂当学徒")
    db.add_all([s1, s2]); db.commit()

    print("\n=== A. 素材挂故事 ===")
    c1 = attach_clip(db, story_id="s_1979", clip_type="text",
                     text="那年水漫到门槛", created_by=OWNER)
    check("A1 文字挂上故事", c1.id.startswith("clip_") and c1.sort_order == 0)

    c2 = attach_clip(db, story_id="s_1979", clip_type="audio",
                     media_url="/media/a1.m4a", media_duration=31.5,
                     transcript="那年水漫到门槛了", created_by=OWNER)
    check("A2 语音挂上故事且保留原声", c2.keep_original_voice is True and c2.clip_type == ClipType.AUDIO)
    check("A3 素材顺序自动续号", c2.sort_order == 1, f"sort_order={c2.sort_order}")

    c3 = attach_clip(db, story_id="s_1979", clip_type="photo",
                     media_url="/media/p1.jpg", caption="当年全家合影", created_by=DAUGHTER)
    c4 = attach_clip(db, story_id="s_1979", clip_type="video",
                     media_url="/media/v1.mp4", cover_url="/media/v1.cover.jpg", created_by=DAUGHTER)
    clips = list_clips(db, "s_1979")
    check("A4 四类素材同挂一条故事", len(clips) == 4, f"共{len(clips)}件")
    check("A5 取出时按顺序排列", [c.sort_order for c in clips] == [0, 1, 2, 3])

    try:
        attach_clip(db, story_id="s_not_exist", clip_type="text", text="x")
        check("A6 挂到不存在的故事要报错", False)
    except ValueError as e:
        check("A6 挂到不存在的故事要报错", True, str(e)[:24])

    print("\n=== B. 双权限 ===")
    fam = add_family_member(db, owner_id=OWNER, display_name="小李",
                            user_id=DAUGHTER, relation="女儿")
    check("B1 家人加进来 granted_via=FAMILY",
          fam.granted_via == GrantVia.FAMILY and fam.story_id is None)

    mem = add_story_member(db, owner_id=OWNER, story_id="s_1979",
                           display_name="老张", user_id="u_laozhang")
    check("B2 故事成员绑定单篇", mem.granted_via == GrantVia.STORY and mem.story_id == "s_1979")

    db.add(Member(id="mem_wang", owner_id=OWNER, user_id=OLDWANG,
                  display_name="老王", granted_via=GrantVia.STORY,
                  story_id="s_1979", claim_status=ClaimStatus.CLAIMED))
    db.commit()

    check("B3 家人看 s1（整本）", can_view_story(db, owner_id=OWNER, viewer_id=DAUGHTER, story_id="s_1979"))
    check("B4 家人看 s2（后续/其它篇也能看）", can_view_story(db, owner_id=OWNER, viewer_id=DAUGHTER, story_id="s_work"))
    check("B5 故事成员只能看绑定的 s1", can_view_story(db, owner_id=OWNER, viewer_id="u_laozhang", story_id="s_1979"))
    check("B6 故事成员看不了 s2", not can_view_story(db, owner_id=OWNER, viewer_id="u_laozhang", story_id="s_work"))
    check("B7 陌生人看不了", not can_view_story(db, owner_id=OWNER, viewer_id=STRANGER, story_id="s_1979"))
    check("B8 主人看自己全部", can_view_story(db, owner_id=OWNER, viewer_id=OWNER, story_id="s_work"))

    check("B9 被提及者无需授权看那一篇",
          can_view_story(db, owner_id=OWNER, viewer_id=OLDWANG, story_id="s_1979"))
    check("B10 被提及者看不了别的篇",
          not can_view_story(db, owner_id=OWNER, viewer_id=OLDWANG, story_id="s_work"))

    check("B11 能看就能添（看=写同一权限）",
          can_add_clip(db, owner_id=OWNER, viewer_id=DAUGHTER, story_id="s_work")
          and not can_add_clip(db, owner_id=OWNER, viewer_id=STRANGER, story_id="s_work"))

    fam_list = visible_stories(db, owner_id=OWNER, viewer_id=DAUGHTER)
    check("B12 家人首页看到整本(2篇)", len(fam_list) == 2, f"{len(fam_list)}篇")
    wang_list = visible_stories(db, owner_id=OWNER, viewer_id=OLDWANG)
    check("B13 被提及者首页只看到1篇", len(wang_list) == 1 and wang_list[0].id == "s_1979")

    ok = remove_member(db, fam.id)
    check("B14 移除家人后权限收回",
          ok and not can_view_story(db, owner_id=OWNER, viewer_id=DAUGHTER, story_id="s_1979"))

    db.close()
    print(f"\n{'='*46}\n通过 {len(PASS)} 项，失败 {len(FAIL)} 项")
    if FAIL:
        print("失败项：" + "、".join(FAIL))
    print("=" * 46)
    return 0 if not FAIL else 1


if __name__ == "__main__":
    sys.exit(main())
