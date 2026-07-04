"""PR-F：产品视觉识别实验 API（只读候选；绝不写产品归属）。

安全边界：
- `VISUAL_RECOGNITION_ENABLED=false`（默认）时全部端点 403（明确实验未开启）；
- 候选/评测**零写入**：不改 AssetProduct / Shot / Onboarding / FinalVideoUsage /
  CatalogRevision，也不把候选存库；
- 临时上传图片：MIME/扩展名/大小/像素校验 + 内存处理，请求结束即弃，
  不落公司素材目录、不保存为参考图；
- 审计日志只记录计数与耗时，不含图片内容与绝对路径。
"""

from __future__ import annotations

import logging
import time

from clipmind_shared.ai.visual import VisualProviderError
from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings, get_settings
from app.db import get_db
from app.schemas.visual import (
    BenchmarkRequest,
    BenchmarkResponse,
    CandidateRequest,
    CandidateResponse,
    FamilyCandidateOut,
    ReferenceCoverageItem,
    ReferenceCoverageOut,
    VisualModelOut,
    VisualStatusOut,
)
from app.services import files
from app.services.visual_benchmark_service import BenchmarkSample, run_benchmark
from app.services.visual_candidate_service import (
    AGGREGATIONS,
    compute_candidates,
)
from app.services.visual_provider import LocalVisualProvider, get_visual_provider
from app.services.visual_reference_index import load_family_reference_sets

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/product-visual-experiments", tags=["visual-experiments"])

_ALLOWED_UPLOAD_TYPES = {"image/jpeg": "jpg", "image/png": "png", "image/webp": "webp"}


def _require_enabled(settings: Settings) -> None:
    if not settings.visual_recognition_enabled:
        raise HTTPException(
            status_code=403,
            detail="产品视觉识别实验未开启（VISUAL_RECOGNITION_ENABLED=false）",
        )


def _provider_or_503(settings: Settings):
    try:
        return get_visual_provider(settings)
    except VisualProviderError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@router.get("/status", response_model=VisualStatusOut)
async def status(
    db: AsyncSession = Depends(get_db), settings: Settings = Depends(get_settings)
) -> VisualStatusOut:
    enabled = settings.visual_recognition_enabled
    provider_name = settings.visual_embedding_provider
    ready = False
    reason: str | None = None if enabled else "实验未开启"
    model_id = settings.visual_model_id
    device = settings.visual_device
    if enabled:
        try:
            provider = get_visual_provider(settings)
            ident = provider.identity()
            provider_name, model_id, device = ident.provider, ident.model_id, ident.device
            if isinstance(provider, LocalVisualProvider):
                ready, reason = provider.ready()
            else:
                ready = True
        except VisualProviderError as exc:
            reason = str(exc)
    sets = await load_family_reference_sets(
        db, min_references=settings.visual_min_references
    )
    eligible = [s for s in sets if s.eligible]
    return VisualStatusOut(
        enabled=enabled,
        provider=provider_name,
        model_id=model_id,
        device=device,
        ready=ready,
        unavailable_reason=reason,
        eligible_family_count=len(eligible),
        eligible_reference_count=sum(len(s.references) for s in eligible),
        total_family_count=len(sets),
        thresholds={
            "min_score": settings.visual_min_score,
            "min_margin": settings.visual_min_margin,
            "confusion_margin": settings.visual_confusion_margin,
            "min_references": settings.visual_min_references,
            "calibrated": False,
        },
    )


@router.get("/models", response_model=list[VisualModelOut])
async def models(settings: Settings = Depends(get_settings)) -> list[VisualModelOut]:
    out = [
        VisualModelOut(
            provider="fake",
            model_id="fake-visual-deterministic-v1",
            dimension=32,
            device="cpu",
            license="n/a",
            notes="确定性假向量：仅供 CI/单测/E2E，不得用于真实验收",
        ),
        VisualModelOut(
            provider="local",
            model_id=settings.visual_model_id,
            dimension=768,
            device=settings.visual_device,
            license="Apache-2.0",
            notes="本地推理（embedder /visual-embeddings）；权重缓存于模型卷，不进镜像/Git",
        ),
    ]
    return out


@router.get("/reference-coverage", response_model=ReferenceCoverageOut)
async def reference_coverage(
    db: AsyncSession = Depends(get_db), settings: Settings = Depends(get_settings)
) -> ReferenceCoverageOut:
    sets = await load_family_reference_sets(
        db, min_references=settings.visual_min_references
    )
    items = [
        ReferenceCoverageItem(
            family_id=s.family_id,
            family_code=s.family_code,
            family_name=s.family_name,
            onboarding_status=s.onboarding_status,
            eligible=s.eligible,
            ineligible_reason=s.ineligible_reason,
            reference_count=len(s.references),
            angle_coverage=sorted({r.angle for r in s.references}),
            source_levels=sorted({r.source_level for r in s.references}),
        )
        for s in sets
    ]
    return ReferenceCoverageOut(
        items=items,
        eligible_count=sum(1 for s in sets if s.eligible),
        total_count=len(sets),
        min_references=settings.visual_min_references,
    )


async def _candidates_for_bytes(
    db: AsyncSession,
    settings: Settings,
    *,
    image: bytes,
    req: CandidateRequest,
    query_meta: dict,
) -> CandidateResponse:
    if req.target_level != "family":
        raise HTTPException(status_code=422, detail="本阶段 target_level 仅支持 family")
    if req.aggregation not in AGGREGATIONS:
        raise HTTPException(status_code=422, detail=f"未知聚合策略: {req.aggregation}")
    provider = _provider_or_503(settings)
    started = time.monotonic()
    result = await compute_candidates(
        db,
        query_image=image,
        provider=provider,
        settings=settings,
        top_k=req.top_k,
        min_score=req.min_score,
        min_margin=req.min_margin,
        aggregation=req.aggregation,
    )
    ident = provider.identity()
    logger.info(
        "visual candidates: decision=%s candidates=%d elapsed_ms=%d",
        result.decision, len(result.candidates),
        int((time.monotonic() - started) * 1000),
    )
    cands = [FamilyCandidateOut(**c.__dict__) for c in result.candidates]
    if not req.include_explanation:
        for c in cands:
            c.matched_angles = []
    return CandidateResponse(
        decision=result.decision,
        candidates=cands,
        top1_score=result.top1_score,
        top2_score=result.top2_score,
        margin=result.margin,
        thresholds=result.thresholds,
        aggregation=result.aggregation,
        model=ident.model_id,
        provider=ident.provider,
        device=ident.device,
        reference_snapshot={
            "eligible_family_count": len({c.target_id for c in result.candidates})
            if result.candidates else 0,
            "compared_reference_count": sum(
                c.embedded_reference_count for c in result.candidates
            ),
        },
        confusion_warning=result.confusion_warning,
        unavailable_reason=result.unavailable_reason,
        query=query_meta,
    )


@router.post("/candidates/shot/{shot_id}", response_model=CandidateResponse)
async def candidates_for_shot(
    shot_id: int,
    req: CandidateRequest,
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> CandidateResponse:
    _require_enabled(settings)
    from clipmind_shared.models import Shot

    shot = (await db.execute(select(Shot).where(Shot.id == shot_id))).scalar_one_or_none()
    if shot is None:
        raise HTTPException(status_code=404, detail="Shot 不存在")
    if not shot.keyframe_path:
        raise HTTPException(status_code=422, detail="Shot 无主关键帧，无法实验识别")
    abs_path = files.resolve_derived(shot.keyframe_path)
    with open(abs_path, "rb") as f:  # noqa: PTH123
        image = f.read()
    return await _candidates_for_bytes(
        db, settings, image=image, req=req,
        query_meta={
            "kind": "shot",
            "shot_id": shot.id,
            "generation": shot.generation,
            "is_historical": shot.retired_at is not None,
        },
    )


@router.post("/candidates/image", response_model=CandidateResponse)
async def candidates_for_image(
    file: UploadFile = File(...),
    top_k: int | None = None,
    aggregation: str = "top_k_mean",
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> CandidateResponse:
    """临时上传图片实验：内存处理，请求结束即弃，不保存、不写素材目录。"""
    _require_enabled(settings)
    ctype = (file.content_type or "").lower()
    if ctype not in _ALLOWED_UPLOAD_TYPES:
        raise HTTPException(status_code=422, detail=f"不支持的图片类型: {ctype or '未知'}")
    name = (file.filename or "").lower()
    if name and name.rsplit(".", 1)[-1] not in ("jpg", "jpeg", "png", "webp"):
        raise HTTPException(status_code=422, detail="不支持的扩展名")
    image = await file.read()
    if len(image) > settings.visual_upload_max_bytes:
        raise HTTPException(status_code=422, detail="图片超过大小上限")
    if not image:
        raise HTTPException(status_code=422, detail="空文件")
    req = CandidateRequest(top_k=top_k, aggregation=aggregation)
    return await _candidates_for_bytes(
        db, settings, image=image, req=req,
        query_meta={"kind": "upload", "content_type": ctype, "size_bytes": len(image)},
    )


@router.post("/benchmark", response_model=BenchmarkResponse)
async def benchmark(
    req: BenchmarkRequest,
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> BenchmarkResponse:
    _require_enabled(settings)
    if req.aggregation not in AGGREGATIONS:
        raise HTTPException(status_code=422, detail=f"未知聚合策略: {req.aggregation}")
    provider = _provider_or_503(settings)
    samples = [
        BenchmarkSample(
            kind=s.kind,
            reference_id=s.reference_id,
            shot_id=s.shot_id,
            ground_truth_family_id=s.ground_truth_family_id,
            is_unknown=s.is_unknown,
            sample_type=s.sample_type,
            source=s.source,
        )
        for s in req.samples
    ]
    report = await run_benchmark(
        db, samples=samples, provider=provider, settings=settings,
        aggregation=req.aggregation,
    )
    ident = provider.identity()
    return BenchmarkResponse(
        total_samples=report.total_samples,
        evaluated=report.evaluated,
        skipped=report.skipped,
        product_samples=report.product_samples,
        unknown_samples=report.unknown_samples,
        family_count=report.family_count,
        metrics=report.metrics,
        per_family=report.per_family,
        groups=report.groups,
        confusion_matrix=report.confusion_matrix,
        curves=report.curves,
        data_gaps=report.data_gaps,
        outcomes=report.outcomes if req.include_outcomes else [],
        model=ident.model_id,
        provider=ident.provider,
    )
