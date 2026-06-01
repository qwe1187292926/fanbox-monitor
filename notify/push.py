"""通知层：青龙 notify（统一汇总） + Bark（per-creator + 头像）。

调用约定：
- push_run_results(settings, stats) 是主入口，根据 stats 同时驱动两条通道。
- 青龙 notify 始终尝试（汇总一条），Bark 仅在配置了 device_key 时启用。
"""
from __future__ import annotations

import logging
import sys
from pathlib import Path
from typing import Callable, Optional

from curl_cffi import requests as curl_requests

from config import Settings
from i18n import t
from models.types import CreatorInfo, RunStats

logger = logging.getLogger(__name__)

_QL_NOTIFY_PATHS = [
    "/ql/scripts",
    "/ql/data/scripts",
    "/ql/repo/scripts",
    "/ql/data/repo/scripts",
]

_send_fn: Optional[Callable[[str, str], None]] = None
_resolved = False


def _resolve_qinglong_send() -> Optional[Callable[[str, str], None]]:
    """尝试找到青龙 notify.py 的 send 函数。"""
    global _send_fn, _resolved
    if _resolved:
        return _send_fn
    _resolved = True

    try:
        import notify  # type: ignore

        if hasattr(notify, "send"):
            _send_fn = notify.send  # type: ignore[attr-defined]
            return _send_fn
    except ImportError:
        pass

    for p in _QL_NOTIFY_PATHS:
        path = Path(p)
        if not path.is_dir() or not (path / "notify.py").is_file():
            continue
        if str(path) not in sys.path:
            sys.path.insert(0, str(path))
        try:
            import notify  # type: ignore

            if hasattr(notify, "send"):
                _send_fn = notify.send  # type: ignore[attr-defined]
                return _send_fn
        except ImportError:
            continue

    return None


def send_qinglong(title: str, content: str, lang: str = "zh-CN") -> None:
    """走青龙 notify.py 统一推送（覆盖所有已配置的渠道）。"""
    fn = _resolve_qinglong_send()
    if fn is None:
        logger.info(t(lang, "notify.fallback", title=title, content=content))
        return
    try:
        fn(title, content)
    except Exception as exc:
        logger.warning(
            t(lang, "notify.ql_failed", error=exc, title=title, content=content)
        )


def send_bark(
    server: str,
    device_key: str,
    title: str,
    body: str,
    icon: Optional[str] = None,
    group: Optional[str] = None,
    url: Optional[str] = None,
    sound: Optional[str] = None,
    lang: str = "zh-CN",
) -> bool:
    """直接调用 Bark API 推送，支持自定义图标。

    Bark POST 接口：POST {server}/{device_key} with JSON body。
    """
    if not device_key:
        return False
    api = f"{server.rstrip('/')}/{device_key}"
    payload: dict[str, str] = {"title": title, "body": body}
    if icon:
        payload["icon"] = icon
    if group:
        payload["group"] = group
    if url:
        payload["url"] = url
    if sound:
        payload["sound"] = sound

    try:
        resp = curl_requests.post(
            api, json=payload, timeout=15, impersonate="chrome120"
        )
    except Exception as exc:
        logger.warning(t(lang, "notify.bark_network_error", error=exc))
        return False

    if resp.status_code != 200:
        logger.warning(
            t(lang, "notify.bark_status_error", status=resp.status_code, text=resp.text[:200])
        )
        return False
    try:
        data = resp.json()
    except Exception:
        return False
    if data.get("code") != 200:
        logger.warning(t(lang, "notify.bark_business_error", data=data))
        return False
    return True


def format_run_summary(stats: RunStats, lang: str = "zh-CN") -> tuple[str, str]:
    """从 RunStats 生成 (title, body) —— 给青龙汇总通知用。"""
    duration = max(0, stats.ended_at - stats.started_at)
    title = t(
        lang,
        "notify.summary_title",
        posts=stats.new_posts,
        files=stats.new_files,
    )

    lines = [
        t(lang, "notify.new_posts", count=stats.new_posts),
        t(lang, "notify.new_files", count=stats.new_files),
        t(lang, "notify.skipped_files", count=stats.skipped_files),
        t(lang, "notify.errors", count=stats.errors),
        t(lang, "notify.duration", seconds=duration),
    ]
    if stats.per_creator:
        lines.append("")
        lines.append(t(lang, "notify.by_creator"))
        sorted_creators = sorted(
            stats.per_creator.items(),
            key=lambda kv: kv[1].new_files,
            reverse=True,
        )
        for cid, info in sorted_creators[:20]:
            label = info.name or cid
            lines.append(f"  {label}: {info.new_files}")
        if len(sorted_creators) > 20:
            lines.append(t(lang, "notify.creators_more", count=len(sorted_creators)))
    if stats.error_messages:
        lines.append("")
        lines.append(t(lang, "notify.error_details"))
        for msg in stats.error_messages[:10]:
            lines.append(f"  - {msg}")

    return title, "\n".join(lines)


def _format_creator_body(info: CreatorInfo, lang: str = "zh-CN") -> str:
    """Bark 单 creator 通知的 body。"""
    lines = [t(lang, "notify.creator_new_files", count=info.new_files)]
    if info.sample_posts:
        lines.append("")
        # 取前 5 篇投稿标题，避免通知太长
        for i, (_, title) in enumerate(info.sample_posts.items()):
            if i >= 5:
                lines.append(
                    t(lang, "notify.creator_more_posts", count=len(info.sample_posts))
                )
                break
            lines.append(f"• {title}")
    return "\n".join(lines)


def push_run_results(settings: Settings, stats: RunStats) -> None:
    """根据 stats 推送通知（同时驱动青龙和 Bark）。

    - 青龙 notify：汇总一条
    - Bark：每个有新文件的 creator 单独一条，icon = 创作者头像
    """
    title, body = format_run_summary(stats, settings.lang)

    # 是否值得通知
    has_new = stats.new_files >= settings.notify_min_new
    has_err = stats.errors > 0

    if not has_new and not has_err:
        logger.info(
            t(settings.lang, "notify.skip_threshold", threshold=settings.notify_min_new)
        )
        return

    # 1) 青龙汇总
    send_qinglong(title, body, settings.lang)

    # 2) Bark per-creator
    if settings.bark_device_key:
        creators_with_new = [
            info for info in stats.per_creator.values() if info.new_files > 0
        ]
        if not creators_with_new and has_err:
            # 没新文件但有错误，发一条错误总览
            send_bark(
                server=settings.bark_server,
                device_key=settings.bark_device_key,
                title=t(settings.lang, "notify.error_title"),
                body=body,
                group=settings.bark_group,
                sound=settings.bark_sound or None,
                lang=settings.lang,
            )
        for info in creators_with_new:
            creator_title = t(
                settings.lang,
                "notify.creator_title",
                name=info.name or info.creator_id,
            )
            send_bark(
                server=settings.bark_server,
                device_key=settings.bark_device_key,
                title=creator_title,
                body=_format_creator_body(info, settings.lang),
                icon=info.icon_url or None,
                group=settings.bark_group,
                url=f"https://www.fanbox.cc/@{info.creator_id}",
                sound=settings.bark_sound or None,
                lang=settings.lang,
            )
        logger.info(
            t(
                settings.lang,
                "notify.bark_count",
                count=len(creators_with_new),
                group=settings.bark_group,
            )
        )
