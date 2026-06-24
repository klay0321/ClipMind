"""派生文件安全服务：把存库的相对路径解析到 data_dir 内并以 FileResponse 提供。

- 仅服务系统派生数据目录（data_dir）内的文件；经 safe_join_within_root 防穿越。
- 绝不接受前端传入的任意路径；绝不返回服务器绝对路径。
- 不可变派生文件使用长缓存；代理视频经 FileResponse 原生支持 HTTP Range。
"""

from __future__ import annotations

import os

from clipmind_shared.security import safe_join_within_root
from fastapi import HTTPException
from fastapi.responses import FileResponse

from app.config import get_settings

# 不可变派生文件（关键帧/缩略图/代理）的长缓存
IMMUTABLE_CACHE = "public, max-age=31536000, immutable"


def resolve_derived(rel_path: str | None) -> str:
    """把相对派生路径解析为 data_dir 下的绝对路径并校验包含。

    Raises:
        HTTPException(404): rel_path 为空或文件不存在。
        clipmind_shared.security.PathTraversal: 解析后跳出 data_dir（全局映射 422）。
    """
    if not rel_path:
        raise HTTPException(status_code=404, detail="派生文件不存在")
    settings = get_settings()
    data_root = os.path.realpath(settings.data_dir)
    abs_path = safe_join_within_root(data_root, rel_path)
    if not os.path.isfile(abs_path):
        raise HTTPException(status_code=404, detail="派生文件不存在")
    return abs_path


def serve_derived(
    rel_path: str | None,
    *,
    media_type: str,
    download_name: str | None = None,
    immutable: bool = True,
) -> FileResponse:
    """返回 FileResponse（支持 Range/206/416 由 Starlette 处理）。

    download_name 非空时作为附件下载（Content-Disposition 自动 RFC5987 编码，支持中文）。
    """
    abs_path = resolve_derived(rel_path)
    headers = {"Cache-Control": IMMUTABLE_CACHE} if immutable else None
    return FileResponse(
        abs_path,
        media_type=media_type,
        filename=download_name,
        headers=headers,
    )
