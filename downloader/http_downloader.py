"""单文件下载：curl_cffi + 重试 + retry_url 降级。

移植自 src/ts/background.ts:64-82 的浏览器下载 + DownloadControl.ts:370-381 的重试逻辑。

注意：本模块完全不碰 SQLite —— SQLite 连接禁止跨线程使用。
去重检查与 mark_downloaded 由 main.py 在主线程负责。
"""
from __future__ import annotations

import logging
import random
import time
from pathlib import Path
from typing import Optional

from curl_cffi import requests as curl_requests

from config import Settings
from error_summary import simplify_error
from i18n import t
from models.types import DownloadResult, FileItem
from parser.filename import render_filename

logger = logging.getLogger(__name__)

MAX_RETRIES = 10
CHUNK = 65536      # 64 KiB；大文件下减少 Python ↔ libcurl 来回开销
TIMEOUT = 300      # 大 zip 可能要几分钟才传完，60s 不够

DOWNLOAD_HEADERS = {"Referer": "https://www.fanbox.cc/"}


def _backoff_sleep(attempt: int) -> None:
    wait = min(2 ** attempt + random.random(), 60.0)
    time.sleep(wait)


def _tmp_size(tmp: Path) -> int:
    try:
        return tmp.stat().st_size if tmp.exists() else 0
    except OSError:
        return 0


def download_file(
    session: curl_requests.Session,
    settings: Settings,
    item: FileItem,
) -> DownloadResult:
    """下载单个 FileItem。

    流程：
    1. 渲染文件名 → 目标路径
    2. 目标文件已存在 → 返回 skipped_reason="existing"
    3. 写到 .part 临时文件；失败时**保留 .part**，下次重试通过 HTTP Range 断点续传
    4. 完整写完后原子 rename .part → target
    """
    relative = render_filename(item, settings.name_rule)
    target = settings.download_dir / relative

    if target.exists():
        # 文件级幂等：磁盘上已有就直接跳过；调用方负责补登记 db
        try:
            size = target.stat().st_size
        except OSError:
            size = None
        return DownloadResult(
            item=item, success=True, local_path=str(target), size=size,
            skipped_reason="existing",
        )

    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_name(target.name + ".part")

    url = item.url
    used_retry_url = False
    last_error: Optional[str] = None

    for attempt in range(MAX_RETRIES):
        resume_pos = _tmp_size(tmp)
        headers = dict(DOWNLOAD_HEADERS)
        if resume_pos > 0:
            headers["Range"] = f"bytes={resume_pos}-"
            logger.info(
                t(
                    settings.lang,
                    "download.resume",
                    relative=relative,
                    mib=resume_pos / 1048576,
                    attempt=attempt + 1,
                )
            )

        try:
            resp = session.get(
                url,
                stream=True,
                impersonate="chrome120",
                headers=headers,
                timeout=TIMEOUT,
            )
        except Exception as exc:
            last_error = simplify_error(exc, settings.lang)
            logger.warning(
                t(
                    settings.lang,
                    "download.net_failed",
                    url=url,
                    attempt=attempt + 1,
                    error=last_error,
                )
            )
            _backoff_sleep(attempt)
            continue

        status = resp.status_code

        # 404/403：尝试降级到缩略图（对应 DownloadControl.ts:380）
        if status in (403, 404):
            if item.retry_url and not used_retry_url:
                logger.warning(
                    t(settings.lang, "download.retry_url", url=url, status=status)
                )
                url = item.retry_url
                used_retry_url = True
                # 不同 URL 不能续传：清掉旧的 .part
                if tmp.exists():
                    try:
                        tmp.unlink()
                    except OSError:
                        pass
                continue
            return DownloadResult(
                item=item, success=False, error=f"HTTP {status}",
            )

        # 416 Range Not Satisfiable：本地 .part 比远程文件还大，从头来
        if status == 416:
            logger.warning(t(settings.lang, "download.reset_part", url=url))
            if tmp.exists():
                try:
                    tmp.unlink()
                except OSError:
                    pass
            continue

        # 5xx：退避重试（保留 .part 用于续传）
        if status >= 500:
            last_error = f"HTTP {status}"
            logger.warning(
                t(
                    settings.lang,
                    "download.server_status",
                    url=url,
                    status=status,
                    attempt=attempt + 1,
                )
            )
            _backoff_sleep(attempt)
            continue

        if status >= 400:
            return DownloadResult(
                item=item, success=False, error=f"HTTP {status}",
            )

        # 200 = 全量；206 = 续传
        if status == 206:
            file_mode = "ab"
        elif status == 200:
            if resume_pos > 0:
                logger.info(t(settings.lang, "download.range_ignored", url=url))
            file_mode = "wb"
        else:
            return DownloadResult(
                item=item, success=False, error=f"unexpected status {status}",
            )

        try:
            with tmp.open(file_mode) as f:
                for chunk in resp.iter_content(chunk_size=CHUNK):
                    if chunk:
                        f.write(chunk)
            tmp.replace(target)
        except Exception as exc:
            # 写入过程中网络中断 / HTTP/2 stream reset 等。
            # **不删 .part**，下次循环用 Range 续传。
            now_size = _tmp_size(tmp)
            last_error = simplify_error(exc, settings.lang)
            logger.warning(
                t(
                    settings.lang,
                    "download.write_interrupted",
                    target=target,
                    error=last_error,
                    mib=now_size / 1048576,
                )
            )
            _backoff_sleep(attempt)
            continue

        try:
            size = target.stat().st_size
        except OSError:
            size = None
        logger.info(
            t(
                settings.lang,
                "download.completed",
                relative=relative,
                mib=(size or 0) / 1048576,
            )
        )
        return DownloadResult(
            item=item, success=True, local_path=str(target), size=size,
        )

    return DownloadResult(
        item=item, success=False, error=last_error or "max retries exceeded",
    )
