"""PostBody → list[FileItem]。

移植自 src/ts/SaveData.ts:44-339。按用户需求**仅保留真实文件**：
- 跳过封面图（coverImageUrl）
- 跳过外链 txt / 嵌入资源 / 正文文本（textContent / embedMap / urlEmbedMap）
- 跳过 video / text 类型（纯外链 / 纯文本，没有可下载文件）

保留：
- article 类型：body.blocks 里 type==image 和 type==file 的资源
- image 类型：body.images
- file 类型：body.files
- entry 类型：body.html 用正则提取图片链接
"""
from __future__ import annotations

import re
from typing import Any, Optional

from models.types import FileItem

_IMG_IN_HTML_RE = re.compile(r"https://[^\"\s]+?\.(jpeg|jpg|png|gif|bmp)", re.I)


def _common_fields(post_body: dict[str, Any]) -> dict[str, Any]:
    return {
        "post_id": str(post_body.get("id", "")),
        "creator_id": str(post_body.get("creatorId", "")),
        "user_name": str((post_body.get("user") or {}).get("name", "")),
        "title": str(post_body.get("title", "")),
        "fee": int(post_body.get("feeRequired") or 0),
        "published_dt": str(post_body.get("publishedDatetime", "")),
    }


def _image_item(image_data: dict[str, Any], index: int, base: dict[str, Any]) -> Optional[FileItem]:
    ext = image_data.get("extension")
    if not ext:
        return None
    original = image_data.get("originalUrl")
    thumbnail = image_data.get("thumbnailUrl")
    url = original or thumbnail
    if not url:
        return None
    return FileItem(
        index=index,
        name=str(image_data.get("id", "")),
        ext=str(ext),
        url=url,
        retry_url=thumbnail if thumbnail and thumbnail != url else None,
        size=None,
        **base,
    )


def _file_item(file_data: dict[str, Any], index: int, base: dict[str, Any]) -> Optional[FileItem]:
    ext = file_data.get("extension")
    url = file_data.get("url")
    if not ext or not url:
        return None
    return FileItem(
        index=index,
        name=str(file_data.get("name") or file_data.get("id") or ""),
        ext=str(ext),
        url=url,
        retry_url=None,
        size=file_data.get("size"),
        **base,
    )


def _parse_url_for_name_ext(url: str) -> tuple[str, str]:
    """从 URL 末段拆出 (name, ext)。"""
    tail = url.rsplit("/", 1)[-1].split("?", 1)[0]
    if "." in tail:
        name, ext = tail.rsplit(".", 1)
    else:
        name, ext = tail, ""
    return name, ext


def parse_post(post_body: dict[str, Any]) -> list[FileItem]:
    """post_body 是 post.info 响应的 body 字段（即 PostBody）。"""
    base = _common_fields(post_body)
    post_type = post_body.get("type")
    inner = post_body.get("body")

    if inner is None:
        # 因为价格限制 / 已删除，body 为 null
        return []

    files: list[FileItem] = []
    index = 0

    if post_type == "article":
        image_map = inner.get("imageMap") or {}
        file_map = inner.get("fileMap") or {}
        for block in inner.get("blocks", []) or []:
            block_type = block.get("type")
            if block_type == "image":
                data = image_map.get(block.get("imageId"))
                if data:
                    index += 1
                    item = _image_item(data, index, base)
                    if item:
                        files.append(item)
            elif block_type == "file":
                data = file_map.get(block.get("fileId"))
                if data:
                    index += 1
                    item = _file_item(data, index, base)
                    if item:
                        files.append(item)

    elif post_type == "image":
        for data in inner.get("images", []) or []:
            if not data:
                continue
            index += 1
            item = _image_item(data, index, base)
            if item:
                files.append(item)

    elif post_type == "file":
        for data in inner.get("files", []) or []:
            if not data:
                continue
            index += 1
            item = _file_item(data, index, base)
            if item:
                files.append(item)

    elif post_type == "entry":
        # entry 投稿是 html 字符串，用正则提取图片链接
        html = inner.get("html", "") or ""
        for m in _IMG_IN_HTML_RE.finditer(html):
            url = m.group(0)
            name, ext = _parse_url_for_name_ext(url)
            if not ext:
                continue
            index += 1
            files.append(
                FileItem(
                    index=index,
                    name=name,
                    ext=ext,
                    url=url,
                    retry_url=None,
                    size=None,
                    **base,
                )
            )

    # video / text 类型不产生文件，直接跳过

    return files


def extract_post_meta(post_list_item: dict[str, Any]) -> dict[str, Any]:
    """从 post.listSupporting / post.listCreator 的 items[i] 提取 list 阶段需要的字段。"""
    user = post_list_item.get("user") or {}
    return {
        "post_id": str(post_list_item.get("id", "")),
        "creator_id": str(post_list_item.get("creatorId") or user.get("userId") or ""),
        "user_name": str(user.get("name", "")),
        "user_icon_url": str(user.get("iconUrl") or ""),
        "title": str(post_list_item.get("title", "")),
        "fee": int(post_list_item.get("feeRequired") or 0),
        "published_dt": str(post_list_item.get("publishedDatetime", "")),
        "updated_dt": str(post_list_item.get("updatedDatetime", "")),
        "tags": list(post_list_item.get("tags") or []),
    }
