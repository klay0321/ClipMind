"""图片校验与派生工具（供产品参考图上传复用）。

- 魔数 + 扩展名校验（与既有 product_service 图片校验一致）。
- 宽高探测与缩略图生成复用**容器内已装的 ffprobe/ffmpeg**（api.Dockerfile 已装 ffmpeg），
  不引入 Pillow。二者均 **best-effort**：失败返回 None / False，不抛，供上传流程回退。
- 本阶段**不做任何视觉理解/质量判定**；缩略仅缩放，宽高仅探测。
"""

from __future__ import annotations

import asyncio
import os
import subprocess

# 支持的图片扩展名 → 魔数前缀（webp 另检 RIFF....WEBP）
IMAGE_MAGIC: dict[str, tuple[bytes, ...]] = {
    "jpg": (b"\xff\xd8\xff",),
    "jpeg": (b"\xff\xd8\xff",),
    "png": (b"\x89PNG\r\n\x1a\n",),
    "webp": (b"RIFF",),
}
# 扩展名 → 响应 Content-Type
CONTENT_TYPE = {
    "jpg": "image/jpeg",
    "jpeg": "image/jpeg",
    "png": "image/png",
    "webp": "image/webp",
}


def ext_of(filename: str) -> str | None:
    """返回受支持的小写扩展名（无扩展或不支持返回 None）。"""
    ext = os.path.splitext(filename or "")[1].lstrip(".").lower()
    return ext if ext in IMAGE_MAGIC else None


def looks_like_image(ext: str, head: bytes) -> bool:
    """按首字节魔数校验内容确为该类型图片。"""
    if ext == "webp":
        return head[:4] == b"RIFF" and head[8:12] == b"WEBP"
    return any(head.startswith(m) for m in IMAGE_MAGIC.get(ext, ()))


def _run(cmd: list[str], *, timeout: int = 20) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(cmd, capture_output=True, timeout=timeout, check=False)  # noqa: S603


async def probe_dimensions(path: str) -> tuple[int, int] | None:
    """ffprobe 探测图片宽高；失败返回 None（best-effort，不抛）。"""
    cmd = [
        "ffprobe", "-v", "error", "-select_streams", "v:0",
        "-show_entries", "stream=width,height", "-of", "csv=p=0:s=x", path,
    ]
    try:
        proc = await asyncio.to_thread(_run, cmd)
        if proc.returncode != 0:
            return None
        out = proc.stdout.decode("ascii", "ignore").strip().split("x")
        if len(out) == 2 and out[0].isdigit() and out[1].isdigit():
            return int(out[0]), int(out[1])
    except (OSError, ValueError, subprocess.SubprocessError):
        return None
    return None


async def make_thumbnail(src: str, dst: str, max_dim: int = 320) -> bool:
    """ffmpeg 生成 WebP 缩略图（等比缩小，不放大）；成功返回 True。

    best-effort：失败返回 False，调用方将 thumbnail_path 置空、前端回退原图。
    """
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    # 不放大：宽高任一超过 max_dim 才缩放；输出 WebP 单帧
    vf = (
        f"scale='if(gt(iw,ih),min({max_dim},iw),-2)':"
        f"'if(gt(iw,ih),-2,min({max_dim},ih))'"
    )
    cmd = ["ffmpeg", "-y", "-v", "error", "-i", src, "-vf", vf, "-frames:v", "1", dst]
    try:
        proc = await asyncio.to_thread(_run, cmd)
        return proc.returncode == 0 and os.path.isfile(dst)
    except (OSError, subprocess.SubprocessError):
        return False
