from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


@dataclass
class PostMeta:
    """从 post.listSupporting / post.listCreator 列表项中提取的元信息。

    对应 src/ts/CrawlResult.d.ts 里 PostListItem 的子集，
    list 阶段就能拿到，用于决定是否调 post.info。
    """

    post_id: str
    creator_id: str
    user_name: str
    title: str
    fee: int
    published_dt: str  # ISO8601
    updated_dt: str
    user_icon_url: str = ""
    tags: list[str] = field(default_factory=list)


@dataclass
class FileItem:
    """parser 把 PostBody 转成 0..N 个 FileItem，对应一个待下载的文件。"""

    post_id: str
    creator_id: str
    user_name: str
    title: str
    fee: int
    published_dt: str
    index: int
    name: str
    ext: str
    url: str
    retry_url: Optional[str] = None
    size: Optional[int] = None


@dataclass
class CreatorRule:
    """单个创作者的过滤规则，来自 creators.yaml 或 JSON env var。"""

    skip: bool = False
    fee_min: Optional[int] = None
    fee_max: Optional[int] = None
    tags_include: list[str] = field(default_factory=list)
    tags_exclude: list[str] = field(default_factory=list)


@dataclass
class DownloadResult:
    """单文件下载结果。"""

    item: FileItem
    success: bool
    local_path: Optional[str] = None
    size: Optional[int] = None
    error: Optional[str] = None
    skipped_reason: Optional[str] = None  # "duplicate" | "filter" | None


@dataclass
class CreatorInfo:
    """一次 run 内单个创作者的新投稿汇总，用于 per-creator 通知。"""

    creator_id: str
    name: str
    icon_url: str = ""
    new_files: int = 0
    # post_id → title，保留插入顺序便于通知 body 列举
    sample_posts: dict[str, str] = field(default_factory=dict)


@dataclass
class RunStats:
    """一次 run 的汇总统计，用于 notify 与 run_log。"""

    started_at: int = 0
    ended_at: int = 0
    new_posts: int = 0
    new_files: int = 0
    skipped_files: int = 0
    errors: int = 0
    per_creator: dict[str, CreatorInfo] = field(default_factory=dict)
    error_messages: list[str] = field(default_factory=list)
