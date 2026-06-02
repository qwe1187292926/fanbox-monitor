"""FanboxMonitor 入口：青龙 cron 调用此脚本。

流程：
1. 加载 Settings、打开 DB、装配 FanboxClient
2. 根据开关跑 supporting / following 流，对每个新 PostMeta：
   - 拉详情 → parser → 文件过滤
   - 并发下载所有通过的 FileItem
   - 全部入库成功后才把 post 标记为 seen
3. 汇总统计 → 写 run_log → notify
"""
from __future__ import annotations

import logging
import os
import random
import socket
import sys
import time
import uuid
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator, Optional
from urllib.parse import urlsplit, urlunsplit

from api.client import FanboxClient
from api.endpoints import get_post
from api.exceptions import (
    FanboxAuthError,
    FanboxError,
    FanboxForbiddenError,
    FanboxRateLimitError,
)
from config import Settings, filter_revision, load_settings
from crawler.incremental import filter_and_mark
from crawler.following import iter_new_following
from crawler.interval import CrawlInterval
from crawler.supporting import iter_new_supporting
from downloader.http_downloader import download_file
from i18n import t
from models.types import CreatorInfo, DownloadResult, FileItem, PostMeta, RunStats
from notify.push import format_run_summary, push_run_results, send_qinglong
from parser.filter import accept_file
from parser.post_parser import parse_post
from storage.db import open_db
from storage.repo import Repo


logger = logging.getLogger("fanbox_monitor")


@dataclass
class _PostDownloadState:
    meta: PostMeta
    failed: bool = False


def _redact_proxy(proxy: Optional[str], lang: str | None = None) -> str:
    """Return a log-safe proxy string without credentials."""
    if not proxy:
        return t(lang, "common.not_configured")

    try:
        parts = urlsplit(proxy)
    except ValueError:
        if "@" in proxy:
            return "***@" + proxy.rsplit("@", 1)[1]
        return proxy

    if "@" not in parts.netloc:
        return proxy

    host = parts.hostname or ""
    if ":" in host and not host.startswith("["):
        host = f"[{host}]"
    if parts.port is not None:
        host = f"{host}:{parts.port}"
    redacted = f"***:***@{host}" if host else "***:***"
    return urlunsplit((parts.scheme, redacted, parts.path, parts.query, parts.fragment))


def _log_startup_config(settings: Settings) -> None:
    fee_max = settings.fee_max if settings.fee_max is not None else t(settings.lang, "common.unlimited")
    date_after = settings.date_after or t(settings.lang, "common.unlimited")
    creator_rules = len(settings.creator_rules)
    creator_rules_source = settings.creator_rules_source or t(settings.lang, "common.not_configured")
    ext_whitelist = ",".join(sorted(settings.ext_whitelist))

    logger.info(t(settings.lang, "main.start"))
    logger.info(t(settings.lang, "main.download_dir", path=settings.download_dir))
    logger.info(t(settings.lang, "main.db", path=settings.db_path))
    logger.info(t(settings.lang, "main.lang", lang=settings.lang))
    logger.info(
        t(
            settings.lang,
            "main.mode",
            supporting=settings.mode_supporting,
            following=settings.mode_following,
        )
    )
    logger.info(
        t(
            settings.lang,
            "main.network",
            proxy=_redact_proxy(settings.proxy, settings.lang),
            interval_sec=settings.interval_sec,
            concurrency=settings.concurrency,
        )
    )
    logger.info(
        t(
            settings.lang,
            "main.filters",
            ext_whitelist=ext_whitelist,
            fee_min=settings.fee_min,
            fee_max=fee_max,
            date_after=date_after,
        )
    )
    logger.info(
        t(
            settings.lang,
            "main.run_retry",
            first_run_max_posts=settings.first_run_max_posts,
            post_403_retries=settings.post_403_retries,
            post_403_backoff_base=settings.post_403_backoff_base,
        )
    )
    logger.info(
        t(
            settings.lang,
            "main.naming_notify",
            name_rule=settings.name_rule,
            notify_min_new=settings.notify_min_new,
            bark_enabled=bool(settings.bark_device_key),
            bark_server=settings.bark_server,
        )
    )
    logger.info(
        t(
            settings.lang,
            "main.creator_rules",
            source=creator_rules_source,
            rules=creator_rules,
            default_skip=settings.default_creator_rule.skip,
        )
    )


def _finalize_downloads(
    repo: Repo,
    stats: RunStats,
    futures: list[tuple[PostMeta, FileItem, Future[DownloadResult]]],
    post_states: dict[str, _PostDownloadState],
    lang: str,
) -> None:
    """等待下载任务落定，写 downloaded，并只把完全成功的投稿标记 seen。"""
    for meta, item, fut in futures:
        state = post_states.get(meta.post_id)
        try:
            result = fut.result()
        except Exception as exc:
            if state is not None:
                state.failed = True
            stats.errors += 1
            stats.error_messages.append(f"{item.url}: {exc}")
            logger.exception(t(lang, "main.download_task_exception", url=item.url))
            continue

        if result.success and result.skipped_reason is None:
            repo.mark_downloaded(
                item.url, item.post_id,
                result.local_path or "", result.size,
            )
            stats.new_files += 1
            info = stats.per_creator.get(meta.creator_id)
            if info is not None:
                info.new_files += 1
        elif result.success and result.skipped_reason == "existing":
            repo.mark_downloaded(
                item.url, item.post_id,
                result.local_path or "", result.size,
            )
            stats.skipped_files += 1
        else:
            if state is not None:
                state.failed = True
            stats.errors += 1
            if result.error:
                stats.error_messages.append(f"{item.url}: {result.error}")

    for state in post_states.values():
        meta = state.meta
        if state.failed:
            logger.warning(
                t(
                    lang,
                    "main.post_failed_not_seen",
                    creator_id=meta.creator_id,
                    post_id=meta.post_id,
                )
            )
            continue
        repo.mark_seen(
            meta.post_id,
            meta.creator_id,
            meta.published_dt,
            meta.fee,
            meta.title,
        )


def setup_logging(log_path: Optional[Path] = None, level: str = "INFO") -> None:
    # 避免 Windows / 部分容器 stdout 编码默认非 utf-8 时打印中文崩溃
    for stream in (sys.stdout, sys.stderr):
        reconfig = getattr(stream, "reconfigure", None)
        if reconfig is not None:
            try:
                reconfig(encoding="utf-8", errors="replace")
            except Exception:
                pass
    handlers: list[logging.Handler] = [logging.StreamHandler(sys.stdout)]
    if log_path is not None:
        try:
            log_path.parent.mkdir(parents=True, exist_ok=True)
            handlers.append(logging.FileHandler(log_path, encoding="utf-8"))
        except OSError as exc:
            print(t(None, "main.log_file_failed", path=log_path, error=exc), file=sys.stderr)
    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        handlers=handlers,
        force=True,
    )


def _collect_files_for_post(
    client: FanboxClient, settings: Settings, meta: PostMeta
) -> Optional[list[FileItem]]:
    """拉详情 → parse → 文件白名单过滤。

    403 处理：先重试若干次（fanbox 偶尔对正常请求软限流返回 403），
    多次重试仍 403 才放弃。
    """
    detail = None
    max_retries = max(0, settings.post_403_retries)

    for attempt in range(max_retries + 1):
        try:
            detail = get_post(client, meta.post_id)
            break
        except FanboxRateLimitError:
            raise
        except FanboxAuthError:
            raise
        except FanboxForbiddenError as exc:
            if attempt < max_retries:
                # 指数退避 + jitter，封顶 5 分钟
                wait = min(
                    settings.post_403_backoff_base * (2 ** attempt)
                    + random.uniform(0, 5),
                    300.0,
                )
                logger.warning(
                    t(
                        settings.lang,
                        "main.post_403_retry",
                        post_id=meta.post_id,
                        wait=wait,
                        attempt=attempt + 1,
                        max_retries=max_retries,
                    )
                )
                time.sleep(wait)
                continue
            logger.info(
                t(
                    settings.lang,
                    "main.post_403_skip",
                    post_id=meta.post_id,
                    max_retries=max_retries,
                )
            )
            return []
        except FanboxError as exc:
            logger.warning(
                t(settings.lang, "main.detail_fetch_failed", post_id=meta.post_id, error=exc)
            )
            return None

    if detail is None:
        return None

    body = detail.get("body") if isinstance(detail, dict) else None
    if not isinstance(body, dict):
        logger.warning(t(settings.lang, "main.invalid_body", post_id=meta.post_id))
        return None

    files = parse_post(body)
    return [f for f in files if accept_file(f, settings.ext_whitelist)]


def _post_streams(
    client: FanboxClient, repo: Repo, settings: Settings
) -> Iterator[PostMeta]:
    """根据开关串接 supporting + following。"""
    revision = filter_revision(settings)
    for meta in repo.iter_skipped_for_recheck(revision):
        if filter_and_mark(meta, repo, settings):
            yield meta

    if settings.mode_supporting:
        logger.info(t(settings.lang, "main.stream_supporting"))
        yield from iter_new_supporting(client, repo, settings)
    if settings.mode_following:
        logger.info(t(settings.lang, "main.stream_following"))
        yield from iter_new_following(client, repo, settings)
    if not settings.mode_supporting and not settings.mode_following:
        logger.warning(t(settings.lang, "main.modes_disabled"))


def run() -> int:
    """主流程，返回退出码。"""
    settings = load_settings()
    setup_logging(settings.download_dir / "fanbox_monitor.log", settings.log_level)

    _log_startup_config(settings)

    settings.download_dir.mkdir(parents=True, exist_ok=True)

    conn = open_db(settings.db_path)
    repo = Repo(conn)
    lock_owner = f"{socket.gethostname()}:{os.getpid()}:{uuid.uuid4().hex[:8]}"
    lock_name = "fanbox_monitor"
    if not repo.acquire_run_lock(lock_name, lock_owner, settings.run_lock_ttl_sec):
        logger.warning(
            t(settings.lang, "main.lock_already_running", ttl=settings.run_lock_ttl_sec)
        )
        conn.close()
        return 0

    try:
        interval = CrawlInterval(settings.interval_sec, settings.lang)
        client = FanboxClient(
            session_cookie=settings.session,
            user_agent=settings.user_agent,
            interval=interval,
            proxy=settings.proxy,
            lang=settings.lang,
        )
    except Exception:
        repo.release_run_lock(lock_name, lock_owner)
        conn.close()
        raise

    stats = RunStats(started_at=int(time.time()))
    futures: list[tuple[PostMeta, FileItem, Future[DownloadResult]]] = []
    post_states: dict[str, _PostDownloadState] = {}
    downloads_finalized = False

    try:
        with ThreadPoolExecutor(max_workers=settings.concurrency) as pool:
            seen_this_run: set[str] = set()

            # 全局配额：本次 run 总共最多处理多少条新投稿（0 = 无限）
            quota_limit = settings.first_run_max_posts
            quota_used = 0
            if quota_limit > 0:
                logger.info(t(settings.lang, "main.quota_limit", limit=quota_limit))

            for meta in _post_streams(client, repo, settings):
                if meta.post_id in seen_this_run:
                    logger.debug(t(settings.lang, "main.duplicate_post", post_id=meta.post_id))
                    continue
                seen_this_run.add(meta.post_id)

                if quota_limit > 0 and quota_used >= quota_limit:
                    logger.info(t(settings.lang, "main.quota_reached", limit=quota_limit))
                    break

                try:
                    files = _collect_files_for_post(client, settings, meta)
                except FanboxAuthError:
                    raise
                except FanboxRateLimitError:
                    logger.error(t(settings.lang, "main.rate_limit_stop"))
                    stats.errors += 1
                    stats.error_messages.append("rate_limit")
                    break

                if files is None:
                    stats.errors += 1
                    stats.error_messages.append(f"{meta.post_id}: detail_fetch_failed")
                    continue

                quota_used += 1

                if not files:
                    # 当前过滤规则下没有可下载文件，记录为 skipped 以便规则变化后重评估。
                    repo.mark_skipped(
                        meta.post_id,
                        filter_revision(settings),
                        meta.creator_id,
                        meta.published_dt,
                        meta.fee,
                        meta.title,
                        "no_accepted_files",
                        updated_dt=meta.updated_dt,
                        user_name=meta.user_name,
                        user_icon_url=meta.user_icon_url,
                        tags=meta.tags,
                    )
                    continue

                state = _PostDownloadState(meta=meta)
                post_states[meta.post_id] = state
                stats.new_posts += 1
                logger.info(
                    t(
                        settings.lang,
                        "main.post_files_found",
                        creator_id=meta.creator_id,
                        post_id=meta.post_id,
                        title=meta.title,
                        published_dt=meta.published_dt,
                        count=len(files),
                    )
                )

                # 记录 creator 信息（即便所有文件都已下载，也保留 creator 出现过的事实）
                info = stats.per_creator.setdefault(
                    meta.creator_id,
                    CreatorInfo(
                        creator_id=meta.creator_id,
                        name=meta.user_name,
                        icon_url=meta.user_icon_url,
                    ),
                )
                # 后到的 meta 可能有更新的 icon_url / name，覆盖一下
                if meta.user_icon_url and not info.icon_url:
                    info.icon_url = meta.user_icon_url
                if meta.user_name and not info.name:
                    info.name = meta.user_name
                info.sample_posts.setdefault(meta.post_id, meta.title)

                for item in files:
                    # 主线程提前去重：DB 操作不能跨线程
                    if repo.is_downloaded(item.url):
                        stats.skipped_files += 1
                        continue
                    try:
                        fut = pool.submit(
                            download_file, client.session, settings, item
                        )
                    except Exception as exc:
                        state.failed = True
                        stats.errors += 1
                        stats.error_messages.append(f"{item.url}: submit_failed: {exc}")
                        logger.exception(t(settings.lang, "main.submit_download_failed", url=item.url))
                        continue
                    futures.append((meta, item, fut))

            _finalize_downloads(repo, stats, futures, post_states, settings.lang)
            downloads_finalized = True

    except FanboxAuthError as exc:
        if not downloads_finalized:
            _finalize_downloads(repo, stats, futures, post_states, settings.lang)
            downloads_finalized = True
        stats.errors += 1
        stats.error_messages.append(f"auth: {exc}")
        logger.error(t(settings.lang, "main.auth_failed", error=exc))
        try:
            send_qinglong(
                t(settings.lang, "main.auth_notify_title"),
                t(settings.lang, "main.auth_notify_body", error=exc),
                settings.lang,
            )
        finally:
            repo.release_run_lock(lock_name, lock_owner)
            conn.close()
        return 2
    except Exception as exc:
        if not downloads_finalized:
            _finalize_downloads(repo, stats, futures, post_states, settings.lang)
            downloads_finalized = True
        stats.errors += 1
        stats.error_messages.append(f"unhandled: {exc}")
        logger.exception(t(settings.lang, "main.unhandled_exception", error=exc))

    stats.ended_at = int(time.time())

    try:
        title, body = format_run_summary(stats, settings.lang)
        repo.insert_run_log(
            stats.started_at,
            stats.ended_at,
            stats.new_posts,
            stats.new_files,
            stats.errors,
            body,
        )

        logger.info(t(settings.lang, "main.run_finished", body=body))

        push_run_results(settings, stats)
    finally:
        repo.release_run_lock(lock_name, lock_owner)
        conn.close()
    return 0 if stats.errors == 0 else 1


if __name__ == "__main__":
    sys.exit(run())
