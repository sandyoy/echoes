"""
往事可追忆 - 迁移 v20261031：九个九付费链路（Order 表补 4 字段 + Pricing 两种 plan）

=== 为什么要这次迁移 ===
2026-10-31 sandy 定死新版付费结构（需求书 §9.6 五修）：
  免费层      = 自己说 / AI 问 / 进时间链         → 永久免费，不设限
  9.9 电子册  = 答几个出几个，篇幅不限，只出电子   → plan_code = ebook
  299 实体书  = 答够页数才解锁，含润色成完整故事   → plan_code = print_book
  一次付款，两条路：为自己购买 / 为他人付费（30 天不接受全额退）

原来预留的三种 plan_code（free / single_book / yearly）语义与新结构对不上：
  · 新结构里没有"年费"这一档（sandy：暂不做订阅，后台留开关即可）
  · "电子册"与"实体书"是两个独立产物，不是"单本"的两种形式
故本次：
  1) 保留 free；新增 ebook / print_book；把 single_book 置 inactive（不删，防旧单失联）
  2) Order 表补 4 字段：
       gift_to_user_id   为他人付费时，书归谁（谁写就算谁的）
       book_id           这笔钱买的是哪一本书（一人一本锁）
       refund_state      30 天无人接受 → 退款状态
       accept_deadline   接受截止时刻（付款时刻 + 30 天）
  3) 写入默认价格行（可在后台改，代码零写死）

幂等：重复执行安全（列已存在则跳过，价格行已存在则只补空值，不覆盖后台改过的价）。
"""
import os
import sys
import sqlite3

BASE = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE, "memory_story.db")


def _cols(cur, table):
    return [r[1] for r in cur.execute(f"PRAGMA table_info({table})")]


def migrate(db_path: str = DB_PATH) -> None:
    con = sqlite3.connect(db_path, timeout=10)
    cur = con.cursor()

    # ---------- 1) Order 表补字段 ----------
    have = _cols(cur, "orders")
    adds = {
        "gift_to_user_id": "VARCHAR(128) DEFAULT ''",
        "book_id": "VARCHAR(64) DEFAULT ''",
        "refund_state": "VARCHAR(32) DEFAULT ''",
        "accept_deadline": "DATETIME",
    }
    for name, ddl in adds.items():
        if name not in have:
            cur.execute(f"ALTER TABLE orders ADD COLUMN {name} {ddl}")
            print(f"  + orders.{name}")

    # ---------- 2) Pricing：旧 single_book 停用 ----------
    cur.execute("UPDATE pricing SET active=0 WHERE plan_code='single_book'")
    if cur.rowcount:
        print(f"  ~ pricing.single_book 置 inactive ({cur.rowcount})")

    # ---------- 3) Pricing：写入默认两档（已存在则只补空值） ----------
    defaults = [
        ("free",       "免费使用",   0.0,   0, "自己说 / AI 问 / 进时间链，永久免费"),
        ("ebook",      "电子册",     9.9,   0, "答几个出几个，篇幅不限，可看可转发可导出"),
        ("print_book", "实体书",   299.0,   0, "答够页数解锁+润色成完整故事，含印刷与配送"),
    ]
    for code, name, price, days, remark in defaults:
        row = cur.execute(
            "SELECT id, plan_name, price, remark FROM pricing WHERE plan_code=?",
            (code,)).fetchone()
        if row is None:
            cur.execute(
                "INSERT INTO pricing (id, plan_code, plan_name, price, period_days,"
                " active, remark, updated_at) VALUES (?,?,?,?,?,1,?,datetime('now'))",
                (f"price_{code}", code, name, price, days, remark))
            print(f"  + pricing.{code} = {price}")
        else:
            _id, pname, pprice, prem = row
            if not pname:
                cur.execute("UPDATE pricing SET plan_name=? WHERE id=?", (name, _id))
            if (pprice or 0) == 0 and price > 0:
                cur.execute("UPDATE pricing SET price=? WHERE id=?", (price, _id))
            if not prem:
                cur.execute("UPDATE pricing SET remark=? WHERE id=?", (remark, _id))
            print(f"  = pricing.{code} 已存在（不动后台改过的值）")

    con.commit()

    print("\n迁移后：")
    for r in cur.execute("SELECT plan_code, plan_name, price, active FROM pricing ORDER BY plan_code"):
        print("   ", r)
    print("orders 列:", _cols(cur, "orders"))
    con.close()


if __name__ == "__main__":
    migrate(sys.argv[1] if len(sys.argv) > 1 else DB_PATH)
