"""Download one Fanbox post by URL or post id.

Usage:
    python download_post.py https://www.fanbox.cc/@creator/posts/123456
    python download_post.py https://creator.fanbox.cc/posts/123456
    python download_post.py 123456
"""
from __future__ import annotations

import argparse
import logging
import re
import sys
from pathlib import Path
from typing import Optional
from urllib.parse import urlparse

from api.client import FanboxClient
from api.endpoints import get_post
from api.exceptions import FanboxAuthError, FanboxError
from config import Settings, load_settings
from crawler.interval import CrawlInterval
from downloader.http_downloader import download_file
from i18n import env_lang, t
from models.types import DownloadResult, FileItem
from parser.filter import accept_file
from parser.post_parser import parse_post
from storage.db import open_db
from storage.repo import Repo

logger = logging.getLogger("fanbox_download_post")


def configure_stdio() -> None:
    for stream in (sys.stdout, sys.stderr):
        reconfig = getattr(stream, "reconfigure", None)
        if reconfig is not None:
            try:
                reconfig(encoding="utf-8", errors="replace")
            except Exception:
                pass


def setup_logging(level: str) -> None:
    configure_stdio()
    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        handlers=[logging.StreamHandler(sys.stdout)],
        force=True,
    )


def extract_post_id(value: str) -> str:
    """Extract post id from a Fanbox post URL or return a raw numeric id."""
    lang = env_lang()
    raw = value.strip()
    if not raw:
        raise ValueError(t(lang, "single.empty_post"))
    if raw.isdigit():
        return raw

    parsed = urlparse(raw)
    if not parsed.scheme or not parsed.netloc:
        raise ValueError(t(lang, "single.invalid_post", value=value))

    match = re.search(r"(?:^|/)posts/(\d+)(?:/|$)", parsed.path)
    if match:
        return match.group(1)

    query_match = re.search(r"(?:^|[?&])postId=(\d+)(?:&|$)", parsed.query)
    if query_match:
        return query_match.group(1)

    raise ValueError(t(lang, "single.parse_failed", value=value))


def collect_files(client: FanboxClient, settings: Settings, post_id: str) -> list[FileItem]:
    detail = get_post(client, post_id)
    body = detail.get("body") if isinstance(detail, dict) else None
    if not isinstance(body, dict):
        raise RuntimeError(t(settings.lang, "single.invalid_body", post_id=post_id))
    files = parse_post(body)
    return [item for item in files if accept_file(item, settings.ext_whitelist)]


def download_post(
    settings: Settings,
    post_id: str,
    force: bool = False,
    mark_seen: bool = False,
) -> tuple[int, int, int]:
    """Download one post.

    Returns (downloaded, skipped, errors).
    """
    settings.download_dir.mkdir(parents=True, exist_ok=True)
    conn = open_db(settings.db_path)
    repo = Repo(conn)
    client = FanboxClient(
        session_cookie=settings.session,
        user_agent=settings.user_agent,
        interval=CrawlInterval(settings.interval_sec, settings.lang),
        proxy=settings.proxy,
        lang=settings.lang,
    )

    downloaded = 0
    skipped = 0
    errors = 0
    files: list[FileItem] = []

    try:
        files = collect_files(client, settings, post_id)
        if not files:
            logger.info(t(settings.lang, "single.no_files", post_id=post_id))
            return downloaded, skipped, errors

        logger.info(t(settings.lang, "single.files_found", post_id=post_id, count=len(files)))
        for item in files:
            if not force and repo.is_downloaded(item.url):
                logger.info(t(settings.lang, "single.skip_registered", url=item.url))
                skipped += 1
                continue

            result = download_file(client.session, settings, item)
            if result.success:
                repo.mark_downloaded(
                    item.url,
                    item.post_id,
                    result.local_path or "",
                    result.size,
                )
                if result.skipped_reason == "existing":
                    skipped += 1
                else:
                    downloaded += 1
            else:
                errors += 1
                logger.error(
                    t(settings.lang, "single.download_failed", url=item.url, error=result.error)
                )

        if mark_seen and errors == 0:
            sample = files[0]
            repo.mark_seen(
                sample.post_id,
                sample.creator_id,
                sample.published_dt,
                sample.fee,
                sample.title,
            )
    finally:
        conn.close()

    return downloaded, skipped, errors


def build_parser() -> argparse.ArgumentParser:
    lang = env_lang()
    parser = argparse.ArgumentParser(
        description=t(lang, "single.parser_description")
    )
    parser.add_argument(
        "post",
        help=t(lang, "single.parser_post_help"),
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help=t(lang, "single.parser_force_help"),
    )
    parser.add_argument(
        "--mark-seen",
        action="store_true",
        help=t(lang, "single.parser_mark_seen_help"),
    )
    return parser


def main(argv: Optional[list[str]] = None) -> int:
    configure_stdio()
    parser = build_parser()
    args = parser.parse_args(argv)

    try:
        post_id = extract_post_id(args.post)
        settings = load_settings()
    except Exception as exc:
        print(t(env_lang(), "single.arg_config_error", error=exc), file=sys.stderr)
        return 2

    setup_logging(settings.log_level)
    logger.info(t(settings.lang, "single.start", post_id=post_id))
    logger.info(t(settings.lang, "main.download_dir", path=settings.download_dir))
    logger.info(t(settings.lang, "main.db", path=settings.db_path))

    try:
        downloaded, skipped, errors = download_post(
            settings,
            post_id,
            force=args.force,
            mark_seen=args.mark_seen,
        )
    except FanboxAuthError as exc:
        logger.error(t(settings.lang, "main.auth_failed", error=exc))
        return 2
    except FanboxError as exc:
        logger.error(t(settings.lang, "single.api_error", error=exc))
        return 1
    except Exception as exc:
        logger.exception(t(settings.lang, "single.failed", error=exc))
        return 1

    logger.info(
        t(
            settings.lang,
            "single.finished",
            downloaded=downloaded,
            skipped=skipped,
            errors=errors,
        )
    )
    return 0 if errors == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
