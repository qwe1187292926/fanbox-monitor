"""数据访问层：seen_posts / downloaded / cursor / run_log CRUD。"""
from __future__ import annotations

import sqlite3
import time
from typing import Optional


class Repo:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn

    # -------- seen_posts --------

    def is_seen(self, post_id: str) -> bool:
        cur = self.conn.execute(
            "SELECT 1 FROM seen_posts WHERE post_id = ? LIMIT 1", (post_id,)
        )
        return cur.fetchone() is not None

    def filter_unseen(self, post_ids: list[str]) -> set[str]:
        """返回 post_ids 中尚未入库的子集，便于批量预筛。"""
        if not post_ids:
            return set()
        placeholders = ",".join("?" for _ in post_ids)
        cur = self.conn.execute(
            f"SELECT post_id FROM seen_posts WHERE post_id IN ({placeholders})",
            post_ids,
        )
        seen = {row["post_id"] for row in cur.fetchall()}
        return {p for p in post_ids if p not in seen}

    def mark_seen(
        self,
        post_id: str,
        creator_id: str,
        published_dt: str,
        fee: int,
        title: Optional[str],
    ) -> None:
        self.conn.execute(
            """
            INSERT OR IGNORE INTO seen_posts
            (post_id, creator_id, published_dt, fee, title, first_seen_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (post_id, creator_id, published_dt, fee, title, int(time.time())),
        )

    # -------- downloaded --------

    def is_downloaded(self, url: str) -> bool:
        cur = self.conn.execute(
            "SELECT 1 FROM downloaded WHERE url = ? LIMIT 1", (url,)
        )
        return cur.fetchone() is not None

    def mark_downloaded(
        self,
        url: str,
        post_id: str,
        local_path: str,
        size: Optional[int],
    ) -> None:
        self.conn.execute(
            """
            INSERT OR REPLACE INTO downloaded
            (url, post_id, local_path, size, downloaded_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (url, post_id, local_path, size, int(time.time())),
        )

    # -------- cursor --------

    def get_cursor(self, scope: str) -> tuple[Optional[str], Optional[str]]:
        """返回 (max_published_dt, max_id)；首次抓取时返回 (None, None)。"""
        cur = self.conn.execute(
            "SELECT max_published_dt, max_id FROM cursor WHERE scope = ?",
            (scope,),
        )
        row = cur.fetchone()
        if row is None:
            return None, None
        return row["max_published_dt"], row["max_id"]

    def set_cursor(
        self,
        scope: str,
        max_published_dt: Optional[str],
        max_id: Optional[str],
    ) -> None:
        self.conn.execute(
            """
            INSERT INTO cursor (scope, max_published_dt, max_id, updated_at)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(scope) DO UPDATE SET
                max_published_dt = excluded.max_published_dt,
                max_id           = excluded.max_id,
                updated_at       = excluded.updated_at
            """,
            (scope, max_published_dt, max_id, int(time.time())),
        )

    # -------- run_log --------

    def insert_run_log(
        self,
        started_at: int,
        ended_at: int,
        new_posts: int,
        new_files: int,
        errors: int,
        summary: str,
    ) -> int:
        cur = self.conn.execute(
            """
            INSERT INTO run_log
            (started_at, ended_at, new_posts, new_files, errors, summary)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (started_at, ended_at, new_posts, new_files, errors, summary),
        )
        return cur.lastrowid or 0
