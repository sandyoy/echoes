"""
selftest_card_render.py —— 「做成一张图」（v3.0 §3.3.1 方式 B）自测
=================================================================
实跑真出 PNG，查像素不被骗（不只看 ok=True）。

覆盖：
  ① 全私有 → PermissionError，**不出图**（绝不泄漏私有内容）
  ② 有公开 → 出真 PNG（魔数 \\x89PNG、宽 750、高度随内容伸缩）
  ③ 图上**只有公开素材的文字**（私有那句不在图内——用像素级比对：造两版只差私有文本的数据，图必须一样）
  ④ 换一条更长的公开文本 → 图更高（换行生效、不是截断）
  ⑤ 主人名字为空 → 不画"None的故事"，也不崩
  ⑥ 书卡：只数可分享篇（私有篇不计数、不暗示存在）
  ⑦ 信封形状：api_render_card 返回 ok/code
  ⑧ 字体缺失时 → render_unavailable（明确报，不静默出豆腐块）
"""
import io
import os
import sys

os.environ["DATABASE_URL"] = "sqlite:///:memory:"
os.environ["ECHOES_DB"] = ":memory:"
os.environ["DB_PATH"] = ":memory:"

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from models import (  # noqa: E402
    SessionLocal, Base, engine, User, Story, Clip, ClipType, Visibility,
)
import share_api as S       # noqa: E402
import card_render as R     # noqa: E402
from PIL import Image       # noqa: E402

PASS = 0
FAIL = 0
PNG_MAGIC = b"\x89PNG\r\n\x1a\n"


def check(name, cond, extra=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  ✅ {name}")
    else:
        FAIL += 1
        print(f"  ❌ {name} {extra}")


def size_of(png):
    im = Image.open(io.BytesIO(png))
    return im.width, im.height


def main():
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    db = SessionLocal()

    u = User(id="u_li", nick_name="李桂芳")
    db.add(u)

    # A：全私有
    db.add(Story(id="s_A", owner_id="u_li", title="1979年那场大水", time_raw="1979年"))
    db.add(Clip(id="c_A1", story_id="s_A", clip_type=ClipType.TEXT,
                text="那年水好大，家里的麦子全淹了", provider_id="u_li",
                visibility=Visibility.PRIVATE))
    # B：一私一公
    db.add(Story(id="s_B", owner_id="u_li", title="嫁过来第二年", time_raw="1976年",
                 summary="那年村里头一回通了电"))
    db.add(Clip(id="c_B1", story_id="s_B", clip_type=ClipType.TEXT,
                text="张大叔那天来帮忙，我心里记着", provider_id="u_li",
                visibility=Visibility.PRIVATE))
    db.add(Clip(id="c_B2", story_id="s_B", clip_type=ClipType.TEXT,
                text="我嫁过来第二年，村里通了电", provider_id="u_li",
                visibility=Visibility.PUBLIC))
    # C：无名字的主人 + 全私有（边界）
    db.add(User(id="u_noname", nick_name=""))
    db.add(Story(id="s_C", owner_id="u_noname", title="没标题"))
    db.add(Clip(id="c_C1", story_id="s_C", clip_type=ClipType.TEXT, text="x",
                provider_id="u_noname", visibility=Visibility.PUBLIC))
    db.commit()

    print("\n=== ① 全私有 → 不出图 ===")
    try:
        R.render_story_card(db, story_id="s_A")
        check("A 应被拒", False, "(出了图=泄漏!)")
    except PermissionError:
        check("A raise PermissionError（不出含私有内容的图）", True)

    print("\n=== ② 有公开 → 真 PNG，宽 750 ===")
    png = R.render_story_card(db, story_id="s_B")
    check("PNG 魔数", png.startswith(PNG_MAGIC), png[:8])
    w, h = size_of(png)
    check("宽=750（与原型图同宽）", w == 750, w)
    check("高度合理（>600 且 <2000）", 600 < h < 2000, h)
    check("体积 >5KB（不是空白图）", len(png) > 5000, len(png))

    print("\n=== ③ 私有素材不上图（像素级：只改私有文本，图必须一模一样）===")
    clip = db.get(Clip, "c_B1")
    clip.text = "张大叔那天来帮忙，我心里记着"  # 原标题
    db.commit()
    png_a = R.render_story_card(db, story_id="s_B")
    clip.text = "完全不同的私有说法：那年他还借过我二十块钱"
    db.commit()
    png_b = R.render_story_card(db, story_id="s_B")
    check("私有文本改动 → 卡片图字节一致（没把私有内容画进去）", png_a == png_b)
    # 反过来：改公开文本 → 图必须变（证明 ③ 不是"图恒等"的空检验）
    c2 = db.get(Clip, "c_B2")
    c2.text = "我嫁过来第二年，村里头一回通了电，全村人都去看"
    db.commit()
    png_c = R.render_story_card(db, story_id="s_B")
    check("公开文本改动 → 卡片图变（检验有效）", png_c != png_b)

    print("\n=== ④ 更长的公开文本 → 图更高（换行生效）===")
    c2.text = "我嫁过来第二年，村里头一回通了电。" * 12
    db.commit()
    png_long = R.render_story_card(db, story_id="s_B")
    _, h_long = size_of(png_long)
    check("长文本 图更高", h_long > h, (h, h_long))

    print("\n=== ⑤ 主人没名字 → 不崩、不写 None ===")
    png_c2 = R.render_story_card(db, story_id="s_C")
    check("无名字也能出图", png_c2.startswith(PNG_MAGIC))

    print("\n=== ⑥ 书卡：只数可分享篇 ===")
    from share_api import make_card_data
    d = make_card_data(db, kind="book", target_id="u_li")
    check("书卡 sub 里 1 篇（A 全私有不计）", "1 篇" in d.get("sub", ""), d.get("sub"))
    png_book = R.render_book_card(db, owner_id="u_li")
    check("书卡出图", png_book.startswith(PNG_MAGIC))
    try:
        R.render_book_card(db, owner_id="u_noname")
        # u_noname 的 s_C 有一条 public → 可分享，这里应成功
        check("无名字的书卡也能出图", True)
    except Exception as e:
        check("无名字的书卡也能出图", False, repr(e))

    print("\n=== ⑦ 信封 ===")
    ok = R.api_render_card(db, actor_id="u_li", kind="story", target_id="s_B")
    check("api ok=True", ok.get("ok") is True, ok)
    check("回宽高", ok["data"]["width"] == 750 and ok["data"]["height"] > 0, ok.get("data"))
    bad = R.api_render_card(db, actor_id="u_li", kind="story", target_id="s_A")
    check("私有篇 → code=not_shareable", bad.get("code") == "not_shareable", bad)
    nob = R.api_render_card(db, actor_id="u_li", kind="xxx")
    check("错 kind → code=bad_kind", nob.get("code") == "bad_kind", nob)

    print("\n=== ⑧ 排版自证（量像素，不靠眼看）===")
    chk = R.api_card_check(png=png)
    check("体检 ok", chk.get("ok") is True, chk)
    dd = chk.get("data", {})
    check("无越界（字没碰画布边）", dd.get("overflow") is False, dd.get("overflow"))
    check("底部留白 ≥40px（小字完整、不被切）",
          dd.get("ink_bottom_gap_px", 0) >= 40, dd.get("ink_bottom_gap_px"))

    print("\n=== ⑨ 引文与摘要重复 → 只印一遍（不重复同句）===")
    c2.text = "我嫁过来第二年，村里头通了电"
    db.get(Story, "s_B").summary = "我嫁过来第二年，村里头通了电。"
    db.commit()
    png_dup = R.render_story_card(db, story_id="s_B")
    _, h_dup = size_of(png_dup)
    db.get(Story, "s_B").summary = ""
    db.commit()
    png_nodup = R.render_story_card(db, story_id="s_B")
    _, h_nodup = size_of(png_nodup)
    check("摘要=引文 → 图与无摘要一致（去重生效）", h_dup == h_nodup, (h_dup, h_nodup))

    print("\n=== ⑩ 字体缺失 → 明确报 render_unavailable ===")
    old = os.environ.get("ECHOES_CARD_FONT", "")
    R._FONT_CACHE.clear()
    R._FONT_CANDIDATES_BACKUP = list(R._FONT_CANDIDATES)
    R._FONT_CANDIDATES = ["/nonexistent/font.ttf"]
    _orig_glob = R.glob.glob
    R.glob.glob = lambda *a, **k: []
    os.environ["ECHOES_CARD_FONT"] = "/nonexistent/x.ttf"
    try:
        res = R.api_render_card(db, actor_id="u_li", kind="story", target_id="s_B")
        check("没字体 → code=render_unavailable（不装成功）",
              res.get("code") == "render_unavailable", res)
    finally:
        R.glob.glob = _orig_glob
        R._FONT_CANDIDATES = R._FONT_CANDIDATES_BACKUP
        R._FONT_CACHE.clear()
        if old:
            os.environ["ECHOES_CARD_FONT"] = old
        else:
            os.environ.pop("ECHOES_CARD_FONT", None)

    # 落一张真图给 sandy 看（内部自查用，不进仓库）
    out = "/tmp/echoes_card_story_demo.png"
    with open(out, "wb") as f:
        f.write(R.render_story_card(db, story_id="s_B"))
    print(f"\n[样例图] {out}")

    print(f"\n===== card_render 自测：{PASS} 过 / {FAIL} 败 =====")
    return 0 if FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
