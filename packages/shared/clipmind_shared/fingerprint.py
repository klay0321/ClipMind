"""分级内容指纹（PR-C 稳定素材身份）。

三层身份语义（docs/ASSET_IDENTITY.md，测试锁定）：
- 候选筛选层：size / duration / 容器 / 宽高 / mtime —— 只筛候选，不认定同一内容；
- Quick Fingerprint：sha256(size + 头 / 中 / 尾 各 QUICK_FP_BLOCK 字节)，带算法版本。
  用于快速筛选疑似移动与决定是否值得算完整哈希；**不能单独作为权威身份**，
  也不能据此自动合并有业务数据的 Asset；
- Full SHA256：完整字节内容哈希，唯一权威身份。转码/裁剪/调色/变速版哈希不同,
  本阶段视为不同内容（视觉近似属 PR-H）。

安全约束：
- 源文件只读打开（"rb"），绝不写；
- 分块读取（不可一次 read 全文件）；
- 计算前后核对 size + mtime_ns，期间变化则抛 FileChangedDuringHashing（结果作废）；
- 哈希不是安全秘密，但公司真实哈希不进入 Git / PR 描述。

注意：本模块与 clipmind_worker.scanning.fingerprint.compute_quick_hash（扫描层
变化指纹：size+头/尾 64KiB，无版本）语义不同——那是"文件变没变"的廉价信号，
这里是"内容身份候选"。两者并存，不互相替代。
"""

from __future__ import annotations

import hashlib
import os
from collections.abc import Callable
from dataclasses import dataclass

# Quick Fingerprint：头 / 中 / 尾 各 1 MiB；文件小于 3 块时退化为全文件读取
QUICK_FP_BLOCK = 1024 * 1024
QUICK_FP_VERSION = "qfp1"

# Full hash 分块大小（8 MiB：顺序读对 NAS 友好，内存占用可控）
FULL_HASH_CHUNK = 8 * 1024 * 1024
FULL_HASH_ALGORITHM = "sha256"


class FileChangedDuringHashing(Exception):
    """计算期间文件 size/mtime 发生变化，本次结果作废。"""


@dataclass(frozen=True)
class FileStamp:
    """计算前后核对用的文件戳（不含路径，不含内容）。"""

    size: int
    mtime_ns: int

    @classmethod
    def of(cls, path: str) -> "FileStamp":
        st = os.stat(path)
        return cls(size=st.st_size, mtime_ns=st.st_mtime_ns)


@dataclass(frozen=True)
class QuickFingerprint:
    value: str
    version: str
    size: int


@dataclass(frozen=True)
class FullHash:
    value: str
    algorithm: str
    size: int


def compute_quick_fingerprint(path: str) -> QuickFingerprint:
    """身份候选指纹：sha256(size + 头/中/尾块)。O(3MiB) IO，与文件总大小无关。"""
    before = FileStamp.of(path)
    h = hashlib.sha256()
    h.update(str(before.size).encode("ascii"))
    with open(path, "rb") as f:  # 只读，绝不写源文件
        if before.size <= 3 * QUICK_FP_BLOCK:
            # 小文件整读（分块），quick == 全内容摘要的退化形式
            while chunk := f.read(QUICK_FP_BLOCK):
                h.update(chunk)
        else:
            h.update(f.read(QUICK_FP_BLOCK))
            f.seek((before.size // 2) - (QUICK_FP_BLOCK // 2))
            h.update(f.read(QUICK_FP_BLOCK))
            f.seek(before.size - QUICK_FP_BLOCK)
            h.update(f.read(QUICK_FP_BLOCK))
    after = FileStamp.of(path)
    if after != before:
        raise FileChangedDuringHashing(
            f"quick fingerprint 期间文件变化: size {before.size}->{after.size}"
        )
    return QuickFingerprint(value=h.hexdigest(), version=QUICK_FP_VERSION, size=before.size)


def compute_full_sha256(
    path: str,
    *,
    chunk_size: int = FULL_HASH_CHUNK,
    progress_cb: Callable[[int, int], None] | None = None,
) -> FullHash:
    """完整内容 SHA256（分块顺序读；前后核对 size+mtime_ns，期间变化即作废）。

    progress_cb(bytes_done, bytes_total) 供任务进度上报，允许为 None。
    """
    before = FileStamp.of(path)
    h = hashlib.sha256()
    done = 0
    with open(path, "rb") as f:  # 只读，绝不写源文件
        while chunk := f.read(chunk_size):
            h.update(chunk)
            done += len(chunk)
            if progress_cb is not None:
                progress_cb(done, before.size)
    after = FileStamp.of(path)
    if after != before:
        raise FileChangedDuringHashing(
            f"full hash 期间文件变化: size {before.size}->{after.size}, "
            f"mtime_ns {before.mtime_ns}->{after.mtime_ns}"
        )
    if done != before.size:
        raise FileChangedDuringHashing(f"读取字节数 {done} 与文件大小 {before.size} 不一致")
    return FullHash(value=h.hexdigest(), algorithm=FULL_HASH_ALGORITHM, size=before.size)


def short_hash(value: str | None, length: int = 12) -> str | None:
    """展示用缩短哈希（前端默认不暴露完整哈希）。"""
    if not value:
        return None
    return value[:length]
