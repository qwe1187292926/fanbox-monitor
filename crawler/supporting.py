"""赞助流：post.listSupporting + nextUrl 翻页。

移植自 src/ts/InitHomePage.ts:90-107。
增量策略：靠 seen_posts 表查重，遇到全部已 seen 的页就停。
本流自身不限量，整次 run 的全局配额由 main.py 管理。
"""
from __future__ import annotations

import logging
from typing import Iterator, Optional

from api.client import FanboxClient
from api.endpoints import list_supporting_posts
from config import Settings
from crawler.incremental import filter_and_mark
from i18n import t
from models.types import PostMeta
from parser.post_parser import extract_post_meta
from storage.repo import Repo

logger = logging.getLogger(__name__)

SCOPE = "supporting"


def iter_new_supporting(
    client: FanboxClient, repo: Repo, settings: Settings
) -> Iterator[PostMeta]:
    """yield 所有需要 fetch detail 的 PostMeta。

    停翻页条件：
    - 本页所有 items 都已在 seen_posts；
    - 没有 nextUrl。
    """
    new_max_dt: Optional[str] = None
    new_max_id: Optional[str] = None

    try:
        page = list_supporting_posts(client, limit=300)
    except Exception as exc:
        logger.error(t(settings.lang, "crawler.supporting_home_failed", error=exc))
        raise

    while True:
        body = page.get("body") or {}
        items = body.get("items") or []
        next_url = body.get("nextUrl")

        if not items:
            break

        page_all_seen = True
        for raw in items:
            meta_dict = extract_post_meta(raw)
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
            logger.info(t(settings.lang, "crawler.supporting_all_seen"))
            break
        if not next_url:
            break

        try:
            page = client.get(next_url)
        except Exception as exc:
            logger.warning(
                t(settings.lang, "crawler.supporting_page_failed", url=next_url, error=exc)
            )
            raise

    if new_max_dt:
        repo.set_cursor(SCOPE, new_max_dt, new_max_id)
