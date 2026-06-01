"""增量抓取的共享工具：早过滤。"""
from __future__ import annotations

import logging

from config import Settings, get_rule_for
from i18n import t
from models.types import PostMeta
from parser.filter import accept_post
from storage.repo import Repo

logger = logging.getLogger(__name__)


def filter_and_mark(meta: PostMeta, repo: Repo, settings: Settings) -> bool:
    """对 PostMeta 跑一次早过滤。

    通过 → 返回 True，调用方继续 fetch detail。
    未通过 → 把 post_id 写入 seen_posts（避免下次 run 重复评估），返回 False。
    """
    rule = get_rule_for(settings, meta.creator_id)
    ok, reason = accept_post(
        meta,
        rule,
        settings.fee_min,
        settings.fee_max,
        settings.date_after,
    )
    if ok:
        return True
    repo.mark_seen(
        meta.post_id, meta.creator_id, meta.published_dt, meta.fee, meta.title
    )
    logger.debug(
        t(
            settings.lang,
            "crawler.filter_skip",
            creator_id=meta.creator_id,
            post_id=meta.post_id,
            reason=reason,
        )
    )
    return False
