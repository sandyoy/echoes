"""
数据库模型 — SQLite
"""
import sqlite3
import os
from typing import Optional
from datetime import datetime

DB_PATH = os.path.join(os.path.dirname(__file__), "data", "finance.db")


def get_db() -> sqlite3.Connection:
    os.makedirs(os.path.join(os.path.dirname(__file__), "data"), exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_db():
    conn = get_db()
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            display_name TEXT DEFAULT '',
            created_at TEXT DEFAULT (datetime('now', 'localtime'))
        );

        CREATE TABLE IF NOT EXISTS bills (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            filename TEXT NOT NULL,
            source TEXT DEFAULT 'wechat',
            upload_time TEXT DEFAULT (datetime('now', 'localtime')),
            period_start TEXT,
            period_end TEXT,
            total_income REAL DEFAULT 0,
            total_expense REAL DEFAULT 0,
            income_count INTEGER DEFAULT 0,
            expense_count INTEGER DEFAULT 0,
            FOREIGN KEY (user_id) REFERENCES users(id)
        );

        CREATE TABLE IF NOT EXISTS transactions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            bill_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL,
            time TEXT NOT NULL,
            type TEXT DEFAULT '',
            peer TEXT DEFAULT '',
            goods TEXT DEFAULT '',
            io TEXT NOT NULL,
            amount REAL NOT NULL,
            method TEXT DEFAULT '',
            status TEXT DEFAULT '',
            category TEXT DEFAULT '其他',
            month TEXT,
            year TEXT,
            FOREIGN KEY (bill_id) REFERENCES bills(id) ON DELETE CASCADE,
            FOREIGN KEY (user_id) REFERENCES users(id)
        );

        CREATE INDEX IF NOT EXISTS idx_tx_user ON transactions(user_id);
        CREATE INDEX IF NOT EXISTS idx_tx_month ON transactions(month);
        CREATE INDEX IF NOT EXISTS idx_tx_category ON transactions(category);
    """)
    conn.commit()
    conn.close()


def create_user(username: str, password_hash: str, display_name: str = "") -> int:
    conn = get_db()
    try:
        cur = conn.execute(
            "INSERT INTO users (username, password_hash, display_name) VALUES (?, ?, ?)",
            (username, password_hash, display_name)
        )
        conn.commit()
        return cur.lastrowid
    except sqlite3.IntegrityError:
        return -1
    finally:
        conn.close()


def get_user(username: str) -> Optional[dict]:
    conn = get_db()
    row = conn.execute("SELECT * FROM users WHERE username = ?", (username,)).fetchone()
    conn.close()
    return dict(row) if row else None


def save_bill(user_id: int, filename: str, source: str,
              period_start: str, period_end: str,
              total_income: float, total_expense: float,
              income_count: int, expense_count: int) -> int:
    conn = get_db()
    cur = conn.execute(
        """INSERT INTO bills (user_id, filename, source, period_start, period_end,
           total_income, total_expense, income_count, expense_count)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (user_id, filename, source, period_start, period_end,
         total_income, total_expense, income_count, expense_count)
    )
    conn.commit()
    bill_id = cur.lastrowid
    conn.close()
    return bill_id


def save_transactions(bill_id: int, user_id: int, transactions: list) -> int:
    conn = get_db()
    count = 0
    for t in transactions:
        conn.execute(
            """INSERT INTO transactions (bill_id, user_id, time, type, peer, goods,
               io, amount, method, status, category, month, year)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (bill_id, user_id,
             t.get("time", ""), t.get("type", ""), t.get("peer", ""),
             t.get("goods", ""), t.get("io", ""), t.get("amount", 0),
             t.get("method", ""), t.get("status", ""),
             t.get("category", "其他"), t.get("month", ""), t.get("year", ""))
        )
        count += 1
    conn.commit()
    conn.close()
    return count


def get_bills(user_id: int) -> list:
    conn = get_db()
    rows = conn.execute(
        "SELECT * FROM bills WHERE user_id = ? ORDER BY upload_time DESC",
        (user_id,)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_summary(user_id: int) -> dict:
    conn = get_db()
    # 总收入支出
    row = conn.execute(
        "SELECT SUM(CASE WHEN io='收入' THEN amount ELSE 0 END) as total_income, "
        "SUM(CASE WHEN io='支出' THEN amount ELSE 0 END) as total_expense, "
        "COUNT(CASE WHEN io='收入' THEN 1 END) as income_count, "
        "COUNT(CASE WHEN io='支出' THEN 1 END) as expense_count "
        "FROM transactions WHERE user_id = ?",
        (user_id,)
    ).fetchone()
    
    # 按分类
    cat_rows = conn.execute(
        "SELECT category, io, SUM(amount) as total, COUNT(*) as cnt "
        "FROM transactions WHERE user_id = ? "
        "GROUP BY category, io ORDER BY total DESC",
        (user_id,)
    ).fetchall()

    # 按月
    month_rows = conn.execute(
        "SELECT month, "
        "SUM(CASE WHEN io='收入' THEN amount ELSE 0 END) as income, "
        "SUM(CASE WHEN io='支出' THEN amount ELSE 0 END) as expense "
        "FROM transactions WHERE user_id = ? AND month != '' "
        "GROUP BY month ORDER BY month",
        (user_id,)
    ).fetchall()

    conn.close()

    by_category = {}
    for r in cat_rows:
        d = dict(r)
        cat = d["category"]
        if cat not in by_category:
            by_category[cat] = {"收入": 0.0, "支出": 0.0, "count_income": 0, "count_expense": 0}
        by_category[cat][d["io"]] += d["total"]
        if d["io"] == "收入":
            by_category[cat]["count_income"] = d["cnt"]
        else:
            by_category[cat]["count_expense"] = d["cnt"]

    return {
        "total_income": round(row["total_income"] or 0, 2),
        "total_expense": round(row["total_expense"] or 0, 2),
        "net": round((row["total_income"] or 0) - (row["total_expense"] or 0), 2),
        "income_count": row["income_count"] or 0,
        "expense_count": row["expense_count"] or 0,
        "by_category": by_category,
        "by_month": {r["month"]: {"收入": round(r["income"] or 0, 2), "支出": round(r["expense"] or 0, 2)}
                     for r in month_rows},
    }


def get_transactions(user_id: int, category: str = None, month: str = None,
                     io: str = None, limit: int = 500, offset: int = 0) -> list:
    conn = get_db()
    sql = "SELECT * FROM transactions WHERE user_id = ?"
    params = [user_id]
    if category:
        sql += " AND category = ?"
        params.append(category)
    if month:
        sql += " AND month = ?"
        params.append(month)
    if io:
        sql += " AND io = ?"
        params.append(io)
    sql += " ORDER BY time DESC LIMIT ? OFFSET ?"
    params.extend([limit, offset])
    rows = conn.execute(sql, params).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def delete_bill(bill_id: int, user_id: int) -> bool:
    conn = get_db()
    cur = conn.execute("DELETE FROM bills WHERE id = ? AND user_id = ?", (bill_id, user_id))
    deleted = cur.rowcount > 0
    conn.commit()
    conn.close()
    return deleted
