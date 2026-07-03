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


# ---------------- PR-F 视觉嵌入（实验；惰性单例加载） ----------------
# 与文本 e5 完全独立：不影响启动、/ready 与文本端点；只有首个视觉请求才加载
# 权重（下载至 cache_dir 卷）。加载失败显式 503 并保留原因，绝不静默回退。

_visual_state: dict[str, Any] = {"model": None, "processor": None, "ready": False,
                                 "error": None, "loading": False}
_visual_lock = threading.Lock()


class VisualEmbeddingRequest(BaseModel):
    images: list[str]  # base64（不落盘、不记录内容）
    model: str | None = None


def _load_visual_model() -> None:
    settings = get_settings()
    try:
        import torch  # noqa: F401 —— 校验 torch 可用

        # 只加载视觉塔：图像嵌入不需要文本塔/tokenizer（避免 SentencePiece 依赖，
        # 内存也减半）。SigLIP 视觉 pooler 输出即对齐空间向量（无独立投影层）。
        from transformers import SiglipImageProcessor, SiglipVisionModel

        kwargs: dict[str, Any] = {"cache_dir": settings.embedder_cache_dir}
        if settings.visual_model_revision:
            kwargs["revision"] = settings.visual_model_revision
        processor = SiglipImageProcessor.from_pretrained(settings.visual_model, **kwargs)
        model = SiglipVisionModel.from_pretrained(settings.visual_model, **kwargs)
        model = model.to(settings.visual_device)
        model.eval()
        with _visual_lock:
            _visual_state.update(model=model, processor=processor, ready=True, loading=False)
        logger.info("视觉模型已加载: %s", settings.visual_model)
    except Exception as exc:  # noqa: BLE001
        with _visual_lock:
            _visual_state.update(error=f"{type(exc).__name__}: {exc}", loading=False)
        logger.error("视觉模型加载失败: %s", type(exc).__name__)


def _ensure_visual_loading() -> None:
    with _visual_lock:
        if _visual_state["ready"] or _visual_state["loading"] or _visual_state["error"]:
            return
        _visual_state["loading"] = True
    threading.Thread(target=_load_visual_model, name="visual-load", daemon=True).start()


@app.get("/visual-ready")
def visual_ready() -> dict[str, Any]:
    """视觉模型状态（不触发加载）。"""
    s = get_settings()
    return {
        "ready": bool(_visual_state["ready"]),
        "loading": bool(_visual_state["loading"]),
        "error": _visual_state["error"],
        "model": s.visual_model,
        "dimension": s.visual_dimension,
        "device": s.visual_device,
    }


@app.post("/visual-embeddings")
def visual_embeddings(req: VisualEmbeddingRequest) -> dict[str, Any]:
    """图片批量嵌入：base64 → 统一预处理（解码/RGB/resize/归一化/batch）→
    L2 归一化向量。首次调用触发惰性加载（加载中返回 503 + retry 提示）。"""
    import base64 as b64
    import io

    settings = get_settings()
    if not req.images:
        raise HTTPException(status_code=400, detail="images 不能为空")
    if len(req.images) > settings.visual_max_batch:
        raise HTTPException(
            status_code=400,
            detail=f"批量超限：{len(req.images)} > {settings.visual_max_batch}",
        )
    _ensure_visual_loading()
    if not _visual_state["ready"]:
        detail = _visual_state["error"] or "视觉模型加载中，请稍后重试"
        raise HTTPException(status_code=503, detail=detail)

    from PIL import Image

    pil_images = []
    for idx, payload in enumerate(req.images):
        try:
            raw = b64.b64decode(payload, validate=True)
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(status_code=400, detail=f"图片 {idx} base64 非法") from exc
        if len(raw) > settings.visual_max_image_bytes:
            raise HTTPException(status_code=400, detail=f"图片 {idx} 超过大小上限")
        try:
            img = Image.open(io.BytesIO(raw))
            img.load()
            pil_images.append(img.convert("RGB"))
        except Exception as exc:  # noqa: BLE001 —— 解码失败必须显式报错，绝不产生零向量
            raise HTTPException(
                status_code=422, detail=f"图片 {idx} 解码失败: {type(exc).__name__}"
            ) from exc

    import torch

    model = _visual_state["model"]
    processor = _visual_state["processor"]
    try:
        with torch.no_grad():
            inputs = processor(images=pil_images, return_tensors="pt").to(
                settings.visual_device
            )
            feats = model(**inputs).pooler_output  # SiglipVisionModel 视觉塔输出
            feats = torch.nn.functional.normalize(feats, p=2, dim=-1)
    except Exception as exc:  # noqa: BLE001 - OOM/推理错误统一 500，安全失败
        logger.error("视觉推理失败: %s", type(exc).__name__)
        raise HTTPException(status_code=500, detail=f"视觉推理失败: {type(exc).__name__}") from exc

    data = [
        {"object": "embedding", "index": i, "embedding": vec.tolist()}
        for i, vec in enumerate(feats.cpu())
    ]
    if data and len(data[0]["embedding"]) != settings.visual_dimension:
        raise HTTPException(
            status_code=500,
            detail=f"维度不符：{len(data[0]['embedding'])} != {settings.visual_dimension}",
        )
    return {
        "object": "list",
        "data": data,
        "model": settings.visual_model,
        "dimension": settings.visual_dimension,
    }


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
