"""
往事可追忆 - 收费闸门（entitlement）v1.0
建立：2026-10-17（第4期「预留」件，按 v3.0 §9.2/§9.3/§十一 预埋纪律提前落地）

=== 为什么今天做本文件（真缺口，不是凑数）===
10-12 已落 `payment_api.py`（能开价/能下单/能回调置 paid），但**收款链路在最后一步断了**：

  Pricing 表能开价 → Order 能落 pending → 回调置 paid  →  ✅
                                                        ↓
                                        然后呢？**没有任何地方读它**。

全仓库 `grep` 实锤：`Pricing` / `Order` 只在 `payment_api.py` 与 `models.py` 出现，
`book_view_api` / `book_api` / `share_api` **一行都没查过"这个用户到底付没付"**。
结果：**钱收了，权限不发**——「单本电子书收费」「年费会员」两种模式形同虚设，
付费用户与白用用户在后端眼里完全一样。这就是 §9 的"最后一步没接"。

本文件补的就是这一跳：**把 Order 表变成一份"用户买了什么"的判决**（§七之二 新章）。

=== 对照需求书 v3.0（逐条落）===
  §9.1 原则「程序只提供能收的能力；收不收/收多少 = 后台配置」
        → 本文件**不写死任何价格**、不写死"必须付费"；收费是否生效**只看 Pricing.active**
          + 有没有 paid 单。后台把 plan 关掉/删掉 = 全站免费（§9.3「免费↔收费=后台开关」）
  §9.2 三种模式：free / single_book / yearly
        → free         = 永不需要授权（程序基础能力）
        → single_book  = 一次性买断（period_days=0）→ 永久有效
        → yearly       = 年费（period_days=365）→ 到期即失效
  §9.3 改动代价「改价=后台改；免费↔收费=后台开关；加年费=已预留则不用重发版」
        → 生效判据全部**运行时算**：改 Pricing 一行，下一秒全站行为就变，前端/后端零改动
  §8.4 「成书不是终点，是活文档」→ **已买断/年费有效期内续添不再收钱**（见 is_entitled）

=== 五条铁律（与 payment_api / book_api 同）===
1. handler 不自己开 session，db 由调用方传
2. 统一信封 {ok, data, error, code}
3. **零信任前端**：只认库里的 paid 单，**绝不接受请求体传"我买过了"**
4. **绝不误伤**：任何异常/配置缺失 → **放行**（fail-open）。
   sandy 的铁律是"老人不能被卡住"；宁可少收一单，不可让老人自己的书打不开。
5. **绝不臆造**：没买 = 没买，明确告知缺什么、花多少钱、去哪买，不假装成功也不假装失败

=== 与 payment_api 的分工 ===
  payment_api  = 收钱的**动作**（开价/下单/回调/查单）
  entitlement  = 收过钱之后的**判决**（这人能不能用这功能）
  → 两个文件互不 import 反向依赖：entitlement 只读 Order/Pricing 两张表。
"""

import datetime as _dt

from models import Order, Pricing, User

# v3.0 §9.2 三种模式的语义（金额一律不在此，价格只在 Pricing 表）
PLAN_FREE = "free"
PLAN_SINGLE = "single_book"
PLAN_YEARLY = "yearly"

# 年费模式没填 period_days 时的兜底周期（§9.2 写的是"___元/年"）
YEARLY_FALLBACK_DAYS = 365

FREE_FOREVER = "free"          # 该功能不收费（免费模式或后台未开价）
PAID_OK = "paid"               # 已付费且有效期
NEED_PAY = "need_pay"          # 未付费 / 已过期 / 后台已开价

NOT_ENTITLED_NOTICE = "这本书还没解锁，付费后可以看完整版"
EXPIRED_NOTICE = "你的年费会员已到期，续费后可继续看完整版"


# ============================================================
# 一、统一信封（与 payment_api 同形）
# ============================================================

def ok(data=None, **extra):
    d = {"ok": True, "data": data, "error": "", "code": ""}
    d.update(extra)
    return d


def fail(msg: str, code: str = "bad_request", **extra):
    d = {"ok": False, "data": None, "error": msg, "code": code}
    d.update(extra)
    return d


# ============================================================
# 二、内部：读「收费该不该生效」与「这人付没付」
# ============================================================

def _active_paid_plans(db):
    """
    当前**生效中且要收钱**的模式（§9.3 后台开关的运行时真身）。
    规则：
      - Pricing 表里没有该模式       → 未启用（§9.2「表里没有的模式 = 未启用」）
      - active=False                 → 已关（免费↔收费 = 开关）
      - price<=0 或 plan_code=free   → 免费，不必授权
    返回 {plan_code: Pricing 行}
    """
    rows = db.query(Pricing).order_by(Pricing.updated_at.desc()).all()
    out = {}
    for r in rows:
        code = (r.plan_code or "").strip()
        if not code or code == PLAN_FREE:
            continue
        if code in out:          # 同 code 多行时取最新一条（与 payment_api._get_plan 同口径）
            continue
        if not bool(r.active):
            continue
        if float(r.price or 0.0) <= 0.0:
            continue
        out[code] = r
    return out


def _is_paid_order(o, now=None) -> bool:
    """一张订单是否构成有效授权：必须是 paid（§ callback 置的），且未过期。"""
    if o is None:
        return False
    if (o.status or "") != "paid":
        return False
    now = now or _dt.datetime.utcnow()
    # 年费：paid_at + period_days 到期
    if (o.plan_code or "") == PLAN_YEARLY:
        if o.paid_at is None:
            return False
        days = YEARLY_FALLBACK_DAYS
        plan = getattr(o, "_plan_days", None)
        if plan:
            days = int(plan)
        try:
            return (o.paid_at + _dt.timedelta(days=days)) > now
        except (TypeError, OverflowError):
            return True       # 脏数据不误伤（铁律4）
    return True               # 一次性买断：永久


def _paid_orders(db, user_id: str):
    return (db.query(Order)
              .filter(Order.user_id == user_id)
              .filter(Order.status == "paid")
              .order_by(Order.created_at.desc())
              .all())


# ============================================================
# 三、★核心判决：这人对这个功能，到底免不免费 / 买没买
# ============================================================

def is_entitled(db, *, user_id: str, feature: str = "ebook_read") -> dict:
    """
    唯一判决入口（其它模块只准调这个，不许自己查 Order 表）。

    返回 data：
      paid_required   bool   —— 该项功能当前收不收费（由后台 Pricing 决定）
      entitled        bool   —— 这人现在能不能用
      reason          str    —— free / paid / not_paid / expired / no_user / fail_open
      plan_code       str    —— 需要买的/已买的模式（single_book 优先，其次 yearly）
      notice          str    —— 给前端直接显示的话（人话，非错误码）
    **绝不误伤（铁律4）**：任何异常 → entitled=True, reason=fail_open，
      并在返回里带 warning=fail_open 让日志能看见（不是静默吞）。
    """
    try:
        plans = _active_paid_plans(db)

        # 全站没有生效的收费模式 → 免费（§9.3 后台开关一关，全站免费）
        if not plans:
            return ok({"paid_required": False, "entitled": True,
                       "reason": FREE_FOREVER, "plan_code": "",
                       "notice": ""})

        if not user_id:
            return ok({"paid_required": True, "entitled": False,
                       "reason": "no_user", "plan_code": "",
                       "notice": "登录后可以购买并查看完整版"})

        # 该用户在生效模式里有没有有效 paid 单
        orders = _paid_orders(db, user_id)
        expired = False
        for o in orders:
            code = (o.plan_code or "")
            if code not in plans:
                continue          # 买了但该模式已被后台关掉 → 不算（后台说了算）
            plan = plans[code]
            o._plan_days = int(plan.period_days or 0) or (YEARLY_FALLBACK_DAYS if code == PLAN_YEARLY else 0)
            if _is_paid_order(o):
                return ok({"paid_required": True, "entitled": True,
                           "reason": PAID_OK, "plan_code": code,
                           "valid_until": str((o.paid_at or _dt.datetime.utcnow())
                                              + _dt.timedelta(days=o._plan_days or 0))
                                             if o._plan_days else "永久",
                           "notice": ""})
            expired = True

        # 要买哪一个：买断优先（一次性最省）
        need = PLAN_SINGLE if PLAN_SINGLE in plans else sorted(plans)[0]
        price = float(plans[need].price or 0.0)
        return ok({"paid_required": True, "entitled": False,
                   "reason": "expired" if expired else "not_paid",
                   "plan_code": need, "plan_name": plans[need].plan_name or need,
                   "price": price,
                   "notice": EXPIRED_NOTICE if expired else NOT_ENTITLED_NOTICE})
    except Exception:            # noqa: BLE001 —— 铁律4：绝不因收费判断把老人挡在自己书的门外
        return ok({"paid_required": False, "entitled": True, "reason": "fail_open",
                   "plan_code": "", "notice": ""}, warning="fail_open")


def require_entitled(db, *, user_id: str, feature: str = "ebook_read") -> dict:
    """判决 + 不通过时直接返回统一 fail 信封（handler 里一行拦截用）。"""
    d = is_entitled(db, user_id=user_id, feature=feature)
    if d["data"]["entitled"]:
        return d
    return fail(d["data"]["notice"] or NOT_ENTITLED_NOTICE, NEED_PAY,
                entitlement=d["data"])


# ============================================================
# 四、★书的口子：只卡「完整版渲染」，绝不卡老人自己的素材
# ============================================================

def book_lock_state(db, *, owner_id: str) -> dict:
    """
    书的锁定状态（前端据此决定：直接打开 / 显示预览+解锁按钮）。

    铁律（sandy 视角）：**老人的素材一条都不能锁**——他录的、他写的，看得到。
      锁的只是「成书形态的完整渲染」（排版/印刷件/全部页），
      且**只锁自己的书**；分享出去的公开篇走 share_api，与收费无关（§8之二.3）。
    """
    d = is_entitled(db, user_id=owner_id, feature="ebook_read")
    s = dict(d["data"])
    s["locked"] = not s["entitled"] and s["paid_required"]
    s["can_preview"] = True      # 永远允许预览（不能连预览都不给，那不叫收费叫要挟）
    return ok(s)
