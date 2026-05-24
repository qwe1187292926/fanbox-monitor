"""单文件下载：curl_cffi + 重试 + retry_url 降级。

移植自 src/ts/background.ts:64-82 的浏览器下载 + DownloadControl.ts:370-381 的重试逻辑。

注意：本模块完全不碰 SQLite —— SQLite 连接禁止跨线程使用。
去重检查与 mark_downloaded 由 main.py 在主线程负责。
"""
from __future__ import annotations

import logging
import random
import time
from typing import Optional

from curl_cffi import requests as curl_requests

from config import Settings
from models.types import DownloadResult, FileItem
from parser.filename import render_filename

logger = logging.getLogger(__name__)

MAX_RETRIES = 10
CHUNK = 8192
TIMEOUT = 60

DOWNLOAD_HEADERS = {"Referer": "https://www.fanbox.cc/"}


def _backoff_sleep(attempt: int) -> None:
    wait = min(2 ** attempt + random.random(), 60.0)
    time.sleep(wait)


def download_file(
    session: curl_requests.Session,
    settings: Settings,
    item: FileItem,
) -> DownloadResult:
    """下载单个 FileItem。

    流程：
    1. 渲染文件名 → 目标路径
    2. 目标文件已存在 → 返回 skipped_reason="existing"
    3. 写到 .part 临时文件 → 原子 rename
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
        try:
            resp = session.get(
                url,
                stream=True,
                impersonate="chrome120",
                headers=DOWNLOAD_HEADERS,
                timeout=TIMEOUT,
            )
        except Exception as exc:
            last_error = f"net error: {exc}"
            logger.warning("下载 %s 失败 (attempt %d): %s", url, attempt + 1, exc)
            _backoff_sleep(attempt)
            continue

        status = resp.status_code

        # 404/403：尝试降级到缩略图（对应 DownloadControl.ts:380）
        if status in (403, 404):
            if item.retry_url and not used_retry_url:
                logger.warning(
                    "%s 返回 %d，降级到 retry_url", url, status
                )
                url = item.retry_url
                used_retry_url = True
                continue
            return DownloadResult(
                item=item, success=False, error=f"HTTP {status}"
            )

        # 5xx：退避重试
        if status >= 500:
            last_error = f"HTTP {status}"
            logger.warning("%s 返回 %d (attempt %d)", url, status, attempt + 1)
            _backoff_sleep(attempt)
            continue

        if status >= 400:
            return DownloadResult(
                item=item, success=False, error=f"HTTP {status}"
            )

        # 成功：流式写入临时文件
        try:
            with tmp.open("wb") as f:
                for chunk in resp.iter_content(chunk_size=CHUNK):
                    if chunk:
                        f.write(chunk)
            tmp.replace(target)
        except Exception as exc:
            last_error = f"write error: {exc}"
            logger.warning("写入 %s 失败: %s", target, exc)
            try:
                tmp.unlink(missing_ok=True)
            except OSError:
                pass
            _backoff_sleep(attempt)
            continue

        try:
            size = target.stat().st_size
        except OSError:
            size = None
        logger.info("下载完成: %s (%s bytes)", relative, size)
        return DownloadResult(
            item=item, success=True, local_path=str(target), size=size
        )

    return DownloadResult(
        item=item, success=False, error=last_error or "max retries exceeded"
    )
