"""PR-C 素材身份服务：身份汇总 / 位置历史 / 指纹任务 / 分析代次。

所有返回值均为只读派生：identity_state 来自 Asset 行；位置计数来自 asset_location；
代次来自 MediaProcessingRun + Shot 聚合。绝不返回绝对路径；哈希只给缩短形式。
"""

from __future__ import annotations

from clipmind_shared.db.base import utcnow
from clipmind_shared.fingerprint import short_hash
from clipmind_shared.models import (
    Asset,
    AssetLocation,
    FinalVideoUsage,
    FingerprintJob,
    MediaProcessingRun,
    Shot,
    SourceDirectory,
)
from clipmind_shared.models.enums import MediaRunStatus, ShotStatus
from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.schemas.identity import (
    AnalysisGenerationOut,
    AnalysisGenerationsOut,
    AssetIdentityOut,
    AssetLocationOut,
    FingerprintJobOut,
)
from app.tasks_client import enqueue_fingerprint_job


async def _get_asset_or_404(db: AsyncSession, asset_id: int) -> Asset:
    asset = await db.get(Asset, asset_id)
    if asset is None:
        raise HTTPException(status_code=404, detail="素材不存在")
    return asset


async def list_locations(db: AsyncSession, asset_id: int) -> list[AssetLocationOut]:
    await _get_asset_or_404(db, asset_id)
    rows = (
        await db.execute(
            select(AssetLocation, SourceDirectory.name)
            .join(SourceDirectory, SourceDirectory.id == AssetLocation.source_root_id)
            .where(AssetLocation.asset_id == asset_id)
            .order_by(
                AssetLocation.is_primary.desc(),
                AssetLocation.last_seen_at.desc(),
            )
        )
    ).all()
    outs: list[AssetLocationOut] = []
    for loc, root_name in rows:
        out = AssetLocationOut.model_validate(loc)
        out.source_root_name = root_name
        outs.append(out)
    return outs


async def get_identity(db: AsyncSession, asset_id: int) -> AssetIdentityOut:
    asset = await _get_asset_or_404(db, asset_id)
    locations = await list_locations(db, asset_id)

    # 代次汇总（历史 = 出现过 Shot 的非当前代次数）
    current_gen = await db.scalar(
        select(func.max(Shot.generation)).where(
            Shot.asset_id == asset_id, Shot.retired_at.is_(None)
        )
    )
    gen_count = await db.scalar(
        select(func.count(func.distinct(Shot.generation))).where(
            Shot.asset_id == asset_id
        )
    )
    historical = max(int(gen_count or 0) - (1 if current_gen is not None else 0), 0)

    out = AssetIdentityOut(
        asset_id=asset.id,
        fingerprint_state=asset.fingerprint_state,
        quick_fingerprint_short=short_hash(asset.quick_fingerprint),
        quick_fingerprint_version=asset.quick_fingerprint_version,
        full_hash_short=short_hash(asset.full_hash),
        full_hash_algorithm=asset.full_hash_algorithm,
        full_hash_available=asset.full_hash is not None,
        content_size=asset.content_size,
        fingerprinted_at=asset.fingerprinted_at,
        fingerprint_error=asset.fingerprint_error,
        location_count=len(locations),
        present_location_count=sum(
            1 for loc in locations if loc.location_status == "present"
        ),
        missing_location_count=sum(
            1 for loc in locations if loc.location_status == "missing"
        ),
        conflict_location_count=sum(
            1 for loc in locations if loc.location_status == "conflict"
        ),
        primary_location=next((loc for loc in locations if loc.is_primary), None),
        locations=locations,
        current_generation=current_gen,
        historical_generation_count=historical,
    )
    return out


async def request_fingerprints(
    db: AsyncSession, asset_ids: list[int], kind: str
) -> FingerprintJob:
    """创建指纹任务并入队（幂等性在 worker 侧：已 full_ready 且未变化则 skip）。"""
    existing = set(
        (
            await db.scalars(select(Asset.id).where(Asset.id.in_(asset_ids)))
        ).all()
    )
    unknown = [aid for aid in asset_ids if aid not in existing]
    if unknown:
        raise HTTPException(status_code=404, detail=f"素材不存在: {unknown[:5]}")

    job = FingerprintJob(
        kind=kind,
        asset_ids=asset_ids,
        status="queued",
        total_count=len(asset_ids),
        created_at=utcnow(),
    )
    db.add(job)
    await db.commit()
    await db.refresh(job)
    try:
        task_id = enqueue_fingerprint_job(job.id)
    except Exception as exc:  # noqa: BLE001
        job.status = "failed"
        job.error_message = f"入队失败: {exc}"[:2000]
        job.finished_at = utcnow()
        await db.commit()
        raise HTTPException(status_code=503, detail=f"无法入队指纹任务: {exc}") from exc
    job.celery_task_id = task_id
    await db.commit()
    await db.refresh(job)
    return job


async def get_fingerprint_job(db: AsyncSession, job_id: int) -> FingerprintJobOut:
    job = await db.get(FingerprintJob, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="指纹任务不存在")
    return FingerprintJobOut.model_validate(job)


async def list_analysis_generations(
    db: AsyncSession, asset_id: int
) -> AnalysisGenerationsOut:
    await _get_asset_or_404(db, asset_id)
    current_gen = await db.scalar(
        select(func.max(Shot.generation)).where(
            Shot.asset_id == asset_id, Shot.retired_at.is_(None)
        )
    )
    runs = (
        await db.scalars(
            select(MediaProcessingRun)
            .where(
                MediaProcessingRun.asset_id == asset_id,
                MediaProcessingRun.status == MediaRunStatus.COMPLETED,
            )
            .order_by(MediaProcessingRun.generation.desc())
        )
    ).all()
    # 各代次镜头数与被血缘引用数（一次分组聚合）
    shot_counts = {
        gen: cnt
        for gen, cnt in (
            await db.execute(
                select(Shot.generation, func.count(Shot.id))
                .where(Shot.asset_id == asset_id, Shot.status == ShotStatus.READY)
                .group_by(Shot.generation)
            )
        ).all()
    }
    usage_counts = {
        gen: cnt
        for gen, cnt in (
            await db.execute(
                select(Shot.generation, func.count(func.distinct(Shot.id)))
                .join(FinalVideoUsage, FinalVideoUsage.source_shot_id == Shot.id)
                .where(Shot.asset_id == asset_id)
                .group_by(Shot.generation)
            )
        ).all()
    }
    items = [
        AnalysisGenerationOut(
            generation=r.generation,
            run_id=r.id,
            status=r.status.value,
            is_current=(r.generation == current_gen),
            shot_count=shot_counts.get(r.generation, 0),
            usage_referenced_count=usage_counts.get(r.generation, 0),
            created_at=r.queued_at,
            finished_at=r.finished_at,
        )
        for r in runs
    ]
    return AnalysisGenerationsOut(
        asset_id=asset_id, current_generation=current_gen, items=items
    )
