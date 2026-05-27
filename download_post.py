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
    raw = value.strip()
    if not raw:
        raise ValueError("post URL/id 不能为空")
    if raw.isdigit():
        return raw

    parsed = urlparse(raw)
    if not parsed.scheme or not parsed.netloc:
        raise ValueError(f"不是有效的 Fanbox URL 或 post id: {value}")

    match = re.search(r"(?:^|/)posts/(\d+)(?:/|$)", parsed.path)
    if match:
        return match.group(1)

    query_match = re.search(r"(?:^|[?&])postId=(\d+)(?:&|$)", parsed.query)
    if query_match:
        return query_match.group(1)

    raise ValueError(f"无法从 URL 中解析 post id: {value}")


def collect_files(client: FanboxClient, settings: Settings, post_id: str) -> list[FileItem]:
    detail = get_post(client, post_id)
    body = detail.get("body") if isinstance(detail, dict) else None
    if not isinstance(body, dict):
        raise RuntimeError(f"post.info {post_id} 响应缺少有效 body")
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
        interval=CrawlInterval(settings.interval_sec),
        proxy=settings.proxy,
    )

    downloaded = 0
    skipped = 0
    errors = 0
    files: list[FileItem] = []

    try:
        files = collect_files(client, settings, post_id)
        if not files:
            logger.info("投稿 %s 没有通过过滤的可下载文件", post_id)
            return downloaded, skipped, errors

        logger.info("投稿 %s 共 %d 个通过过滤的文件", post_id, len(files))
        for item in files:
            if not force and repo.is_downloaded(item.url):
                logger.info("已登记下载，跳过: %s", item.url)
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
                logger.error("下载失败 %s: %s", item.url, result.error)

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
    parser = argparse.ArgumentParser(
        description="按 Fanbox 投稿 URL 或 post id 单独下载一个投稿的文件。"
    )
    parser.add_argument(
        "post",
        help="Fanbox 投稿 URL 或纯 post id，例如 https://www.fanbox.cc/@creator/posts/123456",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="忽略 downloaded 表记录，尝试重新下载；目标文件已存在时仍会跳过。",
    )
    parser.add_argument(
        "--mark-seen",
        action="store_true",
        help="下载无错误时把该投稿写入 seen_posts。默认不写，避免影响定时监控增量状态。",
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
        print(f"参数/配置错误: {exc}", file=sys.stderr)
        return 2

    setup_logging(settings.log_level)
    logger.info("单帖下载启动: post_id=%s", post_id)
    logger.info("下载目录: %s", settings.download_dir)
    logger.info("DB: %s", settings.db_path)

    try:
        downloaded, skipped, errors = download_post(
            settings,
            post_id,
            force=args.force,
            mark_seen=args.mark_seen,
        )
    except FanboxAuthError as exc:
        logger.error("鉴权失败，cookie 可能已过期: %s", exc)
        return 2
    except FanboxError as exc:
        logger.error("Fanbox API 错误: %s", exc)
        return 1
    except Exception as exc:
        logger.exception("单帖下载失败: %s", exc)
        return 1

    logger.info(
        "单帖下载结束: downloaded=%d skipped=%d errors=%d",
        downloaded,
        skipped,
        errors,
    )
    return 0 if errors == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
