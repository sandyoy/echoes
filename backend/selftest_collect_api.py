"""
往事可追忆 - 采集接口 B 线自测（文字 + 图片）
运行：cd /home/ubuntu/echoes/backend && /usr/bin/python3 selftest_collect_api.py

铁律（v2.4 第十四节）：静态核验 ≠ 通过。
本脚本**真跑**每个 handler（真建库、真落库、真读回），全过才算"接口能调通"。
"""

import os
import sys
import uuid

# 用独立的测试库，绝不碰 memory_story.db
TEST_DB = os.path.join("/tmp", f"echoes_selftest_{uuid.uuid4().hex[:8]}.db")
os.environ["DATABASE_URL"] = f"sqlite:///{TEST_DB}"

import models                                    # noqa: E402
from models import Story, Member, GrantVia, ClaimStatus, SessionLocal, init_db, get_db  # noqa: E402
from permissions import add_family_member, add_story_member, attach_clip                 # noqa: E402
import collect_api as api                                                               # noqa: E402

PASS = 0
FAIL = 0


def check(label, cond, extra=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"✅ {label}" + (f"  [{extra}]" if extra else ""))
    else:
        FAIL += 1
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
    INNER = "u_uncle"          # 故事成员
    STRANGER = "u_stranger"

    s1 = new_story(db, "s_1", OWNER)
    s2 = new_story(db, "s_2", OWNER)

    # 家人（全本）+ 故事成员（只看 s1）
    fam = add_family_member(db, owner_id=OWNER, user_id=FAMILY, display_name="女儿")
    inner = add_story_member(db, owner_id=OWNER, story_id="s_1", user_id=INNER, display_name="叔叔")

    print("=== A. 文字接口 ===")
    r = api.api_add_text_clip(db, story_id="s_1", owner_id=OWNER, actor_id=OWNER,
                              text="  1968年我第一次坐火车去北京，车厢里全是人。  ")
    check("A1 主人能挂文字", r["ok"], str(r.get("error", "")))
    clip1_id = r.get("data", {}).get("clip_id")
    check("A2 返回了 clip_id", bool(clip1_id), str(clip1_id))
    check("A3 正文两头空格被去掉", "  1968" not in _get_clip(db, clip1_id).text)

    r = api.api_add_text_clip(db, story_id="s_1", owner_id=OWNER, actor_id=OWNER, text="")
    check("A4 空文字被拒", not r["ok"], r.get("error", ""))

    r = api.api_add_text_clip(db, story_id="s_none", owner_id=OWNER, actor_id=OWNER, text="飘着的字")
    check("A5 挂到不存在的故事被拒", not r["ok"], r.get("error", ""))

    r = api.api_add_text_clip(db, story_id="s_1", owner_id=OWNER, actor_id=STRANGER, text="外人乱写")
    check("A6 陌生人没有权限被拒", not r["ok"], r.get("code", ""))

    r = api.api_add_text_clip(db, story_id="s_1", owner_id=OWNER, actor_id=FAMILY, text="爸，我还记得那年下大雪。")
    check("A7 家人（能看整本）能补充", r["ok"], str(r.get("error", "")))

    r = api.api_add_text_clip(db, story_id="s_1", owner_id=OWNER, actor_id=INNER, text="对，我作证。")
    check("A8 故事成员（绑了s1）能补充s1", r["ok"], str(r.get("error", "")))

    r = api.api_add_text_clip(db, story_id="s_2", owner_id=OWNER, actor_id=INNER, text="我没被加进s2")
    check("A9 故事成员添不了没绑的s2", not r["ok"], r.get("code", ""))

    print("=== B. 图片接口 ===")
    r = api.api_add_photo_clip(db, story_id="s_1", owner_id=OWNER, actor_id=OWNER,
                               media_url="https://cdn.example.com/a.jpg",
                               file_name="火车.jpg", file_size=3_500_000, mime="image/jpeg",
                               caption="站台")
    check("B1 主人能挂照片", r["ok"], str(r.get("error", "")))
    check("B2 没给缩略图时用原图顶", r.get("data", {}).get("cover_url") == "https://cdn.example.com/a.jpg")

    r = api.api_add_photo_clip(db, story_id="s_1", owner_id=OWNER, actor_id=OWNER,
                               media_url="https://cdn.example.com/b.txt",
                               file_name="合同.pdf", file_size=1000, mime="application/pdf")
    check("B3 非图片扩展名被拒", not r["ok"], r.get("error", ""))

    r = api.api_add_photo_clip(db, story_id="s_1", owner_id=OWNER, actor_id=OWNER,
                               media_url="https://cdn.example.com/big.jpg",
                               file_name="big.jpg", file_size=30 * 1024 * 1024, mime="image/jpeg")
    check("B4 超过20MB被拒", not r["ok"], r.get("error", ""))

    r = api.api_add_photo_clip(db, story_id="s_1", owner_id=OWNER, actor_id=OWNER,
                               media_url="https://cdn.example.com/empty.jpg",
                               file_name="empty.jpg", file_size=0, mime="image/jpeg")
    check("B5 0字节图片被拒", not r["ok"], r.get("error", ""))

    r = api.api_add_photo_clip(db, story_id="s_1", owner_id=OWNER, actor_id=OWNER,
                               media_url="", file_name="a.jpg", file_size=100, mime="image/jpeg")
    check("B6 缺地址被拒", not r["ok"], r.get("code", ""))

    r = api.api_add_photo_clip(db, story_id="s_2", owner_id=OWNER, actor_id=INNER,
                               media_url="https://cdn.example.com/x.jpg",
                               file_name="x.jpg", file_size=1000, mime="image/jpeg")
    check("B7 故事成员传不了没绑的s2的图", not r["ok"], r.get("code", ""))

    print("=== C. 纯校验函数（不碰库）===")
    check("C1 jpg 通过", api.validate_image(file_name="a.jpg", file_size=1000)[0])
    check("C2 webp 通过", api.validate_image(file_name="a.webp", file_size=1000)[0])
    check("C3 HEIC（苹果手机）通过", api.validate_image(file_name="IMG_0001.HEIC", file_size=1000)[0])
    check("C4 无扩展名但有合法mime 通过", api.validate_image(file_name="blob", file_size=1000, mime="image/jpeg")[0])
    check("C5 无扩展名也无mime 被拒", not api.validate_image(file_name="blob", file_size=1000)[0])

    print("=== D. 取素材筐 ===")
    # 预期筐内应有 4 件：A1(主人文字) + A7(家人文字) + A8(故事成员文字) + B1(主人照片)
    # 被拒的那几件（A4空/A5不存在/A6外人/A9没绑）**一件都不许落库**
    r = api.api_list_clips(db, story_id="s_1", owner_id=OWNER, viewer_id=OWNER)
    check("D1 主人取到素材列表（被拒的一件都没落库）", r["ok"] and r["data"]["count"] == 4,
          f"共{r['data']['count']}件")
    check("D2 分类计数 text=3 / photo=1",
          r["data"]["count_by_type"].get("text", 0) == 3 and r["data"]["count_by_type"].get("photo", 0) == 1,
          str(r["data"]["count_by_type"]))
    orders = [c["sort_order"] for c in r["data"]["clips"]]
    check("D3 按 sort_order 升序", orders == sorted(orders), str(orders))
    check("D4 顺序从0连续无洞", orders == list(range(len(orders))), str(orders))

    r = api.api_list_clips(db, story_id="s_1", owner_id=OWNER, viewer_id=INNER)
    check("D5 故事成员能取s1", r["ok"])

    r = api.api_list_clips(db, story_id="s_2", owner_id=OWNER, viewer_id=INNER)
    check("D6 故事成员取不了s2", not r["ok"], r.get("code", ""))

    r = api.api_list_clips(db, story_id="s_2", owner_id=OWNER, viewer_id=STRANGER)
    check("D7 陌生人取不了", not r["ok"], r.get("code", ""))

    print("=== E. 上传通道（未接对象存储，必须明说）===")
    r = api.api_upload_url(file_name="a.jpg", file_size=1000, mime="image/jpeg")
    check("E1 未接对象存储时明确返回未接（不假装成功）",
          not r["ok"] and r.get("code") == "upload_not_configured", r.get("code", ""))
    r = api.api_upload_url(file_name="a.txt", file_size=1000)
    check("E2 上传前仍先校验图片格式", not r["ok"] and r.get("code") == "invalid_image", r.get("code", ""))

    print("=== F. 跨权限组合（家人/故事成员同挂一条故事）===")
    r = api.api_add_text_clip(db, story_id="s_1", owner_id=OWNER, actor_id=FAMILY, text="妈妈也补一句")
    r2 = api.api_list_clips(db, story_id="s_1", owner_id=OWNER, viewer_id=OWNER)
    # 4件(D线) + 1件(F线新增) = 5件
    check("F1 三个人（主人/家人/故事成员）的素材落在同一个筐",
          r["ok"] and r2["data"]["count"] == 5, f"共{r2['data']['count']}件")
    creators = {c["created_by"] for c in r2["data"]["clips"]}
    check("F2 筐里能看到不同人传的（created_by 有区分）", len(creators) >= 3, str(sorted(creators)))

    print("=== G. 数据完整性铁律 ===")
    from models import Clip as _Clip
    total = db.query(_Clip).count()
    check("G1 被拒的素材一件都没落库（全库仅5件）", total == 5, f"库内{total}件")
    s2_clips = api.api_list_clips(db, story_id="s_2", owner_id=OWNER, viewer_id=OWNER)
    check("G2 s2 仍是空的（没串到别的故事去）", s2_clips["data"]["count"] == 0,
          f"s2共{s2_clips['data']['count']}件")

    db.close()
    os.remove(TEST_DB) if os.path.exists(TEST_DB) else None

    print()
    print("=" * 46)
    print(f"通过 {PASS} 项，失败 {FAIL} 项")
    print("=" * 46)
    return 0 if FAIL == 0 else 1


def _get_clip(db, clip_id):
    from models import Clip
    return db.get(Clip, clip_id)


if __name__ == "__main__":
    sys.exit(main())
