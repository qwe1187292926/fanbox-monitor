"""SQLite 连接 + 表结构定义。"""
from __future__ import annotations

import sqlite3
from pathlib import Path

# 表结构 DDL
SCHEMA = [
    """
    CREATE TABLE IF NOT EXISTS seen_posts (
        post_id        TEXT PRIMARY KEY,
        creator_id     TEXT NOT NULL,
        published_dt   TEXT NOT NULL,
        fee            INTEGER NOT NULL,
        title          TEXT,
        first_seen_at  INTEGER NOT NULL
    );
    """,
    "CREATE INDEX IF NOT EXISTS idx_seen_creator_dt ON seen_posts(creator_id, published_dt DESC);",
    """
    CREATE TABLE IF NOT EXISTS downloaded (
        url            TEXT PRIMARY KEY,
        post_id        TEXT NOT NULL,
        local_path     TEXT NOT NULL,
        size           INTEGER,
        downloaded_at  INTEGER NOT NULL
    );
    """,
    "CREATE INDEX IF NOT EXISTS idx_dl_post ON downloaded(post_id);",
    """
    CREATE TABLE IF NOT EXISTS cursor (
        scope             TEXT PRIMARY KEY,
        max_published_dt  TEXT,
        max_id            TEXT,
        updated_at        INTEGER NOT NULL
    );
    """,
    """
    CREATE TABLE IF NOT EXISTS run_log (
        run_id      INTEGER PRIMARY KEY AUTOINCREMENT,
        started_at  INTEGER NOT NULL,
        ended_at    INTEGER NOT NULL,
        new_posts   INTEGER NOT NULL DEFAULT 0,
        new_files   INTEGER NOT NULL DEFAULT 0,
        errors      INTEGER NOT NULL DEFAULT 0,
        summary     TEXT
    );
    """,
]


def open_db(path: Path) -> sqlite3.Connection:
    """打开 SQLite 连接并确保 schema 就位。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path), isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA synchronous = NORMAL")
    conn.execute("PRAGMA foreign_keys = ON")
    for ddl in SCHEMA:
        conn.execute(ddl)
    return conn
