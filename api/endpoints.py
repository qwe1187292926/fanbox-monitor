"""8 个 Fanbox API 端点的薄包装。

对应 src/ts/API.ts:91-152。所有方法都直接返回 fanbox 原始 JSON dict，
解析交给 crawler / parser 层。
"""
from __future__ import annotations

from typing import Any, Optional

from api.client import FanboxClient

BASE = "https://api.fanbox.cc"


def list_supporting_plans(client: FanboxClient) -> dict[str, Any]:
    return client.get(f"{BASE}/plan.listSupporting")


def get_supporting_plan_for_creator(client: FanboxClient, creator_id: str) -> dict[str, Any]:
    return client.get(f"{BASE}/legacy/support/creator", params={"creatorId": creator_id})


def get_creator(client: FanboxClient, creator_id: str) -> dict[str, Any]:
    return client.get(f"{BASE}/creator.get", params={"creatorId": creator_id})


def list_following(client: FanboxClient) -> dict[str, Any]:
    return client.get(f"{BASE}/creator.listFollowing")


def list_supporting_posts(
    client: FanboxClient,
    limit: int = 50,
    max_published_dt: Optional[str] = None,
    max_id: Optional[str] = None,
) -> dict[str, Any]:
    """对应 src/ts/API.ts:111-123，post.listSupporting。

    使用 max_published_dt + max_id 作为翻页游标（fanbox API 原生支持）。
    """
    params: dict[str, Any] = {"limit": limit}
    if max_published_dt:
        params["maxPublishedDatetime"] = max_published_dt
    if max_id:
        params["maxId"] = max_id
    return client.get(f"{BASE}/post.listSupporting", params=params)


def list_creator_posts(
    client: FanboxClient,
    creator_id: str,
    limit: int = 50,
    max_published_dt: Optional[str] = None,
    max_id: Optional[str] = None,
) -> dict[str, Any]:
    """对应 src/ts/API.ts:125-139，post.listCreator。"""
    params: dict[str, Any] = {"creatorId": creator_id, "limit": limit}
    if max_published_dt:
        params["maxPublishedDatetime"] = max_published_dt
    if max_id:
        params["maxId"] = max_id
    return client.get(f"{BASE}/post.listCreator", params=params)


def list_tagged_posts(
    client: FanboxClient, user_id: str, tag: str
) -> dict[str, Any]:
    return client.get(
        f"{BASE}/post.listTagged", params={"tag": tag, "userId": user_id}
    )


def get_post(client: FanboxClient, post_id: str) -> dict[str, Any]:
    return client.get(f"{BASE}/post.info", params={"postId": post_id})
