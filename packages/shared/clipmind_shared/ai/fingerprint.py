"""AI 分析输入指纹（PR-03A）。

指纹 = sha256( 规范化 JSON{provider, model, prompt_version, schema_version, params,
frames:[每帧内容 sha256（有序）]} )。用于缓存去重：相同输入命中已 completed 的分析则
跳过、不重复计费（AI_PROVIDER_PLAN 5.3）。
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

_CHUNK = 1024 * 1024


def hash_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def hash_file(path: str) -> str:
    """文件内容 sha256（分块读取，只读）。"""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while True:
            chunk = f.read(_CHUNK)
            if not chunk:
                break
            h.update(chunk)
    return h.hexdigest()


def compute_fingerprint(
    *,
    frame_hashes: list[str],
    provider: str,
    model: str,
    prompt_version: str,
    schema_version: int,
    params: dict[str, Any] | None = None,
) -> str:
    """对给定输入计算稳定指纹（与字段顺序无关）。"""
    payload = {
        "provider": provider,
        "model": model,
        "prompt_version": prompt_version,
        "schema_version": schema_version,
        "params": params or {},
        "frames": list(frame_hashes),
    }
    blob = json.dumps(payload, sort_keys=True, ensure_ascii=True, separators=(",", ":"))
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()
