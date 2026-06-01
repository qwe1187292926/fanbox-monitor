"""关注流：creator.listFollowing → 逐 creator 走 post.listCreator 翻页。

移植自 src/ts/InitHomePage.ts:110-141 + InitPageBase.ts:108-131。
不再使用原项目的 paginateCreator 优化（那是冷启动建库用的），
直接用 listCreator + nextUrl 翻页，靠 seen_posts 去重；cursor 仅记录最近扫描 checkpoint。
本流自身不限量，整次 run 的全局配额由 main.py 管理。
"""
from __future__ import annotations

import logging
from typing import Iterator, Optional

from api.client import FanboxClient
from api.endpoints import list_creator_posts, list_following
from config import Settings, get_rule_for
from crawler.incremental import filter_and_mark
from i18n import t
from models.types import PostMeta
from parser.post_parser import extract_post_meta
from storage.repo import Repo

logger = logging.getLogger(__name__)


def _iter_creator_posts(
    client: FanboxClient, repo: Repo, settings: Settings, creator_id: str
) -> Iterator[PostMeta]:
    scope = f"following:{creator_id}"

    new_max_dt: Optional[str] = None
    new_max_id: Optional[str] = None

    try:
        page = list_creator_posts(client, creator_id, limit=300)
    except Exception as exc:
        logger.warning(
            t(settings.lang, "crawler.creator_home_failed", creator_id=creator_id, error=exc)
        )
        raise

    while True:
        body = page.get("body") or {}
        # post.listCreator 的 body 是 {items, nextUrl}
        items = body.get("items") if isinstance(body, dict) else None
        if items is None and isinstance(body, list):
            # 极少数情况下 body 直接是数组
            items = body
        items = items or []
        next_url = body.get("nextUrl") if isinstance(body, dict) else None

        if not items:
            break

        page_all_seen = True
        for raw in items:
            meta_dict = extract_post_meta(raw)
            if not meta_dict.get("creator_id"):
                meta_dict["creator_id"] = creator_id
            meta = PostMeta(**meta_dict)

            if new_max_dt is None or meta.published_dt > new_max_dt:
                new_max_dt = meta.published_dt
                new_max_id = meta.post_id

            if repo.is_seen(meta.post_id):
                continue

            page_all_seen = False

            if not filter_and_mark(meta, repo, settings):
                continue

            yield meta

        if page_all_seen:
            break
        if not next_url:
            break

        try:
            page = client.get(next_url)
        except Exception as exc:
            logger.warning(
                t(
                    settings.lang,
                    "crawler.creator_page_failed",
                    creator_id=creator_id,
                    url=next_url,
                    error=exc,
                )
            )
            raise

    if new_max_dt:
        repo.set_cursor(scope, new_max_dt, new_max_id)


def iter_new_following(
    client: FanboxClient, repo: Repo, settings: Settings
) -> Iterator[PostMeta]:
    """先拉关注列表，再逐 creator 走增量翻页。

    早早跳过：creator_rules 里 skip=true 的不调 listCreator。
    """
    try:
        raw = list_following(client)
    except Exception as exc:
        logger.error(t(settings.lang, "crawler.following_failed", error=exc))
        raise

    creators = (raw.get("body") or {}).get("creators") or []
    logger.info(t(settings.lang, "crawler.following_count", count=len(creators)))

    for creator in creators:
        creator_id = str(creator.get("creatorId") or "")
        if not creator_id:
            continue
        rule = get_rule_for(settings, creator_id)
        if rule.skip:
            logger.info(t(settings.lang, "crawler.creator_skip", creator_id=creator_id))
            continue

        creator_name = ((creator.get("user") or {}).get("name")) or creator_id
        logger.info(
            t(
                settings.lang,
                "crawler.creator_process",
                name=creator_name,
                creator_id=creator_id,
            )
        )
        yield from _iter_creator_posts(client, repo, settings, creator_id)
