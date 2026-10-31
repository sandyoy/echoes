"""
往事可追忆 - 九个九付费链路（paid_flow_api）v1.0
建立：2026-10-31（sandy 定死新版付费结构，需求书 §9.6 五修 / §9.7 本书）

=== 本文件解决什么 ===
payment_api.py 只能"开价/下单/回调"，但新版结构里最关键的几件事**一处都没写**：
  ① 付完钱之后那两个按钮（转给爸妈 / 我自己先说）—— 这是 9.9 全部价值所在
  ② 一人一本锁 —— 爸妈和孩子各自付 9.9，不能变成两本互不相通的册子
  ③ 为他人付费后 30 天没人接受 → 全额原路退
  ④ 9.9 出电子册、299 才出实体书，两档是**两个独立产物**，不是同一个东西的两种价

=== 定死的规则（sandy 2026-10-31，逐条对应）===
R1 免费层：自己说 / AI 问 / 进时间链 —— 永久免费，不卡任何东西
R2 9.9 = 电子册。答 3 个问题出 3 个的册子，答 30 个出 30 个的，**篇幅不设上限也不设下限**
R3 299 = 实体书。**答够页数才解锁**（页数门槛在后台配置，默认 40），且这一层才做润色
R4 付完 9.9 当场二选一：转给爸妈让老人说 / 我自己先说
R5 两条路进来，体验完全一样；**付费关系对老人不可见**（老人永远看到"这是我自己的册子"）
R6 谁先开头，册子归谁，但归这个家 —— 一人只有一本，后面再付不退不重开
R7 子女能看全部、能加自己那段，**不能改爸妈的**
R8 为他人付费后 **30 天**无人接受 → 书不成立，全额原路退（后台可配天数）

=== 铁律（与 payment_api / entitlement 同）===
1. handler 不自己开 session，db 由调用方传
2. 统一信封 {ok, data, error, code}
3. **零信任前端**：书归谁、能不能改，只认库里的关系，不认请求体
4. **不臆造**：缺什么说什么，不返回假成功
5. **绝不误伤老人**：任何异常 → 老人的素材/自己写的永远能看（fail-open 只对"看"成立，
   对"改别人的"永远 fail-closed）
"""

import datetime as _dt

from permissions import _new_id
from models import User, Story, Ebook, Order, Pricing

# 两档产物（与 migrate_20261031_paid_flow.py 写入的 plan_code 一致）
PLAN_EBOOK = "ebook"           # 9.9 电子册
PLAN_PRINT = "print_book"      # 299 实体书

# R8：为他人付费后的接受期（天）。后台 Pricing.period_days 有值则以其为准。
GIFT_ACCEPT_DAYS_DEFAULT = 30

# R3：实体书页数门槛的**兜底值**（真值在 Pricing.remark 之外由后台 set_plan 的 period_days
# 之外的字段承载不了，故这里读 Pricing 表里 plan_code='print_book' 的 remark 中的
# "pages=NN"约定；未配置时用这个兜底，且**只用于判断"够不够格印"，不涉及价格**）
PRINT_MIN_PAGES_FALLBACK = 40

# 一字不差的对外措辞（前端直接用，不自己编）
BTN_FOR_KID = "转给爸妈，让他自己说"
BTN_FOR_SELF = "我自己先说"
BTN_ELDER_SELF = "我自己先说"
BTN_ELDER_FAMILY = "转给家里人"


def ok(data=None, **extra):
    d = {"ok": True, "data": data if data is not None else {}}
    d.update(extra)
    return d


def fail(msg: str, code: str = "bad_request", **extra):
    d = {"ok": False, "error": msg, "code": code, "data": {}}
    d.update(extra)
    return d


# ============================================================
# 一、配置读取（一律读表，代码零写死金额）
# ============================================================

def _plan(db, code: str):
    return (db.query(Pricing)
              .filter(Pricing.plan_code == code)
              .order_by(Pricing.updated_at.desc())
              .first())


def _price(db, code: str) -> float:
    p = _plan(db, code)
    return float(p.price or 0.0) if p else 0.0


def _print_min_pages(db) -> int:
    """实体书页数门槛。读 print_book.remark 里的 pages=NN，未配则兜底 40。"""
    p = _plan(db, PLAN_PRINT)
    remark = (p.remark or "") if p else ""
    for token in remark.replace("，", ",").replace(" ", ",").split(","):
        if token.startswith("pages="):
            try:
                return int(token.split("=", 1)[1])
            except ValueError:
                break
    return PRINT_MIN_PAGES_FALLBACK


def _gift_days(db) -> int:
    p = _plan(db, PLAN_EBOOK)
    d = int(p.period_days or 0) if p else 0
    return d if d > 0 else GIFT_ACCEPT_DAYS_DEFAULT


# ============================================================
# 二、★一人一本锁（R6）—— 谁先开头，册子归谁，但归这个家
# ============================================================

def _my_book(db, user_id: str):
    """我名下（作为书主人）的那一本。一人只有一本。"""
    return (db.query(Ebook)
              .filter(Ebook.owner_id == user_id)
              .order_by(Ebook.created_at.asc())
              .first())


def _paid_book_order(db, user_id: str):
    """我付过钱、且这本书归我的那笔已付款单（用来判断"我是不是已经买过这本"）。"""
    rows = (db.query(Order)
              .filter(Order.user_id == user_id)
              .filter(Order.status == "paid")
              .order_by(Order.created_at.asc())
              .all())
    for o in rows:
        if (o.plan_code or "") in (PLAN_EBOOK, PLAN_PRINT):
            return o
    return None


def book_identity(db, *, user_id: str) -> dict:
    """
    我是谁 → 我这一本册子现在什么状态。前端所有付费判断都走这一个口子。

    返回：
      has_book        我已有一本（不管是自己买还是别人买给我的）
      owner_id        这本册子归谁
      role            owner=我是书主人 / invited=我是被邀请来添的人
      paid_plan       这本书买到的最高档位（''=没付过 / ebook / print_book）
      paid_by_me      这钱是不是我掏的（**只用于收款逻辑，绝不展示给老人**）
      can_write       能不能往里添
      can_edit_others 能不能改别人的（永远 False）
      gift_pending    有笔"为他人付费"还等着人接受
      accept_deadline 接受截止时间
    """
    if not user_id:
        return fail("缺少 user_id", "missing_user_id")

    book = _my_book(db, user_id)
    mine_order = _paid_book_order(db, user_id)
    paid_plan = (mine_order.plan_code if mine_order else "")

    # 别人为我付了钱、我还没接受的那一笔
    gift = (db.query(Order)
              .filter(Order.gift_to_user_id == user_id)
              .filter(Order.status == "paid")
              .filter(Order.refund_state == "")
              .order_by(Order.created_at.desc())
              .first())

    role = "owner" if book else ("invited" if gift else "visitor")
    return ok({
        "user_id": user_id,
        "has_book": bool(book),
        "owner_id": book.owner_id if book else (gift.gift_to_user_id if gift else ""),
        "book_id": book.id if book else "",
        "role": role,
        "paid_plan": paid_plan,
        "paid_by_me": bool(mine_order),
        "can_write": bool(book or gift),
        "can_edit_others": False,
        "gift_pending": bool(gift),
        "accept_deadline": str(gift.accept_deadline or "") if gift else "",
    })


# ============================================================
# 三、★付完钱那两个按钮（R4/R5）—— 9.9 的全部价值所在
# ============================================================

def post_pay_choices(db, *, user_id: str) -> dict:
    """
    付完 9.9 之后，前端立刻调这个接口拿"两个按钮"。
    不问用户是谁，只按入口来源给对应措辞（R5：老人不觉得自己被安排）。

    返回：
      bought        我这笔 9.9 是不是真收到了（没收到 → 不给按钮，别骗人）
      question      一句话：这一页，给谁说？
      buttons       [{key,label,hint}]  最多两个，前端照画，不自己编词
      same_book     我已经有册子了 → 这里提示"接着这本往下说"，不给新书
    """
    if not user_id:
        return fail("缺少 user_id", "missing_user_id")

    order = _paid_book_order(db, user_id)
    if order is None:
        return ok({
            "bought": False,
            "question": "",
            "buttons": [],
            "notice": "这笔钱还没到账，先别让用户往下走",
        })

    book = _my_book(db, user_id)

    # 已经有册子 → 不重开一本（R6），直接告诉他接着这本说
    if book is not None:
        return ok({
            "bought": True,
            "question": "接着说这本？",
            "buttons": [{"key": "continue_self", "label": "我自己接着说", "hint": ""}],
            "same_book": True,
            "book_id": book.id,
        })

    return ok({
        "bought": True,
        "question": "这一页，给谁说？",
        "buttons": [
            {"key": "gift_to_elder", "label": BTN_FOR_KID,
             "hint": "生成一张卡，微信转给爸妈。他点开就能说。"},
            {"key": "self_first", "label": BTN_FOR_SELF,
             "hint": "先自己说一段，随时能把卡转出去。"},
        ],
        "same_book": False,
        "book_id": "",
    })


def choose_path(db, *, user_id: str, choice: str) -> dict:
    """
    用户在两个按钮里点了一个。

      self_first    → 给他开一本（书主人=他），进说话界面
      gift_to_elder → **不立刻开书**，生成一张可转发的邀请卡；
                      谁点开接受，谁就成为书主人（R6/R8）

    铁律：gift 这条路**不能提前把书归给子女**，否则老人说的全落在子女名下，
          和"谁写就算谁的"冲突。
    """
    if not user_id:
        return fail("缺少 user_id", "missing_user_id")
    if choice not in ("self_first", "gift_to_elder"):
        return fail("只有两个选择：self_first / gift_to_elder", "bad_choice")

    order = _paid_book_order(db, user_id)
    if order is None:
        return fail("这笔钱还没到账", "not_paid")

    if choice == "gift_to_elder":
        # 为他人付费：钱记在付款人名下，书等对方接受才成立
        exist = (db.query(Order)
                   .filter(Order.user_id == user_id)
                   .filter(Order.gift_to_user_id != "")
                   .filter(Order.status == "paid")
                   .filter(Order.refund_state == "")
                   .first())
        if exist is None:
            order.gift_to_user_id = "__pending__"   # 占位：卡还没人接
            order.accept_deadline = (
                _dt.datetime.utcnow() + _dt.timedelta(days=_gift_days(db)))
            db.commit()
        return ok({
            "path": "gift",
            "card": {
                "title": "给爸妈留一页",
                "subtitle": "点开就能说，说一句算一句，他自己就是这本书的主人",
                "cta": "我来写",
                "token": order.id,     # 卡片的凭据 = 订单号，扫码/点击后走 accept
            },
            "accept_deadline": str(order.accept_deadline or ""),
        })

    # self_first：当场开书，书主人 = 他自己
    book = _my_book(db, user_id)
    if book is None:
        u = db.get(User, user_id)
        # 书名先留空，成书时按昵称/「我的一生」兜底
        book = Ebook(id=_new_id("ebook"), owner_id=user_id, title="")
        db.add(book)
        db.commit()
        db.refresh(book)
    order.book_id = book.id
    db.commit()
    return ok({
        "path": "self",
        "book_id": book.id,
        "next": "capture",
    })


# ============================================================
# 四、接受邀请（老人/家人点开卡片）
# ============================================================

def accept_gift(db, *, token: str, new_owner_id: str) -> dict:
    """
    有人点开邀请卡并接受（token = 付款订单号）。

    R6：谁写就算谁的 → **接受的人成为书主人**，付款人变成家人（能看能加不能改）。
    R8：超过 accept_deadline → 书不成立，标记待退款，不让接受。
        但**不粗暴拒绝老人**：告诉他"这张卡过期了，让买的人重新发一张"。

    幂等：同一张卡重复接受不重复开书。
    """
    if not token or not new_owner_id:
        return fail("缺少卡片凭据或用户", "missing_args")

    order = db.get(Order, token)
    if order is None or (order.plan_code or "") not in (PLAN_EBOOK, PLAN_PRINT):
        return fail("这张卡无效", "bad_token")
    if order.status != "paid":
        return fail("这张卡还没生效", "not_paid")
    if order.refund_state:
        return fail("这张卡已失效（钱已退回）", "refunded")

    # 已有人接受过 → 直接把书给他看（幂等，不重开）
    if order.book_id:
        book = db.get(Ebook, order.book_id)
        if book is not None:
            return ok({"book_id": book.id, "owner_id": book.owner_id,
                       "idempotent": True, "role": "owner"})

    now = _dt.datetime.utcnow()
    if order.accept_deadline and now > order.accept_deadline:
        order.refund_state = "expired_waiting_refund"
        db.commit()
        return fail("这张卡过期了，让买的人重新发一张", "expired")

    # 一人一本：接受的人如果已经有册子，钱并到他那一本上，不新开
    book = _my_book(db, new_owner_id)
    if book is None:
        book = Ebook(id=_new_id("ebook"), owner_id=new_owner_id, title="")
        db.add(book)
        db.commit()
        db.refresh(book)

    order.book_id = book.id
    order.gift_to_user_id = new_owner_id      # 从 __pending__ 换成真人
    db.commit()
    return ok({
        "book_id": book.id,
        "owner_id": new_owner_id,
        "idempotent": False,
        "role": "owner",
        "payer_still_can_read": True,   # 付款人仍然能看全部（R7）
    })


# ============================================================
# 五、过期退款扫描（R8）—— 供 cron / 手动触发
# ============================================================

def sweep_expired_gifts(db, *, now=None) -> dict:
    """
    扫所有"为他人付费但没人接受、且已过期"的单 → 标记待退款并返回清单。
    真退钱要走微信原路退（凭证到位后接 payment_api），**这里只出清单，不动钱**。
    """
    now = now or _dt.datetime.utcnow()
    rows = (db.query(Order)
              .filter(Order.status == "paid")
              .filter(Order.refund_state == "")
              .filter(Order.gift_to_user_id != "")
              .all())
    expired = []
    for o in rows:
        if o.book_id:
            continue          # 已经有人接受了
        if o.accept_deadline and now > o.accept_deadline:
            o.refund_state = "waiting_refund"
            expired.append({"order_id": o.id, "user_id": o.user_id,
                            "amount": float(o.amount or 0.0)})
    if expired:
        db.commit()
    return ok({"expired": expired, "count": len(expired)})


# ============================================================
# 六、两档产物：9.9 电子册随时可出 / 299 实体书看页数
# ============================================================

def _count_pages(db, owner_id: str) -> int:
    """
    估算这本书的页数（**只用于判断够不够格印成实体书**）。
    口径：每条故事至少 1 页；素材条数按每页 3 条折算。
    这个数字不求精确，只求"答得越多越接近门槛"。
    """
    from models import Clip
    stories = db.query(Story).filter(Story.owner_id == owner_id).all()
    if not stories:
        return 0
    total = 0
    for st in stories:
        n = db.query(Clip).filter(Clip.story_id == st.id).count() or 0
        # 一条故事至少 1 页；素材多则按每页 3 条折算（只用于"够不够格印"）
        total += max(1, (n + 2) // 3)
    return total


def print_eligibility(db, *, owner_id: str) -> dict:
    """
    我能不能买实体书（299）？
      能 → 回答 why 并给按钮
      不能 → 说清楚还差多少（不打击人：告诉他"再答 N 个问题就够了"）
    """
    if not owner_id:
        return fail("缺少 owner_id", "missing_owner_id")
    pages = _count_pages(db, owner_id)
    need = _print_min_pages(db)
    ebook_price = _price(db, PLAN_EBOOK)
    print_price = _price(db, PLAN_PRINT)
    return ok({
        "eligible": pages >= need,
        "pages": pages,
        "need_pages": need,
        "short_by": max(0, need - pages),
        "ebook_price": ebook_price,
        "print_price": print_price,
        "can_buy_ebook": True,      # 9.9 永远可买，不设门槛（R2）
        "notice": ("" if pages >= need
                   else f"再答 {max(0, need - pages)} 件事，就能印成书了"),
    })
