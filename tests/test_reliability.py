import sqlite3
import unittest
from pathlib import Path
from unittest.mock import patch

import download_post
import main
from api.exceptions import FanboxAPIError, FanboxForbiddenError
from config import Settings, filter_revision, load_settings
from crawler.incremental import filter_and_mark
from crawler.supporting import iter_new_supporting
from models.types import CreatorRule, DownloadResult, FileItem, PostMeta
from notify.push import format_run_summary
from storage.db import SCHEMA
from storage.repo import Repo


class _NonClosingConnection:
    def __init__(self) -> None:
        self.conn = sqlite3.connect(":memory:", isolation_level=None)
        self.conn.row_factory = sqlite3.Row
        for ddl in SCHEMA:
            self.conn.execute(ddl)

    def execute(self, *args, **kwargs):
        return self.conn.execute(*args, **kwargs)

    def close(self) -> None:
        pass

    def real_close(self) -> None:
        self.conn.close()


def _settings(root: Path) -> Settings:
    return Settings(
        session="session",
        user_agent="ua",
        proxy=None,
        download_dir=root,
        db_path=root / "fanbox.db",
        log_level="CRITICAL",
        mode_supporting=True,
        mode_following=False,
        interval_sec=0.0,
        concurrency=1,
        ext_whitelist={"jpg"},
        fee_min=0,
        fee_max=None,
        date_after=None,
        name_rule="{post_id}/{index}",
        notify_min_new=0,
        first_run_max_posts=50,
        post_403_retries=0,
        post_403_backoff_base=0.0,
        forbidden_fee_infer_threshold=2,
        run_lock_ttl_sec=3600,
        bark_server="https://api.day.app",
        bark_device_key="",
        bark_group="FanboxMonitor",
        bark_sound="",
        creator_rules_source=None,
        default_creator_rule=CreatorRule(),
        creator_rules={},
    )


def _meta(post_id: str = "post1") -> PostMeta:
    return PostMeta(
        post_id=post_id,
        creator_id="creator1",
        user_name="Creator",
        user_icon_url="",
        title="Title",
        fee=0,
        published_dt="2026-01-01T00:00:00+00:00",
        updated_dt="2026-01-01T00:00:00+00:00",
        tags=[],
    )


def _item(post_id: str = "post1") -> FileItem:
    return FileItem(
        post_id=post_id,
        creator_id="creator1",
        user_name="Creator",
        title="Title",
        fee=0,
        published_dt="2026-01-01T00:00:00+00:00",
        index=1,
        name="image",
        ext="jpg",
        url=f"https://example.invalid/{post_id}.jpg",
    )


def _raw_post(post_id: str, published_dt: str, fee: int = 0) -> dict:
    return {
        "id": post_id,
        "creatorId": "creator1",
        "user": {"name": "Creator", "iconUrl": ""},
        "title": f"Title {post_id}",
        "feeRequired": fee,
        "publishedDatetime": published_dt,
        "updatedDatetime": published_dt,
        "tags": [],
    }


class _FakeClient:
    def __init__(self, *args, **kwargs) -> None:
        self.session = object()


class _PagedClient(_FakeClient):
    def __init__(self, pages: dict[str, dict]) -> None:
        super().__init__()
        self.pages = pages
        self.requested: list[str] = []

    def get(self, url: str):
        self.requested.append(url)
        return self.pages[url]


class ReliabilityTests(unittest.TestCase):
    def _run_with_patches(self, root: Path, collect_result, download_result):
        meta = _meta()
        settings = _settings(root)
        db = _NonClosingConnection()
        with patch.object(main, "load_settings", return_value=settings), \
             patch.object(main, "setup_logging"), \
             patch.object(main, "open_db", return_value=db), \
             patch.object(main, "FanboxClient", _FakeClient), \
             patch.object(main, "_post_streams", return_value=iter([meta])), \
             patch.object(main, "_collect_files_for_post", return_value=collect_result), \
             patch.object(main, "download_file", return_value=download_result), \
             patch.object(main, "push_run_results"), \
             patch.object(main, "send_qinglong"):
            return main.run(), settings, db

    def test_successful_download_marks_downloaded_and_seen(self):
        item = _item()
        code, _, db = self._run_with_patches(
            Path("."),
            collect_result=[item],
            download_result=DownloadResult(
                item=item,
                success=True,
                local_path="downloads/post1/1.jpg",
                size=123,
            ),
        )
        try:
            self.assertEqual(code, 0)
            self.assertEqual(
                db.execute("SELECT COUNT(*) FROM downloaded").fetchone()[0], 1
            )
            self.assertEqual(
                db.execute("SELECT COUNT(*) FROM seen_posts").fetchone()[0], 1
            )
        finally:
            db.real_close()

    def test_failed_download_does_not_mark_seen(self):
        item = _item()
        code, _, db = self._run_with_patches(
            Path("."),
            collect_result=[item],
            download_result=DownloadResult(
                item=item,
                success=False,
                error="HTTP 500",
            ),
        )
        try:
            self.assertEqual(code, 1)
            self.assertEqual(
                db.execute("SELECT COUNT(*) FROM downloaded").fetchone()[0], 0
            )
            self.assertEqual(
                db.execute("SELECT COUNT(*) FROM seen_posts").fetchone()[0], 0
            )
        finally:
            db.real_close()

    def test_detail_fetch_failure_does_not_mark_seen(self):
        code, _, db = self._run_with_patches(
            Path("."),
            collect_result=None,
            download_result=DownloadResult(item=_item(), success=True),
        )
        try:
            self.assertEqual(code, 1)
            self.assertEqual(
                db.execute("SELECT COUNT(*) FROM seen_posts").fetchone()[0], 0
            )
        finally:
            db.real_close()

    def test_empty_file_list_marks_skipped_not_seen(self):
        code, settings, db = self._run_with_patches(
            Path("."),
            collect_result=[],
            download_result=DownloadResult(item=_item(), success=True),
        )
        try:
            self.assertEqual(code, 0)
            self.assertEqual(
                db.execute("SELECT COUNT(*) FROM seen_posts").fetchone()[0], 0
            )
            row = db.execute(
                "SELECT filter_revision, reason FROM skipped_posts WHERE post_id = ?",
                ("post1",),
            ).fetchone()
            self.assertIsNotNone(row)
            self.assertEqual(row["filter_revision"], filter_revision(settings))
            self.assertEqual(row["reason"], "no_accepted_files")
        finally:
            db.real_close()

    def test_post_403_raises_access_forbidden(self):
        settings = _settings(Path("."))
        with patch.object(main, "get_post", side_effect=FanboxForbiddenError("403")):
            with self.assertRaises(main.PostAccessForbidden):
                main._collect_files_for_post(_FakeClient(), settings, _meta())

    def test_access_forbidden_marks_retryable_not_seen(self):
        settings = _settings(Path("."))
        db = _NonClosingConnection()
        try:
            with patch.object(main, "load_settings", return_value=settings), \
                 patch.object(main, "setup_logging"), \
                 patch.object(main, "open_db", return_value=db), \
                 patch.object(main, "FanboxClient", _FakeClient), \
                 patch.object(main, "_post_streams", return_value=iter([_meta()])), \
                 patch.object(
                     main,
                     "_collect_files_for_post",
                     side_effect=main.PostAccessForbidden("403"),
                 ), \
                 patch.object(main, "download_file") as download_file, \
                 patch.object(main, "push_run_results"), \
                 patch.object(main, "send_qinglong"):
                self.assertEqual(main.run(), 0)

            self.assertEqual(download_file.call_count, 0)
            self.assertEqual(
                db.execute("SELECT COUNT(*) FROM seen_posts").fetchone()[0], 0
            )
            row = db.execute(
                "SELECT reason FROM skipped_posts WHERE post_id = ?",
                ("post1",),
            ).fetchone()
            self.assertIsNotNone(row)
            self.assertEqual(row["reason"], main.ACCESS_FORBIDDEN_REASON)
        finally:
            db.real_close()

    def test_run_lock_blocks_overlapping_run_and_releases_after_success(self):
        item = _item()
        settings = _settings(Path("."))
        db = _NonClosingConnection()
        repo = Repo(db)
        self.assertTrue(repo.acquire_run_lock("fanbox_monitor", "other", 3600))
        with patch.object(main, "load_settings", return_value=settings), \
             patch.object(main, "setup_logging"), \
             patch.object(main, "open_db", return_value=db), \
             patch.object(main, "FanboxClient", _FakeClient), \
             patch.object(main, "_post_streams", return_value=iter([_meta()])), \
             patch.object(main, "_collect_files_for_post", return_value=[item]), \
             patch.object(main, "download_file", return_value=DownloadResult(item=item, success=True)), \
             patch.object(main, "push_run_results"), \
             patch.object(main, "send_qinglong"):
            self.assertEqual(main.run(), 0)
        try:
            self.assertEqual(
                db.execute("SELECT COUNT(*) FROM downloaded").fetchone()[0], 0
            )
            repo.release_run_lock("fanbox_monitor", "other")

            with patch.object(main, "load_settings", return_value=settings), \
                 patch.object(main, "setup_logging"), \
                 patch.object(main, "open_db", return_value=db), \
                 patch.object(main, "FanboxClient", _FakeClient), \
                 patch.object(main, "_post_streams", return_value=iter([_meta()])), \
                 patch.object(main, "_collect_files_for_post", return_value=[item]), \
                 patch.object(
                     main,
                     "download_file",
                     return_value=DownloadResult(
                         item=item,
                         success=True,
                         local_path="downloads/post1/1.jpg",
                         size=123,
                     ),
                 ), \
                 patch.object(main, "push_run_results"), \
                 patch.object(main, "send_qinglong"):
                self.assertEqual(main.run(), 0)
            self.assertEqual(
                db.execute("SELECT COUNT(*) FROM downloaded").fetchone()[0], 1
            )
            self.assertEqual(
                db.execute("SELECT COUNT(*) FROM run_lock").fetchone()[0], 0
            )
        finally:
            db.real_close()

    def test_supporting_home_failure_propagates(self):
        db = _NonClosingConnection()
        repo = Repo(db)
        settings = _settings(Path("."))
        try:
            with patch(
                "crawler.supporting.list_supporting_posts",
                side_effect=FanboxAPIError("boom"),
            ):
                with self.assertRaises(FanboxAPIError):
                    list(iter_new_supporting(_FakeClient(), repo, settings))
        finally:
            db.real_close()

    def test_filter_skip_is_re_evaluated_when_rules_change(self):
        db = _NonClosingConnection()
        repo = Repo(db)
        meta = _meta()
        settings = _settings(Path("."))
        settings.fee_min = 100
        try:
            self.assertFalse(filter_and_mark(meta, repo, settings))
            self.assertEqual(
                db.execute("SELECT COUNT(*) FROM seen_posts").fetchone()[0], 0
            )
            first_revision = filter_revision(settings)
            self.assertTrue(repo.is_skipped(meta.post_id, first_revision))

            settings.fee_min = 0
            second_revision = filter_revision(settings)
            self.assertNotEqual(first_revision, second_revision)
            self.assertFalse(repo.is_skipped(meta.post_id, second_revision))
            self.assertTrue(filter_and_mark(meta, repo, settings))
        finally:
            db.real_close()

    def test_post_streams_rechecks_previous_filter_skips(self):
        db = _NonClosingConnection()
        repo = Repo(db)
        old_settings = _settings(Path("."))
        old_settings.fee_min = 100
        meta = _meta()
        try:
            self.assertFalse(filter_and_mark(meta, repo, old_settings))

            new_settings = _settings(Path("."))
            new_settings.mode_supporting = False
            posts = list(main._post_streams(_FakeClient(), repo, new_settings))

            self.assertEqual([post.post_id for post in posts], ["post1"])
            self.assertFalse(repo.is_skipped("post1", filter_revision(new_settings)))
        finally:
            db.real_close()

    def test_post_streams_rechecks_current_access_forbidden(self):
        db = _NonClosingConnection()
        repo = Repo(db)
        settings = _settings(Path("."))
        settings.mode_supporting = False
        meta = _meta()
        try:
            repo.mark_skipped(
                meta.post_id,
                filter_revision(settings),
                meta.creator_id,
                meta.published_dt,
                meta.fee,
                meta.title,
                main.ACCESS_FORBIDDEN_REASON,
                updated_dt=meta.updated_dt,
                user_name=meta.user_name,
                user_icon_url=meta.user_icon_url,
                tags=meta.tags,
            )

            posts = list(main._post_streams(_FakeClient(), repo, settings))

            self.assertEqual([post.post_id for post in posts], ["post1"])
        finally:
            db.real_close()

    def test_access_forbidden_history_can_download_after_permission_changes(self):
        db = _NonClosingConnection()
        repo = Repo(db)
        settings = _settings(Path("."))
        settings.mode_supporting = False
        meta = _meta()
        item = _item()
        try:
            repo.mark_skipped(
                meta.post_id,
                filter_revision(settings),
                meta.creator_id,
                meta.published_dt,
                meta.fee,
                meta.title,
                main.ACCESS_FORBIDDEN_REASON,
                updated_dt=meta.updated_dt,
                user_name=meta.user_name,
                user_icon_url=meta.user_icon_url,
                tags=meta.tags,
            )

            with patch.object(main, "load_settings", return_value=settings), \
                 patch.object(main, "setup_logging"), \
                 patch.object(main, "open_db", return_value=db), \
                 patch.object(main, "FanboxClient", _FakeClient), \
                 patch.object(main, "_collect_files_for_post", return_value=[item]), \
                 patch.object(
                     main,
                     "download_file",
                     return_value=DownloadResult(
                         item=item,
                         success=True,
                         local_path="downloads/post1/1.jpg",
                         size=123,
                     ),
                 ), \
                 patch.object(main, "push_run_results"), \
                 patch.object(main, "send_qinglong"):
                self.assertEqual(main.run(), 0)

            self.assertEqual(
                db.execute("SELECT COUNT(*) FROM downloaded").fetchone()[0], 1
            )
            self.assertEqual(
                db.execute("SELECT COUNT(*) FROM seen_posts").fetchone()[0], 1
            )
        finally:
            db.real_close()

    def test_forbidden_fee_inference_skips_same_or_higher_fee_this_run(self):
        settings = _settings(Path("."))
        db = _NonClosingConnection()
        metas = [_meta("p1"), _meta("p2"), _meta("p3"), _meta("p4")]
        metas[0].fee = 500
        metas[1].fee = 500
        metas[2].fee = 1000
        metas[3].fee = 100
        try:
            with patch.object(main, "load_settings", return_value=settings), \
                 patch.object(main, "setup_logging"), \
                 patch.object(main, "open_db", return_value=db), \
                 patch.object(main, "FanboxClient", _FakeClient), \
                 patch.object(main, "_post_streams", return_value=iter(metas)), \
                 patch.object(
                     main,
                     "_collect_files_for_post",
                     side_effect=[
                         main.PostAccessForbidden("403"),
                         main.PostAccessForbidden("403"),
                         [],
                     ],
                 ) as collect_files, \
                 patch.object(main, "download_file") as download_file, \
                 patch.object(main, "push_run_results"), \
                 patch.object(main, "send_qinglong"):
                self.assertEqual(main.run(), 0)

            self.assertEqual(collect_files.call_count, 3)
            self.assertEqual(download_file.call_count, 0)
            rows = {
                row["post_id"]: row["reason"]
                for row in db.execute(
                    "SELECT post_id, reason FROM skipped_posts"
                ).fetchall()
            }
            self.assertEqual(rows["p1"], main.ACCESS_FORBIDDEN_REASON)
            self.assertEqual(rows["p2"], main.ACCESS_FORBIDDEN_REASON)
            self.assertEqual(rows["p3"], main.ACCESS_FORBIDDEN_REASON)
            self.assertEqual(rows["p4"], "no_accepted_files")
        finally:
            db.real_close()

    def test_supporting_cursor_stops_at_previous_boundary_and_updates_scope(self):
        db = _NonClosingConnection()
        repo = Repo(db)
        settings = _settings(Path("."))
        revision = filter_revision(settings)
        repo.set_cursor("supporting:" + revision, "2026-01-02T00:00:00+00:00", "old")
        pages = [
            {
                "body": {
                    "items": [
                        _raw_post("new", "2026-01-03T00:00:00+00:00"),
                        _raw_post("old", "2026-01-02T00:00:00+00:00"),
                    ],
                    "nextUrl": "next",
                }
            }
        ]
        try:
            with patch("crawler.supporting.list_supporting_posts", return_value=pages[0]):
                posts = list(iter_new_supporting(_FakeClient(), repo, settings))

            self.assertEqual([post.post_id for post in posts], ["new"])
            cursor_dt, cursor_id = repo.get_cursor("supporting:" + revision)
            self.assertEqual(cursor_dt, "2026-01-03T00:00:00+00:00")
            self.assertEqual(cursor_id, "new")
        finally:
            db.real_close()

    def test_supporting_continues_past_seen_page_without_cursor(self):
        db = _NonClosingConnection()
        repo = Repo(db)
        settings = _settings(Path("."))
        repo.mark_seen(
            "seen",
            "creator1",
            "2026-01-03T00:00:00+00:00",
            0,
            "Seen",
        )
        first_page = {
            "body": {
                "items": [_raw_post("seen", "2026-01-03T00:00:00+00:00")],
                "nextUrl": "next",
            }
        }
        second_page = {
            "body": {
                "items": [_raw_post("new", "2026-01-02T00:00:00+00:00")],
                "nextUrl": None,
            }
        }
        client = _PagedClient({"next": second_page})
        try:
            with patch("crawler.supporting.list_supporting_posts", return_value=first_page):
                posts = list(iter_new_supporting(client, repo, settings))

            self.assertEqual(client.requested, ["next"])
            self.assertEqual([post.post_id for post in posts], ["new"])
            cursor_dt, cursor_id = repo.get_cursor("supporting:" + filter_revision(settings))
            self.assertEqual(cursor_dt, "2026-01-03T00:00:00+00:00")
            self.assertEqual(cursor_id, "seen")
        finally:
            db.real_close()

    def test_load_settings_supports_log_level_and_clamps_concurrency(self):
        env = {
            "FANBOX_SESSION": "session",
            "FANBOX_LOG_LEVEL": "debug",
            "FANBOX_CONCURRENCY": "0",
            "FANBOX_LANG": "en",
        }
        with patch.dict("os.environ", env, clear=True):
            settings = load_settings(Path("."))

        self.assertEqual(settings.log_level, "DEBUG")
        self.assertEqual(settings.concurrency, 1)
        self.assertEqual(settings.lang, "en-US")

    def test_proxy_redaction_hides_credentials(self):
        self.assertEqual(main._redact_proxy(None), "未配置")
        self.assertEqual(
            main._redact_proxy("http://user:pass@proxy.example:8080"),
            "http://***:***@proxy.example:8080",
        )
        self.assertEqual(
            main._redact_proxy("socks5://proxy.example:1080"),
            "socks5://proxy.example:1080",
        )

    def test_format_run_summary_uses_requested_language(self):
        stats = main.RunStats(
            started_at=100,
            ended_at=105,
            new_posts=2,
            new_files=3,
            skipped_files=1,
            errors=0,
        )

        title, body = format_run_summary(stats, "en-US")

        self.assertEqual(title, "Fanbox new posts 2 / files 3")
        self.assertIn("New files: 3", body)
        self.assertIn("Duration: 5s", body)

    def test_format_run_summary_simplifies_common_tls_errors(self):
        stats = main.RunStats(
            started_at=100,
            ended_at=105,
            errors=1,
            error_messages=[
                "unhandled: 请求失败: https://api.fanbox.cc/post.listSupporting - "
                "Failed to perform, curl: (35) TLS connect error: "
                "error:00000000:invalid library (0):OPENSSL_internal:invalid library (0)."
            ],
        )

        _, body = format_run_summary(stats, "zh-CN")

        self.assertIn("网络/TLS 连接失败", body)
        self.assertIn("可能原因:", body)
        self.assertIn("https://api.fanbox.cc/post.listSupporting", body)
        self.assertIn("curl 35", body)
        self.assertNotIn("OPENSSL_internal:invalid library", body)

    def test_extract_post_id_accepts_common_inputs(self):
        self.assertEqual(download_post.extract_post_id("123456"), "123456")
        self.assertEqual(
            download_post.extract_post_id(
                "https://www.fanbox.cc/@creator/posts/123456"
            ),
            "123456",
        )
        self.assertEqual(
            download_post.extract_post_id("https://creator.fanbox.cc/posts/987654"),
            "987654",
        )
        self.assertEqual(
            download_post.extract_post_id("https://api.fanbox.cc/post.info?postId=42"),
            "42",
        )

    def test_single_post_download_records_downloaded_without_seen_by_default(self):
        db = _NonClosingConnection()
        settings = _settings(Path("."))
        item = _item()
        try:
            with patch.object(download_post, "open_db", return_value=db), \
                 patch.object(download_post, "FanboxClient", _FakeClient), \
                 patch.object(download_post, "collect_files", return_value=[item]), \
                 patch.object(
                     download_post,
                     "download_file",
                     return_value=DownloadResult(
                         item=item,
                         success=True,
                         local_path="downloads/post1/1.jpg",
                         size=123,
                     ),
                 ):
                downloaded, skipped, errors = download_post.download_post(
                    settings, "post1"
                )

            self.assertEqual((downloaded, skipped, errors), (1, 0, 0))
            self.assertEqual(
                db.execute("SELECT COUNT(*) FROM downloaded").fetchone()[0], 1
            )
            self.assertEqual(
                db.execute("SELECT COUNT(*) FROM seen_posts").fetchone()[0], 0
            )
        finally:
            db.real_close()

    def test_single_post_download_can_mark_seen(self):
        db = _NonClosingConnection()
        settings = _settings(Path("."))
        item = _item()
        try:
            with patch.object(download_post, "open_db", return_value=db), \
                 patch.object(download_post, "FanboxClient", _FakeClient), \
                 patch.object(download_post, "collect_files", return_value=[item]), \
                 patch.object(
                     download_post,
                     "download_file",
                     return_value=DownloadResult(
                         item=item,
                         success=True,
                         local_path="downloads/post1/1.jpg",
                         size=123,
                     ),
                 ):
                downloaded, skipped, errors = download_post.download_post(
                    settings, "post1", mark_seen=True
                )

            self.assertEqual((downloaded, skipped, errors), (1, 0, 0))
            self.assertEqual(
                db.execute("SELECT COUNT(*) FROM seen_posts").fetchone()[0], 1
            )
        finally:
            db.real_close()


if __name__ == "__main__":
    unittest.main()
