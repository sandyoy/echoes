"""
往事可追忆 · 幂等迁移：给 clips 表加「来路 + 公开/私有」5 个字段（v3.0 §1.3）

背景：v3.0（视角容器版，2026-10-09）§1.3 铁律——第1期起，每条素材必须带：
  provider_id / visibility（默认私有）/ source_type / ref_from_id / ref_author_name
第1期可不用第3期的成书逻辑，但字段一个都不能少。

做法：SQLite 不支持 "ADD COLUMN IF NOT EXISTS"，故先 PRAGMA table_info 探列，
缺哪个补哪个（幂等，可重复跑）。**已存在的库**（memory_story.db）必须跑一次；
全新库由 models.init_db() 直接建全字段，无需本脚本。

用法：  python3 migrate_20261010_clip_provenance.py
环境：  用 /usr/bin/python3（.venv 是空壳，无 sqlalchemy —— 见 README_运行环境.md）
"""
import os
import sqlite3
import sys


def _db_path() -> str:
    url = os.environ.get("DATABASE_URL", "")
    if url.startswith("sqlite:///"):
        return url[len("sqlite:///"):]
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), "memory_story.db")


# 列名 -> SQLite 列定义（枚举以 VARCHAR 存，值 = private/public / origin/quote）
NEW_COLUMNS = {
    "provider_id":     "VARCHAR(128) DEFAULT ''",
    "visibility":      "VARCHAR(16) DEFAULT 'private'",
    "source_type":     "VARCHAR(16) DEFAULT 'origin'",
    "ref_from_id":     "VARCHAR(64)",
    "ref_author_name": "VARCHAR(64) DEFAULT ''",
}


def migrate(db_path: str) -> int:
    print(f"[迁移] 目标库：{db_path}")
    if not os.path.exists(db_path):
        print("[跳过] 库文件不存在（全新库无需迁移，init_db 会建全字段）")
        return 0

    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='clips'")
    if cur.fetchone() is None:
        print("[跳过] 没有 clips 表（全新库无需迁移）")
        conn.close()
        return 0

    cur.execute("PRAGMA table_info(clips)")
    existing = {row[1] for row in cur.fetchall()}

    added = 0
    for col, coldef in NEW_COLUMNS.items():
        if col in existing:
            print(f"[已有] {col} —— 跳过")
            continue
        cur.execute(f"ALTER TABLE clips ADD COLUMN {col} {coldef}")
        print(f"[新增] {col} {coldef}")
        added += 1

    conn.commit()

    # 回填：老素材没有 provider_id 时用 created_by 顶（谁传的即谁提供）
    if "provider_id" in {row[1] for row in cur.execute("PRAGMA table_info(clips)").fetchall()}:
        cur.execute("UPDATE clips SET provider_id = created_by "
                    "WHERE (provider_id IS NULL OR provider_id='') AND created_by IS NOT NULL AND created_by<>''")
        if cur.rowcount:
            print(f"[回填] provider_id 从 created_by 补了 {cur.rowcount} 行")
        conn.commit()

    conn.close()
    print(f"[完成] 本次新增 {added} 列")
    return added


if __name__ == "__main__":
    n = migrate(_db_path())
    print("EXIT=0" if True else "EXIT=1")
    sys.exit(0)
