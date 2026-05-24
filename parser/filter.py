"""过滤逻辑：扩展名 / 费用 / 日期 / per-creator。

调用约定：
- accept_post(meta, rule, settings) -> (ok, reason)：list 阶段早过滤
- accept_file(item, settings) -> bool：parse 阶段对每个 FileItem 兜底
"""
from __future__ import annotations

from typing import Optional

from models.types import CreatorRule, FileItem, PostMeta


def accept_post(
    meta: PostMeta,
    rule: CreatorRule,
    fee_min: int,
    fee_max: Optional[int],
    date_after: Optional[str],
) -> tuple[bool, Optional[str]]:
    """返回 (是否通过, 拒绝原因)。"""
    if rule.skip:
        return False, "creator_skip"

    effective_min = rule.fee_min if rule.fee_min is not None else fee_min
    if effective_min and meta.fee < effective_min:
        return False, f"fee<{effective_min}"

    effective_max = rule.fee_max if rule.fee_max is not None else fee_max
    if effective_max is not None and meta.fee > effective_max:
        return False, f"fee>{effective_max}"

    if date_after and meta.published_dt and meta.published_dt < date_after:
        return False, f"published<{date_after}"

    if rule.tags_include:
        tag_set = set(meta.tags or [])
        if not (set(rule.tags_include) & tag_set):
            return False, "tags_not_include"

    if rule.tags_exclude:
        tag_set = set(meta.tags or [])
        if set(rule.tags_exclude) & tag_set:
            return False, "tags_excluded"

    return True, None


def accept_file(item: FileItem, ext_whitelist: set[str]) -> bool:
    """按扩展名白名单过滤单个文件。"""
    ext = (item.ext or "").lower()
    if not ext:
        return False
    return ext in ext_whitelist
