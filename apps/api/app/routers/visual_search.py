"""IMG-SEARCH：以图搜图（对全库素材/镜头的视觉向量做相似检索）。

复用 VIS-AUTO 的持久化向量（visual_media_embedding，HNSW cosine）：
上传一张图 → 视觉 provider 算查询向量 → 只与**同 provider/同模型**的
completed 向量比对（跨模型距离无意义）→ 返回相似素材/镜头。

安全边界与 PR-F 一致：上传图内存处理请求结束即弃；零写入；
`VISUAL_RECOGNITION_ENABLED=false` 时 403；日志不含图片内容与绝对路径。
"""

from __future__ import annotations

import logging
import time

from clipmind_shared.ai.visual import VisualProviderError
from clipmind_shared.models import Asset, Shot, VisualMediaEmbedding
from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings, get_settings
from app.db import get_db

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/search", tags=["visual-search"])

_ALLOWED_UPLOAD_TYPES = {"image/jpeg", "image/png", "image/webp"}


class VisualHit(BaseModel):
    kind: str                      # asset | shot
    score: float                   # 余弦相似度（1 - cosine_distance）
    asset_id: int | None = None
    shot_id: int | None = None
    filename: str | None = None
    media_kind: str | None = None
    sequence_no: int | None = None
    start_time: float | None = None
    end_time: float | None = None
    is_historical: bool | None = None


class VisualSearchOut(BaseModel):
    provider: str
    model: str
    total_indexed: int             # 参与比对的向量行数（同 provider/模型、completed）
    hits: list[VisualHit]


@router.post("/by-image", response_model=VisualSearchOut)
async def search_by_image(
    file: UploadFile = File(...),
    top_k: int = Query(24, ge=1, le=100),
    kind: str = Query("all"),  # all | asset | shot
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> VisualSearchOut:
    """临时上传图片以图搜图：内存处理，请求结束即弃，不保存。"""
    if not settings.visual_recognition_enabled:
        raise HTTPException(
            status_code=403,
            detail="视觉功能未开启（VISUAL_RECOGNITION_ENABLED=false）",
        )
    if kind not in ("all", "asset", "shot"):
        raise HTTPException(status_code=422, detail=f"未知目标类型: {kind}")
    ctype = (file.content_type or "").lower()
    if ctype not in _ALLOWED_UPLOAD_TYPES:
        raise HTTPException(status_code=422, detail=f"不支持的图片类型: {ctype or '未知'}")
    image = await file.read()
    if not image:
        raise HTTPException(status_code=422, detail="空图片")
    if len(image) > settings.visual_upload_max_bytes:
        raise HTTPException(
            status_code=413,
            detail=f"图片超过上限 {settings.visual_upload_max_bytes // (1024 * 1024)}MB",
        )

    from app.services.visual_provider import get_visual_provider

    try:
        provider = get_visual_provider(settings)
        started = time.monotonic()
        qvec = provider.embed_images([image])[0]
    except VisualProviderError as exc:
        raise HTTPException(status_code=503, detail=f"视觉模型不可用: {exc}") from exc
    ident = provider.identity()

    base = [
        VisualMediaEmbedding.provider == ident.provider,
        VisualMediaEmbedding.model_id == ident.model_id,
        VisualMediaEmbedding.status == "completed",
        VisualMediaEmbedding.embedding.is_not(None),
    ]
    kinds = ["asset", "shot"] if kind == "all" else [kind]
    base.append(VisualMediaEmbedding.target_type.in_(kinds))

    from sqlalchemy import func

    total_indexed = (
        await db.execute(
            select(func.count()).select_from(VisualMediaEmbedding).where(*base)
        )
    ).scalar_one()

    dist = VisualMediaEmbedding.embedding.cosine_distance(qvec)
    rows = (
        await db.execute(
            select(
                VisualMediaEmbedding.target_type,
                VisualMediaEmbedding.target_id,
                dist.label("distance"),
            )
            .where(*base)
            .order_by(dist.asc(), VisualMediaEmbedding.target_id.asc())  # 确定性
            .limit(top_k)
        )
    ).all()

    asset_ids = {tid for tt, tid, _d in rows if tt == "asset"}
    shot_ids = {tid for tt, tid, _d in rows if tt == "shot"}
    assets = {
        a.id: a
        for a in (
            await db.execute(select(Asset).where(Asset.id.in_(asset_ids or {0})))
        ).scalars()
    }
    shots = {
        s.id: s
        for s in (
            await db.execute(select(Shot).where(Shot.id.in_(shot_ids or {0})))
        ).scalars()
    }
    # shot 归属的 asset（文件名展示用）
    shot_asset_ids = {s.asset_id for s in shots.values()} - set(assets)
    for a in (
        await db.execute(select(Asset).where(Asset.id.in_(shot_asset_ids or {0})))
    ).scalars():
        assets[a.id] = a

    hits: list[VisualHit] = []
    for tt, tid, d in rows:
        score = round(max(-1.0, min(1.0, 1.0 - float(d))), 6)
        if tt == "asset":
            a = assets.get(tid)
            if a is None:
                continue  # 目标已删除，向量行滞后——跳过不报错
            hits.append(
                VisualHit(
                    kind="asset", score=score, asset_id=a.id,
                    filename=a.filename, media_kind=a.media_kind,
                )
            )
        else:
            s = shots.get(tid)
            if s is None:
                continue
            a = assets.get(s.asset_id)
            hits.append(
                VisualHit(
                    kind="shot", score=score, shot_id=s.id, asset_id=s.asset_id,
                    filename=a.filename if a else None,
                    sequence_no=s.sequence_no,
                    start_time=s.start_time, end_time=s.end_time,
                    is_historical=s.retired_at is not None,
                )
            )
    logger.info(
        "visual search: hits=%d indexed=%d elapsed_ms=%d",
        len(hits), total_indexed, int((time.monotonic() - started) * 1000),
    )
    return VisualSearchOut(
        provider=ident.provider, model=ident.model_id,
        total_indexed=int(total_indexed), hits=hits,
    )
