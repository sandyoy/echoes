"""
往事可追忆 - 九个九付费链路 端到端自测（可复跑）
建立：2026-10-31

跑法：
    cd /home/ubuntu/echoes/backend
    python3.12 tests_paid_flow_20261031.py

它会在**真库**里造 5 个测试用户（前缀 zt_），走真实 HTTP，不走内存 mock。
测完只清理自己造的（前缀 zt_），绝不动真用户数据。

覆盖（需求书 §9.6 五修逐条）：
  T1 免费层不受限                → identity / choices 未付时给什么
  T2 付完 9.9 两按钮             → 为他人付费 / 自己先说
  T3 gift 路径：卡片 → 老人接受 → 书归老人
  T4 自己先说路径：当场开书 → 书归自己
  T5 一人一本：同一人再买 → 不重开、不出现第二本
  T6 299 门槛：页数不够 → 不给印，说清差多少
  T7 30 天过期：接受被拒 + 标待退款
  T8 幂等：同一张卡接受两次不重开书
"""
import sys
import os
import json
import urllib.request
import urllib.error
import datetime as dt

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.chdir(os.path.dirname(os.path.abspath(__file__)))

BASE = "http://127.0.0.1:8971"
PFX = "zt_31_"

from models import SessionLocal, User, Ebook, Order, Story, Clip

results = []


def _get(path):
    try:
        with urllib.request.urlopen(BASE + path, timeout=15) as r:
            return json.loads(r.read())
    except urllib.error.HTTPError as e:
        return {"_http": e.code, "_body": e.read().decode()[:400]}
    except Exception as e:
        return {"_err": str(e)}


def _post(path, body):
    req = urllib.request.Request(
        BASE + path, data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            return json.loads(r.read())
    except urllib.error.HTTPError as e:
        return {"_http": e.code, "_body": e.read().decode()[:400]}
    except Exception as e:
        return {"_err": str(e)}


def check(name, cond, detail=""):
    results.append((name, bool(cond), detail))
    print(("  ✅ " if cond else "  ❌ ") + name + (f"   [{detail}]" if detail and not cond else ""))


def ensure_user(db, uid, nick=""):
    u = db.get(User, uid)
    if u is None:
        u = User(id=uid, nick_name=nick or uid, phone="")
        db.add(u)
        db.commit()
    return u


def make_paid_order(db, uid, plan="ebook", amount=None, gift_to="", deadline=None):
    """造一笔已付款单（模拟微信回调已到账）"""
    from permissions import _new_id
    o = Order(
        id=_new_id("order"),
        user_id=uid,
        plan_code=plan,
        amount=amount if amount is not None else (9.9 if plan == "ebook" else 299.0),
        pay_channel="wechat",
        status="paid",
        gift_to_user_id=gift_to,
        accept_deadline=deadline,
        paid_at=dt.datetime.utcnow(),
    )
    db.add(o)
    db.commit()
    db.refresh(o)
    return o


def cleanup(db):
    """只删自己造的 zt_ 数据"""
    users = [u for u in db.query(User).all() if u.id.startswith(PFX)]
    uids = {u.id for u in users}
    orders = [o for o in db.query(Order).all() if (o.user_id in uids) or (o.gift_to_user_id in uids)]
    book_ids = {o.book_id for o in orders if o.book_id}
    for o in orders:
        db.delete(o)
    db.commit()
    books = [b for b in db.query(Ebook).all() if b.owner_id in uids or b.id in book_ids]
    for b in books:
        for st in db.query(Story).filter(Story.owner_id == b.owner_id).all():
            db.query(Clip).filter(Clip.story_id == st.id).delete()
            db.delete(st)
        db.delete(b)
    db.commit()
    for u in users:
        db.delete(u)
    db.commit()


def main():
    db = SessionLocal()
    try:
        ids = {k: PFX + k for k in ("kid", "mom", "self", "twice", "expy")}

        # 清场：先清上一轮残留，保证可复跑
        cleanup(db)
        for k, uid in ids.items():
            ensure_user(db, uid, k)

        print("\n=== T1 免费层不受限 / 未付款不假成功 ===")
        r = _get(f"/api/echoes/pay/identity?user_id={ids['kid']}")
        check("T1.1 新用户 identity 可读、无书", r.get("ok") and r["data"]["has_book"] is False, json.dumps(r)[:200])
        r = _get(f"/api/echoes/pay/choices?user_id={ids['kid']}")
        check("T1.2 未付款 → bought=False，不给按钮", r.get("ok") and r["data"]["bought"] is False and r["data"]["buttons"] == [], json.dumps(r)[:200])

        print("\n=== T2 付完 9.9 → 两个按钮 ===")
        make_paid_order(db, ids["kid"], "ebook")
        r = _get(f"/api/echoes/pay/choices?user_id={ids['kid']}")
        btns = r.get("data", {}).get("buttons", [])
        check("T2.1 bought=True", r.get("data", {}).get("bought") is True, json.dumps(r)[:200])
        check("T2.2 恰好两个按钮", len(btns) == 2, str(len(btns)))
        check("T2.3 按钮含'给爸妈'与'我自己'",
              any("爸妈" in b["label"] for b in btns) and any("我自己" in b["label"] for b in btns),
              str([b["label"] for b in btns]))

        print("\n=== T3 gift 路径：卡片 → 老人接受 → 书归老人 ===")
        r = _post("/api/echoes/pay/choose", {"user_id": ids["kid"], "choice": "gift_to_elder"})
        token = r.get("data", {}).get("card", {}).get("token", "")
        check("T3.1 生成卡片且带凭据", r.get("ok") and bool(token), json.dumps(r, ensure_ascii=False)[:300])
        check("T3.2 此时书**未**归老人（还未接受）",
              _get(f"/api/echoes/pay/identity?user_id={ids['mom']}")["data"]["has_book"] is False)
        r = _post("/api/echoes/pay/accept_gift", {"token": token, "new_owner_id": ids["mom"]})
        check("T3.3 老人接受成功", r.get("ok") is True, json.dumps(r, ensure_ascii=False)[:300])
        r = _get(f"/api/echoes/pay/identity?user_id={ids['mom']}")
        check("T3.4 书归老人（owner=老人）", r["data"]["role"] == "owner" and r["data"]["owner_id"] == ids["mom"], json.dumps(r, ensure_ascii=False)[:300])
        check("T3.5 老人的身份里 paid_by_me=False（不显示是孩子买的）", r["data"]["paid_by_me"] is False)

        print("\n=== T4 自己先说路径 ===")
        make_paid_order(db, ids["self"], "ebook")
        r = _post("/api/echoes/pay/choose", {"user_id": ids["self"], "choice": "self_first"})
        check("T4.1 当场开书", r.get("ok") and bool(r["data"].get("book_id")), json.dumps(r, ensure_ascii=False)[:300])
        r = _get(f"/api/echoes/pay/identity?user_id={ids['self']}")
        check("T4.2 自己是书主人", r["data"]["role"] == "owner" and r["data"]["paid_by_me"] is True, json.dumps(r, ensure_ascii=False)[:300])

        print("\n=== T5 一人一本：再买不重开 ===")
        make_paid_order(db, ids["self"], "ebook")
        r = _get(f"/api/echoes/pay/choices?user_id={ids['self']}")
        check("T5.1 已有一本 → same_book=True，不给新书按钮",
              r["data"]["same_book"] is True and len(r["data"]["buttons"]) == 1, json.dumps(r, ensure_ascii=False)[:300])
        books = db.query(Ebook).filter(Ebook.owner_id == ids["self"]).all()
        check("T5.2 库里只有一本", len(books) == 1, f"实际 {len(books)} 本")

        print("\n=== T6 299 门槛：页数不够不给印 ===")
        r = _get(f"/api/echoes/pay/print_eligibility?owner_id={ids['self']}")
        check("T6.1 新书不够格", r["data"]["eligible"] is False, json.dumps(r, ensure_ascii=False)[:300])
        check("T6.2 说清差多少（不打击人）", "再答" in r["data"]["notice"], r["data"]["notice"])
        check("T6.3 9.9 永远可买", r["data"]["can_buy_ebook"] is True)

        print("\n=== T7 30 天过期 ===")
        past = dt.datetime.utcnow() - dt.timedelta(days=1)
        o = make_paid_order(db, ids["expy"], "ebook", gift_to="__pending__", deadline=past)
        r = _post("/api/echoes/pay/accept_gift", {"token": o.id, "new_owner_id": ids["mom"]})
        check("T7.1 过期卡拒绝接受", r.get("ok") is False and r.get("code") == "expired", json.dumps(r, ensure_ascii=False)[:300])
        db.refresh(o)
        check("T7.2 标记待退款", o.refund_state == "expired_waiting_refund", o.refund_state)
        r = _post("/api/echoes/pay/sweep_expired_gifts", {})
        check("T7.3 退款扫描能出清单", r.get("ok") is True, json.dumps(r, ensure_ascii=False)[:300])

        print("\n=== T8 幂等：同一张卡接受两次 ===")
        o2 = make_paid_order(db, ids["twice"], "ebook",
                             deadline=dt.datetime.utcnow() + dt.timedelta(days=30))
        r1 = _post("/api/echoes/pay/accept_gift", {"token": o2.id, "new_owner_id": ids["mom"]})
        r2 = _post("/api/echoes/pay/accept_gift", {"token": o2.id, "new_owner_id": ids["mom"]})
        check("T8.1 第一次成功", r1.get("ok") is True)
        check("T8.2 第二次幂等不重开", r2.get("ok") is True and r2["data"].get("idempotent") is True, json.dumps(r2, ensure_ascii=False)[:300])
        books = db.query(Ebook).filter(Ebook.owner_id == ids["mom"]).all()
        check("T8.3 老人仍只有一本", len(books) == 1, f"实际 {len(books)} 本")

    finally:
        cleanup(db)
        db.close()

    print("\n" + "=" * 56)
    bad = [r for r in results if not r[1]]
    print(f"共 {len(results)} 项，通过 {len(results)-len(bad)}，失败 {len(bad)}")
    for n, _, d in bad:
        print("   ❌", n, d)
    return 0 if not bad else 1


if __name__ == "__main__":
    sys.exit(main())
