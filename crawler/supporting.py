"""赞助流：post.listSupporting + nextUrl 翻页。

移植自 src/ts/InitHomePage.ts:90-107。
增量策略：用按过滤规则版本隔离的 cursor 控制翻页边界，seen/skipped 表负责去重。
本流自身不限量，整次 run 的全局配额由 main.py 管理。
"""
from __future__ import annotations

import logging
from typing import Iterator, Optional

from api.client import FanboxClient
from api.endpoints import list_supporting_posts
from config import Settings, filter_revision
from crawler.incremental import filter_and_mark
from i18n import t
from models.types import PostMeta
from parser.post_parser import extract_post_meta
from storage.repo import Repo

logger = logging.getLogger(__name__)

SCOPE = "supporting"


def _cursor_reached(meta: PostMeta, cursor_dt: Optional[str], cursor_id: Optional[str]) -> bool:
    if not cursor_dt:
        return False
    if meta.published_dt < cursor_dt:
        return True
    if meta.published_dt == cursor_dt and (not cursor_id or meta.post_id == cursor_id):
        return True
    return False


def iter_new_supporting(
    client: FanboxClient, repo: Repo, settings: Settings
) -> Iterator[PostMeta]:
    """yield 所有需要 fetch detail 的 PostMeta。

    停翻页条件：
    - 到达当前过滤规则版本的 cursor；
    - 没有 nextUrl。
    """
    revision = filter_revision(settings)
    scope = f"{SCOPE}:{revision}"
    cursor_dt, cursor_id = repo.get_cursor(scope)
    new_max_dt: Optional[str] = None
    new_max_id: Optional[str] = None
    completed_scan = False
    saw_cursor_advance = cursor_dt is None

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

            if _cursor_reached(meta, cursor_dt, cursor_id):
                completed_scan = True
                logger.info(t(settings.lang, "crawler.supporting_cursor_reached"))
                break
            if cursor_dt and meta.published_dt >= cursor_dt:
                saw_cursor_advance = True

            if repo.is_seen(meta.post_id):
                continue
            if repo.is_skipped(meta.post_id, revision):
                continue

            page_all_seen = False

            if not filter_and_mark(meta, repo, settings):
                continue

            yield meta

        if completed_scan:
            break
        if not next_url:
            completed_scan = True
            break

        try:
            page = client.get(next_url)
        except Exception as exc:
            logger.warning(
                t(settings.lang, "crawler.supporting_page_failed", url=next_url, error=exc)
            )
            raise

    if completed_scan and new_max_dt and saw_cursor_advance:
        repo.set_cursor(scope, new_max_dt, new_max_id)
