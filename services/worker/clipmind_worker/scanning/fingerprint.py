"""快速变化指纹：sha256(size + 头 64KiB + 尾 64KiB)。

只在新增或 size/mtime 变化时计算（分层变化检测），不每次读取所有文件。
全程以只读模式打开源文件。quick_hash 仅作变化指纹，不作完整内容去重依据
（完整去重的 full_hash 留待后续 PR）。
"""

from __future__ import annotations

import hashlib

from clipmind_shared.constants import QUICK_HASH_CHUNK


def compute_quick_hash(path: str, size: int) -> str:
    h = hashlib.sha256()
    h.update(str(size).encode("ascii"))
    with open(path, "rb") as f:  # 只读，绝不写源文件
        h.update(f.read(QUICK_HASH_CHUNK))
        if size > QUICK_HASH_CHUNK:
            f.seek(max(0, size - QUICK_HASH_CHUNK))
            h.update(f.read(QUICK_HASH_CHUNK))
    return h.hexdigest()
