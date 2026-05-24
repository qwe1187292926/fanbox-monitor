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
import random
import sys
import time
from concurrent.futures import Future, ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Iterator

from api.client import FanboxClient
from api.endpoints import get_post
from api.exceptions import (
    FanboxAuthError,
    FanboxError,
    FanboxForbiddenError,
    FanboxRateLimitError,
)
from config import Settings, load_settings
from crawler.following import iter_new_following
from crawler.interval import CrawlInterval
from crawler.supporting import iter_new_supporting
from downloader.http_downloader import download_file
from models.types import CreatorInfo, DownloadResult, FileItem, PostMeta, RunStats
from notify.push import format_run_summary, push_run_results, send_qinglong
from parser.filter import accept_file
from parser.post_parser import parse_post
from storage.db import open_db
from storage.repo import Repo


logger = logging.getLogger("fanbox_monitor")


def setup_logging(log_path: Path | None = None) -> None:
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
            print(f"[warn] 无法写日志文件 {log_path}: {exc}", file=sys.stderr)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        handlers=handlers,
        force=True,
    )


def _collect_files_for_post(
    client: FanboxClient, settings: Settings, meta: PostMeta
) -> list[FileItem]:
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
        except FanboxForbiddenError as exc:
            if attempt < max_retries:
                # 指数退避 + jitter，封顶 5 分钟
                wait = min(
                    settings.post_403_backoff_base * (2 ** attempt)
                    + random.uniform(0, 5),
                    300.0,
                )
                logger.warning(
                    "post.info %s 返回 403，等待 %.0fs 后重试 (%d/%d)",
                    meta.post_id, wait, attempt + 1, max_retries,
                )
                time.sleep(wait)
                continue
            logger.info(
                "post.info %s 重试 %d 次后仍 403，跳过（可能是付费等级不足或限定内容）",
                meta.post_id, max_retries,
            )
            return []
        except FanboxError as exc:
            logger.warning("拉详情失败 %s: %s", meta.post_id, exc)
            return []

    if detail is None:
        return []

    body = detail.get("body") if isinstance(detail, dict) else None
    if not isinstance(body, dict):
        return []

    files = parse_post(body)
    return [f for f in files if accept_file(f, settings.ext_whitelist)]


def _post_streams(
    client: FanboxClient, repo: Repo, settings: Settings
) -> Iterator[PostMeta]:
    """根据开关串接 supporting + following。"""
    if settings.mode_supporting:
        logger.info("=== 抓取赞助流 ===")
        yield from iter_new_supporting(client, repo, settings)
    if settings.mode_following:
        logger.info("=== 抓取关注流 ===")
        yield from iter_new_following(client, repo, settings)
    if not settings.mode_supporting and not settings.mode_following:
        logger.warning("两个模式都关了，本次无事可做")


def run() -> int:
    """主流程，返回退出码。"""
    settings = load_settings()
    setup_logging(settings.download_dir / "fanbox_monitor.log")

    logger.info("FanboxMonitor 启动")
    logger.info("下载目录: %s", settings.download_dir)
    logger.info("DB: %s", settings.db_path)
    logger.info(
        "模式: supporting=%s following=%s",
        settings.mode_supporting,
        settings.mode_following,
    )

    settings.download_dir.mkdir(parents=True, exist_ok=True)

    conn = open_db(settings.db_path)
    repo = Repo(conn)

    interval = CrawlInterval(settings.interval_sec)
    client = FanboxClient(
        session_cookie=settings.session,
        user_agent=settings.user_agent,
        interval=interval,
        proxy=settings.proxy,
    )

    stats = RunStats(started_at=int(time.time()))

    try:
        with ThreadPoolExecutor(max_workers=settings.concurrency) as pool:
            futures: list[tuple[PostMeta, FileItem, Future[DownloadResult]]] = []

            # 全局配额：本次 run 总共最多处理多少条新投稿（0 = 无限）
            quota_limit = settings.first_run_max_posts
            quota_used = 0
            if quota_limit > 0:
                logger.info("本次 run 配额：最多处理 %d 条新投稿", quota_limit)

            for meta in _post_streams(client, repo, settings):
                if quota_limit > 0 and quota_used >= quota_limit:
                    logger.info(
                        "达到本次 run 配额上限 %d，停止处理后续投稿", quota_limit
                    )
                    break

                try:
                    files = _collect_files_for_post(client, settings, meta)
                except FanboxRateLimitError:
                    logger.error("触发限流且重试失败，提前结束本次 run")
                    stats.errors += 1
                    stats.error_messages.append("rate_limit")
                    break

                quota_used += 1

                if not files:
                    # 没有可下载文件也视为已处理：mark_seen 避免下次重跑
                    repo.mark_seen(
                        meta.post_id,
                        meta.creator_id,
                        meta.published_dt,
                        meta.fee,
                        meta.title,
                    )
                    continue

                stats.new_posts += 1
                logger.info(
                    "投稿 %s/%s (%s) 共 %d 个文件",
                    meta.creator_id,
                    meta.post_id,
                    meta.title,
                    len(files),
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
                    fut = pool.submit(
                        download_file, client.session, settings, item
                    )
                    futures.append((meta, item, fut))

                # 现在就标记 seen：即使部分文件失败，下次 run 也不会重复评估这个 post
                # （失败的文件靠 downloaded 表查重，下次会重试）
                repo.mark_seen(
                    meta.post_id,
                    meta.creator_id,
                    meta.published_dt,
                    meta.fee,
                    meta.title,
                )

            # 等所有下载完成
            for meta, item, fut in futures:
                try:
                    result = fut.result()
                except Exception as exc:
                    stats.errors += 1
                    stats.error_messages.append(f"{item.url}: {exc}")
                    logger.exception("下载任务抛异常: %s", item.url)
                    continue

                if result.success and result.skipped_reason is None:
                    # 下载成功：主线程写库 + 累计 per-creator 统计
                    repo.mark_downloaded(
                        item.url, item.post_id,
                        result.local_path or "", result.size,
                    )
                    stats.new_files += 1
                    info = stats.per_creator.get(meta.creator_id)
                    if info is not None:
                        info.new_files += 1
                elif result.success and result.skipped_reason == "existing":
                    # 磁盘已存在但 db 没记录 → 补登记
                    repo.mark_downloaded(
                        item.url, item.post_id,
                        result.local_path or "", result.size,
                    )
                    stats.skipped_files += 1
                else:
                    stats.errors += 1
                    if result.error:
                        stats.error_messages.append(f"{item.url}: {result.error}")

    except FanboxAuthError as exc:
        stats.errors += 1
        stats.error_messages.append(f"auth: {exc}")
        logger.error("鉴权失败，cookie 可能已过期: %s", exc)
        send_qinglong(
            "FanboxMonitor 认证失败", f"FANBOX_SESSION cookie 已失效\n{exc}"
        )
        conn.close()
        return 2
    except Exception as exc:
        stats.errors += 1
        stats.error_messages.append(f"unhandled: {exc}")
        logger.exception("未处理异常: %s", exc)

    stats.ended_at = int(time.time())

    title, body = format_run_summary(stats)
    repo.insert_run_log(
        stats.started_at,
        stats.ended_at,
        stats.new_posts,
        stats.new_files,
        stats.errors,
        body,
    )
    conn.close()

    logger.info("本次 run 结束:\n%s", body)

    push_run_results(settings, stats)

    return 0 if stats.errors == 0 else 1


if __name__ == "__main__":
    sys.exit(run())
