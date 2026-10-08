"""
一次性迁移：给 users 表补 prefs 列（采访偏好扩展点，2026-10-08）。
SQLite 的 create_all 不会 ALTER 已存在的表，故对现网库补列。
幂等：已有该列则跳过。
"""
import sqlite3
import os

DB = os.getenv("ECHOES_MIGRATE_DB", "./memory_story.db")


def main():
    if not os.path.exists(DB):
        print(f"[migrate] 库不存在，跳过：{DB}")
        return
    con = sqlite3.connect(DB)
    cols = [r[1] for r in con.execute("PRAGMA table_info(users)")]
    if "prefs" in cols:
        print("[migrate] users.prefs 已存在，无需迁移")
    else:
        con.execute("ALTER TABLE users ADD COLUMN prefs JSON")
        con.commit()
        print("[migrate] 已补 users.prefs 列")
    cols2 = [r[1] for r in con.execute("PRAGMA table_info(users)")]
    print("[migrate] users 列：", cols2)
    con.close()


if __name__ == "__main__":
    main()
