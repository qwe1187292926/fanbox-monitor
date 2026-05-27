import sqlite3
import unittest
from pathlib import Path
from unittest.mock import patch

import download_post
import main
from api.exceptions import FanboxAPIError
from config import Settings, load_settings
from crawler.supporting import iter_new_supporting
from models.types import CreatorRule, DownloadResult, FileItem, PostMeta
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


class _FakeClient:
    def __init__(self, *args, **kwargs) -> None:
        self.session = object()


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

    def test_load_settings_supports_log_level_and_clamps_concurrency(self):
        env = {
            "FANBOX_SESSION": "session",
            "FANBOX_LOG_LEVEL": "debug",
            "FANBOX_CONCURRENCY": "0",
        }
        with patch.dict("os.environ", env, clear=True):
            settings = load_settings(Path("."))

        self.assertEqual(settings.log_level, "DEBUG")
        self.assertEqual(settings.concurrency, 1)

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
