"""OpenAI 兼容的本地 Embedding 服务（FastAPI）。

端点：
- ``GET /health``：进程存活即 200（**不代表模型已加载**）；
- ``GET /ready``：模型成功加载后才 200，否则 503；
- ``POST /embeddings``：OpenAI 兼容；模型未就绪 → 503，输入非法 → 400。

模型在后台线程加载，故服务可先接受连接、/health 立即可用、/ready 待加载完成。
不记录业务文本与密钥。
"""

from __future__ import annotations

import logging
import threading
from typing import Any

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from embedder.config import get_settings

logger = logging.getLogger("embedder")

app = FastAPI(title="ClipMind Embedder", version="0.1.0")

# 模型持有器（后台线程加载）
_state: dict[str, Any] = {"model": None, "ready": False, "error": None}
_lock = threading.Lock()


class EmbeddingRequest(BaseModel):
    input: str | list[str]
    model: str | None = None


def _load_model() -> None:
    settings = get_settings()
    try:
        # 惰性导入：torch / sentence-transformers 仅在本服务镜像内存在
        from sentence_transformers import SentenceTransformer

        model = SentenceTransformer(
            settings.embedder_model,
            revision=settings.embedder_model_revision or None,
            device=settings.embedder_device,
            cache_folder=settings.embedder_cache_dir,
        )
        with _lock:
            _state["model"] = model
            _state["ready"] = True
        logger.info("embedder 模型已加载: %s", settings.embedder_model)
    except Exception as exc:  # noqa: BLE001
        with _lock:
            _state["error"] = f"{type(exc).__name__}: {exc}"
        logger.error("embedder 模型加载失败: %s", type(exc).__name__)


@app.on_event("startup")
def _startup() -> None:
    threading.Thread(target=_load_model, name="embedder-load", daemon=True).start()


@app.get("/health")
def health() -> dict[str, Any]:
    return {"status": "ok", "ready": bool(_state["ready"])}


@app.get("/ready")
def ready() -> dict[str, Any]:
    if _state["ready"]:
        s = get_settings()
        return {"status": "ready", "model": s.embedder_model, "dimension": s.embedder_dimension}
    raise HTTPException(status_code=503, detail=_state["error"] or "模型加载中")


@app.post("/embeddings")
def embeddings(req: EmbeddingRequest) -> dict[str, Any]:
    settings = get_settings()
    if not _state["ready"]:
        raise HTTPException(status_code=503, detail=_state["error"] or "模型未就绪")

    inputs = [req.input] if isinstance(req.input, str) else list(req.input)
    if not inputs:
        raise HTTPException(status_code=400, detail="input 不能为空")
    if len(inputs) > settings.embedder_max_batch:
        raise HTTPException(
            status_code=400,
            detail=f"批量超限：{len(inputs)} > {settings.embedder_max_batch}",
        )
    inputs = [(t or "")[: settings.embedder_max_input_chars] for t in inputs]

    model = _state["model"]
    try:
        vectors = model.encode(
            inputs,
            normalize_embeddings=settings.embedder_normalize,
            convert_to_numpy=True,
        )
    except Exception as exc:  # noqa: BLE001 - OOM/推理错误统一 500
        logger.error("嵌入推理失败: %s", type(exc).__name__)
        raise HTTPException(status_code=500, detail=f"嵌入失败: {type(exc).__name__}") from exc

    data = []
    for idx, vec in enumerate(vectors):
        emb = vec.tolist()
        if len(emb) != settings.embedder_dimension:
            raise HTTPException(
                status_code=500,
                detail=f"维度不符：{len(emb)} != {settings.embedder_dimension}",
            )
        data.append({"object": "embedding", "index": idx, "embedding": emb})

    total_chars = sum(len(t) for t in inputs)
    return {
        "object": "list",
        "data": data,
        "model": settings.embedder_model,
        "usage": {"prompt_tokens": total_chars, "total_tokens": total_chars},
    }
