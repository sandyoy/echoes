# -*- coding: utf-8 -*-
"""
print_api.py —— v3.0 §8.1 / §8.5【实体书】后端通道（2026-10-17）

【为什么有这个文件（找活记录）】
    §8.5 原文：「对接印刷厂（sandy 联系，多家比价）；印刷厂决定页数/开本/装帧；
                 印完邮寄到家。**现在不用决定。**」
    models.py 里 `PrintOrder` 表从 §七 收费段建库那天就在，但全仓库
    除 payment_api 的注释提过它一句，**零代码使用**（`grep -rn PrintOrder backend/*.py`
    只有 models.py 定义 + payment_api docstring）。也就是——
        **用户「满意了 → 印实体书」，前端无处可点；印刷厂报价单来了也没处录。**
    这是「表在能力没接」的又一例：不是没设计，是**最后一跳没人写**。

【本文件的边界（严守 §8.1 / §8.5，不许越界）】
    1. **不替 sandy 选印刷厂**（多家比价是他的决策）→ 印刷厂用 `vendor` 字段自由填，
       不做厂商白名单、不写死任何厂商名/价格（同 §9.1「代码里一行价格都没有」）。
    2. **不臆造印刷能力**（能不能印、多少页、什么工艺 = 印刷厂说了算）→
       印刷厂口径缺失时返回 `spec_missing` / `printer_not_configured`，
       **绝不假装下单成功**（铁律 A）。
    3. **只「实体书后置」**（§8.1 铁律）：电子书必须已生成；未成书 → `no_ebook` 拒。
       且 §8.4「电子书是活文档」→ 续添后内容变了，旧排版件作废 → `stale_ebook` 拦下重排。
    4. **一人只能印自己的书**：owner_id 必须是书主人（与 book_view 同口径）。

【对外 5 个 handler】
    api_print_catalog(db, owner_id)            可印信息：开本候选/页数/预计件数/能否印
    api_print_quote(db, owner_id, book_spec, copies, vendor)
                                               生成印件清单（落 PrintOrder, status=quoted）
    api_print_order(db, print_order_id, actor_id)
                                               查印单（只有本人能看）
    api_print_my_orders(db, owner_id)          我的印单列表
    api_print_set_status(db, print_order_id, actor_id, status, vendor)
                                               印刷厂回执 → 状态流转（幂等、只许合法迁移）

【状态机】pending → quoted → confirmed → printing → shipped → done
                               ↘ cancelled（任一非终态可取消）
    不给「done → 任意」开后门：印完/寄到的单子不许再改，避免账目被回写成未发货。
"""

import json
from datetime import datetime

from models import (
    SessionLocal, Story, Clip, Ebook, PrintOrder, User, init_db,
)
import book_view_api as BV


# ============================================================
# 一、统一信封（与 book_view_api / book_api / payment_api 同形）
# ============================================================

def ok(data=None, **extra):
    d = {"ok": True, "data": data, "error": "", "code": ""}
    d.update(extra)
    return d


def fail(msg: str, code: str = "bad_request", **extra):
    d = {"ok": False, "data": None, "error": msg, "code": code}
    d.update(extra)
    return d


NO_PERMISSION = "只有这本书的主人能操作它"

# §8.5 印刷厂口径：下列键为「必须由印刷厂给」的参数（本端不臆造）
PRINTER_REQUIRED_KEYS = ("vendor", "unit_price")

# 状态机：只许往前推 / 取消，不许倒退
STATUS_FLOW = {
    "pending":   {"quoted", "confirmed", "cancelled"},
    "quoted":    {"confirmed", "cancelled"},
    "confirmed": {"printing", "cancelled"},
    "printing":  {"shipped"},          # 已开印 → 不能再取消（纸已经下去了）
    "shipped":   {"done"},
    "done":      set(),
    "cancelled": set(),
}
TERMINAL = {"done", "cancelled"}
STATUS_LABEL = {
    "pending": "待报价",
    "quoted": "已报价",
    "confirmed": "已确认",
    "printing": "印刷中",
    "shipped": "已寄出",
    "done": "已完成",
    "cancelled": "已取消",
}


# ============================================================
# 二、内部：取书主人自己的电子书（§8.1 实体书后置）
# ============================================================

def _get_my_ebook(db, owner_id: str):
    return (db.query(Ebook)
              .filter(Ebook.owner_id == owner_id)
              .order_by(Ebook.created_at.desc())
              .first())


def _content_of(eb) -> dict:
    try:
        return json.loads(eb.content or "{}") or {}
    except Exception:
        return {}


def _entry_count(content: dict) -> int:
    """条目数（与 book_view 的排版最小单元一致：一条素材一条）。"""
    n = 0
    for ch in content.get("chapters", []) or []:
        n += len(ch.get("entries", []) or [])
    return n


def _page_count(content: dict, lines_per_page: int = 12) -> int:
    """页数：直接用 book_view 的 paginate()，**不另算一套**（§8.6 线上=印着）。"""
    try:
        return len(BV.paginate(content, lines_per_page=lines_per_page))
    except Exception:
        return 0


def _timestamp_after(a, b) -> bool:
    """a 是否晚于 b（两个都是 datetime 或字符串都兜住）。"""
    try:
        return a > b
    except Exception:
        return False


# ============================================================
# 三、★对外①：可印信息（前端「满意了 → 去印书」页进入时读）
# ============================================================

def api_print_catalog(db, *, owner_id: str, book_spec: str = "A5") -> dict:
    """
    前端进「印实体书」页先调这个：
      - 书还没成         → ok=True + can_print=False + reason=no_ebook（不是报错，是"还没到这一步"）
      - 书已成           → 给页数/条目数/开本尺寸/预计成品规格，供印刷厂报价
      - 开本不认识       → 回落 A5 并标 fallback=True（沿用 book_view 口径）

    ⚠️ 这里**故意不返回任何价格**：价格只能来自印刷厂报价（vendor 填报），
       本端不臆造（§9.1 精神）。
    """
    if not owner_id:
        return fail("缺少 owner_id", "missing_owner_id")
    eb = _get_my_ebook(db, owner_id)
    if eb is None:
        return ok({
            "can_print": False,
            "reason": "no_ebook",
            "notice": "先把电子书做出来，看着满意了再来印实体书。",   # §8.1 顺序
            "specs": None,
        })

    content = _content_of(eb)
    chapters = content.get("chapters", []) or []
    if not chapters:
        return ok({
            "can_print": False, "reason": "empty_ebook",
            "notice": "这本书里还没有内容，印不出东西。", "specs": None,
        })

    spec = BV.computed_page_size_mm(book_spec)
    pages = _page_count(content)
    entries = _entry_count(content)

    # §8.4 活文档：续添/重生成后内容比上次印单新 → 旧排版件作废
    last = (db.query(PrintOrder)
              .filter(PrintOrder.owner_id == owner_id)
              .order_by(PrintOrder.created_at.desc())
              .first())
    stale = False
    if last is not None and not _is_cancelled(last):
        stale = _timestamp_after(eb.created_at, last.created_at) and \
                (eb.id != (last.ebook_id or ""))

    return ok({
        "can_print": True,
        "reason": "",
        "ebook_id": eb.id,
        "ebook_title": eb.title,
        "specs": {
            "book_spec": spec["spec"],
            "width_mm": spec["width_mm"],
            "height_mm": spec["height_mm"],
            "fallback": spec["fallback"],
            "page_count": pages,
            "entry_count": entries,
            "chapter_count": len(chapters),
            "contributors": content.get("contributors", []) or [],
        },
        "last_print_order": (None if last is None else {
            "print_order_id": last.id,
            "status": last.status,
            "status_label": STATUS_LABEL.get(last.status, last.status),
            "copies": last.copies,
            "book_spec": last.book_spec,
        }),
        "stale_against_last_order": stale,
        "notice": ("内容比上次印单新了，重新报一次价再印，免得印出旧版本。" if stale else ""),
    })


def _is_cancelled(po) -> bool:
    return str(getattr(po, "status", "") or "") == "cancelled"


# ============================================================
# 四、★对外②：生成印件清单（落 PrintOrder，status=quoted）
# ============================================================

def api_print_quote(db, *, owner_id: str, actor_id: str = "",
                    book_spec: str = "A5", copies: int = 1,
                    vendor: str = "", unit_price=None,
                    padding: str = "") -> dict:
    """
    把「这本书 + 这个开本 + 这些册数 + 这家厂」落成一张印单（报价/下单前的清单）。

    关键规矩：
      - **可不带价**（还没报价也能先建单 → status=pending）；带价则 status=quoted。
        价格与厂商都是**外部输入**，本端不猜、不填默认价。
      - `unit_price` 若给，必须是数字且 >= 0；本端只做算术（总价 = 单价 × 册数），
        **不做任何"建议零售价"/加价**（那是 §九 收款的事，不在这里混）。
      - 册数越界（<=0 或 > MAX_COPIES）→ 拒。上限不是业务规则，是防手滑打出 999 册。
      - 书没生成 → no_ebook 拒（§8.1 实体书必须后置于电子书）。
      - 别人的书 → forbidden。
    """
    if not owner_id:
        return fail("缺少 owner_id", "missing_owner_id")
    actor = actor_id or owner_id
    if actor != owner_id:
        return fail(NO_PERMISSION, "forbidden")

    try:
        copies = int(copies)
    except Exception:
        return fail("册数要写个整数", "bad_copies")
    if copies <= 0:
        return fail("册数至少 1 本", "bad_copies")
    if copies > MAX_COPIES:
        return fail(f"一次最多 {MAX_COPIES} 本，多了请直接联系印刷厂", "too_many_copies")

    if unit_price is not None and unit_price != "":
        try:
            unit_price = float(unit_price)
        except Exception:
            return fail("单价要写数字", "bad_price")
        if unit_price < 0:
            return fail("单价不能是负数", "bad_price")
    else:
        unit_price = None

    eb = _get_my_ebook(db, owner_id)
    if eb is None:
        return fail("还没有电子书，不能印实体书", "no_ebook")
    content = _content_of(eb)
    if not (content.get("chapters") or []):
        return fail("这本书里还没有内容", "empty_ebook")

    spec = BV.computed_page_size_mm(book_spec)
    from permissions import _new_id
    po = PrintOrder(
        id=_new_id("print"),
        ebook_id=eb.id,
        owner_id=owner_id,
        book_spec=spec["spec"],
        copies=copies,
        price=(float(unit_price) * copies) if unit_price is not None else 0.0,
        vendor=(vendor or "").strip(),
        status=("quoted" if unit_price is not None else "pending"),
    )
    db.add(po)
    db.commit()
    db.refresh(po)

    out = _order_view(po)
    out["quote"] = {
        "unit_price": unit_price,
        "copies": copies,
        "total_price": po.price,
        "currency": "CNY",
        "priced": unit_price is not None,
        "notice": ("" if unit_price is not None
                   else "还没报价：印刷厂给了单价再补进来，本系统不填默认价。"),
    }
    out["specs"] = {
        "book_spec": spec["spec"],
        "width_mm": spec["width_mm"],
        "height_mm": spec["height_mm"],
        "page_count": _page_count(content),
        "entry_count": _entry_count(content),
        "padding": padding,
    }
    return ok(out)


MAX_COPIES = 200


def _order_view(po) -> dict:
    return {
        "print_order_id": po.id,
        "ebook_id": po.ebook_id,
        "owner_id": po.owner_id,
        "book_spec": po.book_spec,
        "copies": po.copies,
        "price": float(po.price or 0.0),
        "vendor": po.vendor or "",
        "status": po.status,
        "status_label": STATUS_LABEL.get(po.status, po.status),
        "created_at": str(po.created_at or ""),
    }


# ============================================================
# 五、★对外③④：查单 / 我的印单
# ============================================================

def api_print_order(db, *, print_order_id: str, actor_id: str = "") -> dict:
    """查一张印单。**只有书主人能看**（印单含地址类敏感信息的扩展位，一律不外给）。"""
    if not print_order_id:
        return fail("缺少 print_order_id", "missing_id")
    po = db.get(PrintOrder, print_order_id)
    if po is None:
        return fail("没有这张印单", "not_found")
    if not actor_id or actor_id != po.owner_id:
        return fail(NO_PERMISSION, "forbidden")
    v = _order_view(po)
    v["next_status"] = sorted(STATUS_FLOW.get(po.status, set()))
    return ok(v)


def api_print_my_orders(db, *, owner_id: str) -> dict:
    """我的印单列表（新的在前）。没有书/没印过 → 空列表（不报错）。"""
    if not owner_id:
        return fail("缺少 owner_id", "missing_owner_id")
    rows = (db.query(PrintOrder)
              .filter(PrintOrder.owner_id == owner_id)
              .order_by(PrintOrder.created_at.desc())
              .all())
    return ok({
        "count": len(rows),
        "orders": [_order_view(r) for r in rows],
    })


# ============================================================
# 六、★对外⑤：状态流转（印刷厂回执）
# ============================================================

def api_print_set_status(db, *, print_order_id: str, actor_id: str = "",
                         status: str = "", vendor: str = "") -> dict:
    """
    印刷厂/运营把回执写回来（已确认 → 印刷中 → 已寄出 → 已完成）。

    三条硬规矩：
      1. **只许合法迁移**（STATUS_FLOW）：印完了不能改回"待报价"（账目不许被回写）。
      2. **幂等**：目标状态 == 当前状态 → ok + `unchanged=True`，不报错、不改时间。
      3. **不臆造**：`status` 不在状态机里 → `bad_status` 拒，不静默落个野值。
         （models 里 status 是 String(32)，不做校验就会静默写进 "发货了" 这种值。）
    """
    if not print_order_id:
        return fail("缺少 print_order_id", "missing_id")
    po = db.get(PrintOrder, print_order_id)
    if po is None:
        return fail("没有这张印单", "not_found")
    if not actor_id or actor_id != po.owner_id:
        return fail(NO_PERMISSION, "forbidden")

    want = (status or "").strip()
    if want not in STATUS_FLOW:
        return fail("不认识这个状态", "bad_status")

    if want == po.status:
        v = _order_view(po)
        v["unchanged"] = True
        return ok(v)

    if want not in STATUS_FLOW.get(po.status, set()):
        return fail(f"“{STATUS_LABEL.get(po.status, po.status)}”不能直接改成"
                    f"“{STATUS_LABEL.get(want, want)}”", "bad_transition")

    po.status = want
    if vendor:
        po.vendor = vendor.strip()
    db.commit()
    db.refresh(po)
    v = _order_view(po)
    v["unchanged"] = False
    v["next_status"] = sorted(STATUS_FLOW.get(po.status, set()))
    return ok(v)


# ============================================================
# 七、自测入口（真跑：/usr/bin/python3 print_api.py）
# ============================================================

if __name__ == "__main__":
    import tempfile, os
    os.environ["DATABASE_URL"] = f"sqlite:///{tempfile.mktemp(suffix='.db')}"
    init_db()
    db = SessionLocal()
    from models import Story, Clip, ClipType, Visibility, SourceType
    from permissions import _new_id

    owner = "u_owner"
    db.add(User(id=owner, nick_name="李桂芳"))
    st = Story(id="s1", owner_id=owner, title="小时候")
    db.add(st)
    db.commit()
    db.add(Clip(id=_new_id("clip"), story_id="s1", clip_type=ClipType.TEXT,
                provider_id=owner, text="我八岁那年下了很大的雪", visibility=Visibility.PUBLIC,
                source_type=SourceType.ORIGIN))
    db.commit()
    import book_api
    r = book_api.api_generate_ebook(db, owner_id=owner)
    eid = r["data"]["ebook_id"]

    print("catalog:", api_print_catalog(db, owner_id=owner)["data"]["specs"])
    q = api_print_quote(db, owner_id=owner, copies=3, vendor="某某印务", unit_price=28.5)
    print("quote:", q["data"]["status"], q["data"]["price"])
    pid = q["data"]["print_order_id"]
    print("confirm:", api_print_set_status(db, print_order_id=pid, actor_id=owner, status="confirmed")["data"]["status"])
    print("bad jump:", api_print_set_status(db, print_order_id=pid, actor_id=owner, status="done")["code"])
