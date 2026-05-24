"""文件名模板渲染 + 非法字符清理。

移植自 src/ts/FileName.ts。支持的占位符：
    {postid} {post_id} {title} {name} {ext} {index} {tags}
    {date} {task_date} {fee} {user}
    {create_id} {creator_id} {uid} {user_id}
"""
from __future__ import annotations

import re
from datetime import datetime
from typing import Optional

from models.types import FileItem

# 控制字符 + BiDi 等不可见字符（对应 FileName.ts:18-19）
_UNSAFE_CTRL_RE = re.compile(
    r"[--­؀-؅؜۝܏"
    r"࣢᠎​-‏‪-‮⁠-⁤⁦-⁯"
    r"﷐-﷯﻿￹-￻￾￿]"
)

# 不能做文件名的符号 → 全角等价；左是 pattern，右是替换
_FULLWIDTH_MAP = [
    (r"\\", "＼"),
    (r"/", "／"),
    (r":", "："),
    (r"\?", "？"),
    (r'"', "＂"),
    (r"<", "＜"),
    (r">", "＞"),
    (r"\*", "＊"),
    (r"\|", "｜"),
    (r"~", "～"),
]


def _replace_unsafe(value: str) -> str:
    if not value:
        return value
    value = _UNSAFE_CTRL_RE.sub("", value)
    for pattern, repl in _FULLWIDTH_MAP:
        value = re.sub(pattern, repl, value)
    return value


def _format_date(iso_dt: str, fmt: str = "%Y-%m-%d") -> str:
    """fanbox 的 publishedDatetime 形如 '2025-01-23 04:05:06'。"""
    if not iso_dt:
        return ""
    for parser in (
        lambda s: datetime.fromisoformat(s.replace("Z", "+00:00")),
        lambda s: datetime.strptime(s, "%Y-%m-%d %H:%M:%S"),
        lambda s: datetime.strptime(s, "%Y-%m-%d"),
    ):
        try:
            return parser(iso_dt).strftime(fmt)
        except (ValueError, TypeError):
            continue
    return iso_dt  # 解析失败时原样返回


def render_filename(
    item: FileItem,
    name_rule: str,
    zero_padding: int = 0,
    task_date: Optional[datetime] = None,
) -> str:
    """根据模板生成相对路径文件名（含扩展名）。

    返回值示例：'fanbox/omutatsu／おむたつ/2025-07-22-7月22日/0.jpeg'。
    """
    index_str = str(item.index)
    if zero_padding > 0:
        index_str = index_str.rjust(zero_padding, "0")

    # safe=True 表示已经是安全字符串，无需替换
    placeholders: dict[str, tuple[str, bool]] = {
        "{postid}": (item.post_id, True),
        "{post_id}": (item.post_id, True),
        "{title}": (item.title or "", False),
        "{name}": (item.name or "", False),
        "{ext}": (item.ext or "", False),
        "{index}": (index_str, False),
        "{date}": (_format_date(item.published_dt), False),
        "{task_date}": (
            task_date.strftime("%Y-%m-%d") if task_date else "",
            False,
        ),
        "{fee}": (str(item.fee), True),
        "{user}": (item.user_name or "", False),
        "{create_id}": (item.creator_id or "", True),
        "{creator_id}": (item.creator_id or "", True),
        "{uid}": (item.creator_id or "", True),
        "{user_id}": (item.creator_id or "", True),
    }

    result = name_rule
    # 替换非法字符（保留 / 作为目录分隔）
    result = _UNSAFE_CTRL_RE.sub("", result)
    for pattern, repl in _FULLWIDTH_MAP:
        if pattern == r"/":
            continue
        result = re.sub(pattern, repl, result)

    for key, (value, safe) in placeholders.items():
        if key not in result:
            continue
        if not safe:
            value = _replace_unsafe(value)
        result = result.replace(key, value)

    # 处理空值导致的 // 和 undefined 残留
    result = result.replace("undefined", "")
    result = re.sub(r"/{2,}", "/", result)

    # 每层路径首尾的 . 转全角（windows 不允许）+ trim
    parts = []
    for part in result.split("/"):
        part = part.strip()
        part = re.sub(r"^\.+", lambda m: "．" * len(m.group()), part)
        part = re.sub(r"\.+$", lambda m: "．" * len(m.group()), part)
        parts.append(part)
    result = "/".join(parts).strip("/")

    if item.ext:
        result = f"{result}.{item.ext}"
    return result
