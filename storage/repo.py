"""数据访问层：seen_posts / downloaded / cursor / run_log CRUD。"""
from __future__ import annotations

import json
import sqlite3
import time
from typing import Optional

from models.types import PostMeta

ACCESS_FORBIDDEN_REASON = "access_forbidden"


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

    # -------- skipped_posts --------

    def is_skipped(self, post_id: str, filter_revision: str) -> bool:
        cur = self.conn.execute(
            """
            SELECT 1 FROM skipped_posts
            WHERE post_id = ? AND filter_revision = ?
            LIMIT 1
            """,
            (post_id, filter_revision),
        )
        return cur.fetchone() is not None

    def mark_skipped(
        self,
        post_id: str,
        filter_revision: str,
        creator_id: str,
        published_dt: str,
        fee: int,
        title: Optional[str],
        reason: Optional[str],
        updated_dt: str = "",
        user_name: str = "",
        user_icon_url: str = "",
        tags: Optional[list[str]] = None,
    ) -> None:
        self.conn.execute(
            """
            INSERT OR REPLACE INTO skipped_posts
            (
                post_id, filter_revision, creator_id, published_dt, updated_dt,
                fee, title, user_name, user_icon_url, tags, reason, skipped_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                post_id,
                filter_revision,
                creator_id,
                published_dt,
                updated_dt,
                fee,
                title,
                user_name,
                user_icon_url,
                json.dumps(tags or [], ensure_ascii=False),
                reason,
                int(time.time()),
            ),
        )

    def iter_skipped_for_recheck(self, filter_revision: str) -> list[PostMeta]:
        cur = self.conn.execute(
            """
            SELECT
                s.post_id, s.creator_id, s.user_name, s.user_icon_url, s.title,
                s.fee, s.published_dt, s.updated_dt, s.tags
            FROM skipped_posts s
            WHERE s.filter_revision <> ?
              AND NOT EXISTS (
                  SELECT 1 FROM skipped_posts current
                  WHERE current.post_id = s.post_id
                    AND current.filter_revision = ?
              )
              AND NOT EXISTS (
                  SELECT 1 FROM seen_posts seen
                  WHERE seen.post_id = s.post_id
              )
              AND NOT EXISTS (
                  SELECT 1 FROM skipped_posts newer
                  WHERE newer.post_id = s.post_id
                    AND (
                        newer.skipped_at > s.skipped_at
                        OR (
                            newer.skipped_at = s.skipped_at
                            AND newer.filter_revision > s.filter_revision
                        )
                    )
              )
            ORDER BY s.published_dt DESC
            """,
            (filter_revision, filter_revision),
        )
        posts: list[PostMeta] = []
        for row in cur.fetchall():
            try:
                tags = json.loads(row["tags"] or "[]")
            except json.JSONDecodeError:
                tags = []
            if not isinstance(tags, list):
                tags = []
            posts.append(
                PostMeta(
                    post_id=row["post_id"],
                    creator_id=row["creator_id"],
                    user_name=row["user_name"],
                    user_icon_url=row["user_icon_url"],
                    title=row["title"] or "",
                    fee=row["fee"],
                    published_dt=row["published_dt"],
                    updated_dt=row["updated_dt"],
                    tags=[str(tag) for tag in tags],
                )
            )
        return posts

    def iter_access_forbidden_for_recheck(self) -> list[PostMeta]:
        cur = self.conn.execute(
            """
            SELECT
                s.post_id, s.creator_id, s.user_name, s.user_icon_url, s.title,
                s.fee, s.published_dt, s.updated_dt, s.tags
            FROM skipped_posts s
            WHERE s.reason = ?
              AND NOT EXISTS (
                  SELECT 1 FROM seen_posts seen
                  WHERE seen.post_id = s.post_id
              )
              AND NOT EXISTS (
                  SELECT 1 FROM skipped_posts newer
                  WHERE newer.post_id = s.post_id
                    AND (
                        newer.skipped_at > s.skipped_at
                        OR (
                            newer.skipped_at = s.skipped_at
                            AND newer.filter_revision > s.filter_revision
                        )
                    )
              )
            ORDER BY s.published_dt DESC
            """,
            (ACCESS_FORBIDDEN_REASON,),
        )
        posts: list[PostMeta] = []
        for row in cur.fetchall():
            try:
                tags = json.loads(row["tags"] or "[]")
            except json.JSONDecodeError:
                tags = []
            if not isinstance(tags, list):
                tags = []
            posts.append(
                PostMeta(
                    post_id=row["post_id"],
                    creator_id=row["creator_id"],
                    user_name=row["user_name"],
                    user_icon_url=row["user_icon_url"],
                    title=row["title"] or "",
                    fee=row["fee"],
                    published_dt=row["published_dt"],
                    updated_dt=row["updated_dt"],
                    tags=[str(tag) for tag in tags],
                )
            )
        return posts

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

    # -------- run_lock --------

    def acquire_run_lock(
        self,
        name: str,
        owner: str,
        ttl_sec: int,
    ) -> bool:
        now = int(time.time())
        expires_at = now + max(1, ttl_sec)
        self.conn.execute(
            "DELETE FROM run_lock WHERE name = ? AND expires_at <= ?",
            (name, now),
        )
        cur = self.conn.execute(
            """
            INSERT OR IGNORE INTO run_lock
            (name, owner, acquired_at, expires_at)
            VALUES (?, ?, ?, ?)
            """,
            (name, owner, now, expires_at),
        )
        return cur.rowcount == 1

    def release_run_lock(self, name: str, owner: str) -> None:
        self.conn.execute(
            "DELETE FROM run_lock WHERE name = ? AND owner = ?",
            (name, owner),
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
