"""PR-B：最终成片与 Shot 使用血缘业务逻辑。

职责：FinalVideo CRUD（引用已有 Asset，不复制视频）、归档/恢复、Usage 引用关系
（手工添加 / 从项目生成候选 / 确认 / 驳回 / 撤销 / 恢复候选）、Occurrence 时间段、
append-only 事件审计、Shot/Asset 使用统计。

正式使用次数语义（详见 docs/FINAL_VIDEO_USAGE.md，测试锁定）：
- 正式使用次数 = 引用该 Shot 的 **confirmed** FinalVideoUsage 行数
  （UNIQUE(final_video_id, source_shot_id) ⇒ 天然按成片去重）；
- proposed/suspected/rejected/revoked 一律不计数；occurrence 不影响计数；
- 计数永远是实时聚合（无缓存列、无手工输入入口）；撤销后立即反映。

安全/正确性要点：
- 所有状态转换 SELECT ... FOR UPDATE + 同事务写事件（append-only），并发确认不产生重复；
- 手工添加只允许 evidence_method=manual；confirm 仅允许 CONFIRMABLE_EVIDENCE_METHODS；
- archived FinalVideo 一律只读（除恢复）；rejected 须先恢复 proposed 才能再确认；
- propose-from-project 幂等：已存在关系（任何状态）绝不覆盖；
- 自引用守卫：Source Shot 所属 Asset 不得与成片 Asset 相同；
- 绝不物理删除 FinalVideo/Usage；occurrence 删除是正常编辑且留事件。
"""

from __future__ import annotations

import math
from collections import defaultdict
from datetime import datetime
from typing import Any

from clipmind_shared.db.base import utcnow
from clipmind_shared.models import (
    Asset,
    FinalVideo,
    FinalVideoUsage,
    FinalVideoUsageEvent,
    FinalVideoUsageOccurrence,
    Product,
    Project,
    ScriptProject,
    ScriptSegment,
    Shot,
    ShotReviewState,
)
from clipmind_shared.models.enums import (
    CONFIRMABLE_EVIDENCE_METHODS,
    AssetStatus,
    FinalVideoStatus,
    FinalVideoUsageStatus,
    ShotStatus,
)
from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.schemas.final_video import (
    AssetUsageSummaryOut,
    FinalVideoBriefOut,
    FinalVideoCreateRequest,
    FinalVideoLineageOut,
    FinalVideoOut,
    FinalVideoUpdateRequest,
    FinalVideoUsageStatsOut,
    OccurrenceCreateRequest,
    OccurrenceOut,
    OccurrenceUpdateRequest,
    ProposeFromProjectOut,
    ShotUsageCountOut,
    ShotUsageSummaryOut,
    UsageCreateRequest,
    UsageOut,
    UsageUpdateRequest,
    UsageWithOccurrencesOut,
)
from app.schemas.shot import to_shot_out

# ============================ 守卫 / 基础 ============================


async def get_final_video_or_404(db: AsyncSession, final_video_id: int) -> FinalVideo:
    fv = await db.get(FinalVideo, final_video_id)
    if fv is None:
        raise HTTPException(status_code=404, detail="最终成片不存在")
    return fv


def ensure_final_video_mutable(fv: FinalVideo) -> None:
    """归档成片除恢复外禁止任何写操作（含确认新 Usage）。"""
    if fv.status == FinalVideoStatus.ARCHIVED:
        raise HTTPException(
            status_code=409, detail="成片已归档，禁止修改（仅可恢复后再操作）"
        )


async def get_usage_or_404(db: AsyncSession, usage_id: int) -> FinalVideoUsage:
    usage = await db.get(FinalVideoUsage, usage_id)
    if usage is None:
        raise HTTPException(status_code=404, detail="使用引用不存在")
    return usage


async def _get_usage_locked(db: AsyncSession, usage_id: int) -> FinalVideoUsage:
    """行锁读取（状态转换统一入口，消除并发读后写竞态）。"""
    usage = (
        await db.execute(
            select(FinalVideoUsage)
            .where(FinalVideoUsage.id == usage_id)
            .with_for_update()
        )
    ).scalar_one_or_none()
    if usage is None:
        raise HTTPException(status_code=404, detail="使用引用不存在")
    return usage


def _ensure_shot_usable(shot: Shot, asset: Asset) -> None:
    """Source Shot 必须可用：当前代次 READY 镜头 + 源素材未缺失。

    PR-C：retired（历史代次）镜头不允许**新增**引用；既有历史引用继续保留可查。
    """
    if shot.status != ShotStatus.READY:
        raise HTTPException(status_code=409, detail="来源镜头不可用（非 ready 状态）")
    if shot.retired_at is not None:
        raise HTTPException(
            status_code=409, detail="来源镜头属于历史分析代次，请使用当前代次镜头"
        )
    if asset.status == AssetStatus.SOURCE_MISSING:
        raise HTTPException(status_code=409, detail="来源素材源文件缺失，不能建立引用")


def _add_event(
    db: AsyncSession,
    usage_id: int,
    action: str,
    *,
    before_status: str | None,
    after_status: str | None,
    actor_label: str | None = None,
    note: str | None = None,
) -> None:
    """append-only 审计事件；与业务变更同事务（调用方负责 commit）。"""
    db.add(
        FinalVideoUsageEvent(
            usage_id=usage_id,
            action=action,
            before_status=before_status,
            after_status=after_status,
            actor_label=actor_label,
            note=note,
        )
    )


# ============================ 装配 helpers ============================


async def _usage_stats_map(
    db: AsyncSession, final_video_ids: list[int]
) -> dict[int, FinalVideoUsageStatsOut]:
    """批量统计各成片的血缘状态分布（派生值）。"""
    stats: dict[int, FinalVideoUsageStatsOut] = {
        fid: FinalVideoUsageStatsOut() for fid in final_video_ids
    }
    if not final_video_ids:
        return stats
    rows = (
        await db.execute(
            select(
                FinalVideoUsage.final_video_id,
                FinalVideoUsage.status,
                func.count(FinalVideoUsage.id),
            )
            .where(FinalVideoUsage.final_video_id.in_(final_video_ids))
            .group_by(FinalVideoUsage.final_video_id, FinalVideoUsage.status)
        )
    ).all()
    field_by_status = {
        FinalVideoUsageStatus.CONFIRMED: "confirmed_count",
        FinalVideoUsageStatus.PROPOSED: "proposed_count",
        FinalVideoUsageStatus.SUSPECTED: "suspected_count",
        FinalVideoUsageStatus.REJECTED: "rejected_count",
        FinalVideoUsageStatus.REVOKED: "revoked_count",
    }
    for fid, status_, cnt in rows:
        s = stats[fid]
        s.source_shot_count += cnt
        setattr(s, field_by_status[status_], cnt)
    return stats


async def _to_final_video_outs(
    db: AsyncSession, videos: list[FinalVideo]
) -> list[FinalVideoOut]:
    """批量装配便利字段（asset/project/script 名称 + 血缘统计），固定查询数。"""
    if not videos:
        return []
    asset_ids = {v.asset_id for v in videos}
    project_ids = {v.project_id for v in videos if v.project_id is not None}
    script_ids = {v.script_project_id for v in videos if v.script_project_id is not None}

    assets = {
        a.id: a
        for a in (
            await db.scalars(select(Asset).where(Asset.id.in_(asset_ids)))
        ).all()
    }
    projects: dict[int, str] = {}
    if project_ids:
        projects = {
            p.id: p.name
            for p in (
                await db.scalars(select(Project).where(Project.id.in_(project_ids)))
            ).all()
        }
    scripts: dict[int, str] = {}
    if script_ids:
        scripts = {
            s.id: s.name
            for s in (
                await db.scalars(
                    select(ScriptProject).where(ScriptProject.id.in_(script_ids))
                )
            ).all()
        }
    stats = await _usage_stats_map(db, [v.id for v in videos])

    outs: list[FinalVideoOut] = []
    for v in videos:
        out = FinalVideoOut.model_validate(v)
        asset = assets.get(v.asset_id)
        if asset is not None:
            out.asset_filename = asset.filename
            out.asset_duration = asset.duration
            out.asset_has_poster = bool(asset.poster_path)
        if v.project_id is not None:
            out.project_name = projects.get(v.project_id)
        if v.script_project_id is not None:
            out.script_project_name = scripts.get(v.script_project_id)
        out.usage_stats = stats[v.id]
        outs.append(out)
    return outs


async def _product_name_map(db: AsyncSession, shots: list[Shot]) -> dict[int, str]:
    """shot_id → 展示产品名：人工确认产品优先，回退素材主产品。"""
    result: dict[int, str] = {}
    if not shots:
        return result
    shot_ids = [s.id for s in shots]
    review_rows = (
        await db.execute(
            select(ShotReviewState.shot_id, Product.name)
            .join(Shot, Shot.id == ShotReviewState.shot_id)
            .join(Product, Product.id == ShotReviewState.confirmed_product_id)
            .where(
                ShotReviewState.shot_id.in_(shot_ids),
                ShotReviewState.shot_generation == Shot.generation,
                ShotReviewState.confirmed_product_id.is_not(None),
            )
        )
    ).all()
    for sid, name in review_rows:
        result[sid] = name
    # 回退：素材主产品
    remaining = [s for s in shots if s.id not in result]
    if remaining:
        asset_ids = {s.asset_id for s in remaining}
        asset_rows = (
            await db.execute(
                select(Asset.id, Product.name)
                .join(Product, Product.id == Asset.primary_product_id)
                .where(Asset.id.in_(asset_ids), Asset.primary_product_id.is_not(None))
            )
        ).all()
        by_asset = {aid: name for aid, name in asset_rows}
        for s in remaining:
            if s.asset_id in by_asset:
                result[s.id] = by_asset[s.asset_id]
    return result


async def _to_usage_outs(
    db: AsyncSession, usages: list[FinalVideoUsage], *, with_occurrences: bool = False
) -> list[UsageOut] | list[UsageWithOccurrencesOut]:
    """批量装配 Usage 展示字段（shot 摘要 / occurrence 数 / 产品名），固定查询数。"""
    if not usages:
        return []
    shot_ids = {u.source_shot_id for u in usages}
    shots = {
        s.id: s
        for s in (await db.scalars(select(Shot).where(Shot.id.in_(shot_ids)))).all()
    }
    asset_ids = {s.asset_id for s in shots.values()} | {u.source_asset_id for u in usages}
    assets = {
        a.id: a
        for a in (await db.scalars(select(Asset).where(Asset.id.in_(asset_ids)))).all()
    }
    usage_ids = [u.id for u in usages]
    occ_counts: dict[int, int] = defaultdict(int)
    occ_map: dict[int, list[FinalVideoUsageOccurrence]] = defaultdict(list)
    if with_occurrences:
        occs = (
            await db.scalars(
                select(FinalVideoUsageOccurrence)
                .where(FinalVideoUsageOccurrence.usage_id.in_(usage_ids))
                .order_by(
                    FinalVideoUsageOccurrence.usage_id,
                    FinalVideoUsageOccurrence.occurrence_index,
                )
            )
        ).all()
        for o in occs:
            occ_map[o.usage_id].append(o)
            occ_counts[o.usage_id] += 1
    else:
        rows = (
            await db.execute(
                select(
                    FinalVideoUsageOccurrence.usage_id,
                    func.count(FinalVideoUsageOccurrence.id),
                )
                .where(FinalVideoUsageOccurrence.usage_id.in_(usage_ids))
                .group_by(FinalVideoUsageOccurrence.usage_id)
            )
        ).all()
        for uid, cnt in rows:
            occ_counts[uid] = cnt
    product_names = await _product_name_map(db, list(shots.values()))

    outs: list[UsageOut] = []
    cls = UsageWithOccurrencesOut if with_occurrences else UsageOut
    for u in usages:
        out = cls.model_validate(u)
        shot = shots.get(u.source_shot_id)
        src_asset = assets.get(u.source_asset_id)
        if shot is not None:
            shot_asset = assets.get(shot.asset_id)
            out.shot = to_shot_out(
                shot, shot_asset.filename if shot_asset is not None else None
            )
            out.product_name = product_names.get(shot.id)
        if src_asset is not None:
            out.source_asset_filename = src_asset.filename
        out.occurrence_count = occ_counts.get(u.id, 0)
        if with_occurrences:
            out.occurrences = [
                OccurrenceOut.model_validate(o) for o in occ_map.get(u.id, [])
            ]
        outs.append(out)
    return outs


# ============================ FinalVideo CRUD ============================


async def create_final_video(
    db: AsyncSession, req: FinalVideoCreateRequest
) -> FinalVideo:
    asset = await db.get(Asset, req.asset_id)
    if asset is None:
        raise HTTPException(status_code=404, detail="成片素材（Asset）不存在")
    if asset.status == AssetStatus.SOURCE_MISSING:
        raise HTTPException(status_code=409, detail="成片素材源文件缺失，不能创建成片")
    if req.project_id is not None and await db.get(Project, req.project_id) is None:
        raise HTTPException(status_code=404, detail="绑定的项目不存在")
    if (
        req.script_project_id is not None
        and await db.get(ScriptProject, req.script_project_id) is None
    ):
        raise HTTPException(status_code=404, detail="绑定的脚本不存在")

    fv = FinalVideo(
        asset_id=req.asset_id,
        project_id=req.project_id,
        script_project_id=req.script_project_id,
        title=req.title,
        description=req.description,
        version_label=req.version_label,
        status=req.status,
        completed_at=req.completed_at,
    )
    db.add(fv)
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(
            status_code=409, detail="该素材已存在未归档的成片记录（同一素材至多一个活动成片）"
        ) from None
    await db.refresh(fv)
    return fv


async def list_final_videos(
    db: AsyncSession,
    *,
    page: int,
    page_size: int,
    status: FinalVideoStatus | None,
    project_id: int | None,
    q: str | None,
    include_archived: bool,
) -> tuple[list[FinalVideo], int]:
    base = select(FinalVideo)
    count_base = select(func.count(FinalVideo.id))
    conds = []
    if status is not None:
        conds.append(FinalVideo.status == status)
    elif not include_archived:
        conds.append(FinalVideo.status != FinalVideoStatus.ARCHIVED)
    if project_id is not None:
        conds.append(FinalVideo.project_id == project_id)
    if q:
        like = f"%{q.strip()}%"
        conds.append(FinalVideo.title.ilike(like))
    for c in conds:
        base = base.where(c)
        count_base = count_base.where(c)
    total = int(await db.scalar(count_base) or 0)
    rows = (
        await db.scalars(
            base.order_by(FinalVideo.created_at.desc(), FinalVideo.id.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
    ).all()
    return list(rows), total


async def update_final_video(
    db: AsyncSession, final_video_id: int, req: FinalVideoUpdateRequest
) -> FinalVideo:
    fv = await get_final_video_or_404(db, final_video_id)
    ensure_final_video_mutable(fv)
    data = req.model_dump(exclude_unset=True)
    if "project_id" in data and data["project_id"] is not None:
        if await db.get(Project, data["project_id"]) is None:
            raise HTTPException(status_code=404, detail="绑定的项目不存在")
    if "script_project_id" in data and data["script_project_id"] is not None:
        if await db.get(ScriptProject, data["script_project_id"]) is None:
            raise HTTPException(status_code=404, detail="绑定的脚本不存在")
    for field, value in data.items():
        setattr(fv, field, value)
    await db.commit()
    await db.refresh(fv)
    return fv


async def archive_final_video(db: AsyncSession, final_video_id: int) -> FinalVideo:
    """归档（代替删除）：保留全部血缘；历史 confirmed usage 继续计数。"""
    fv = await get_final_video_or_404(db, final_video_id)
    if fv.status == FinalVideoStatus.ARCHIVED:
        raise HTTPException(status_code=409, detail="成片已归档")
    fv.status = FinalVideoStatus.ARCHIVED
    fv.archived_at = utcnow()
    await db.commit()
    await db.refresh(fv)
    return fv


async def restore_final_video(db: AsyncSession, final_video_id: int) -> FinalVideo:
    fv = await get_final_video_or_404(db, final_video_id)
    if fv.status != FinalVideoStatus.ARCHIVED:
        raise HTTPException(status_code=409, detail="成片未归档，无需恢复")
    fv.status = (
        FinalVideoStatus.COMPLETED if fv.completed_at else FinalVideoStatus.DRAFT
    )
    fv.archived_at = None
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(
            status_code=409, detail="该素材已存在另一个未归档成片，无法恢复"
        ) from None
    await db.refresh(fv)
    return fv


# ============================ Usage 创建 / 工作流 ============================


async def create_manual_usage(
    db: AsyncSession, final_video_id: int, req: UsageCreateRequest
) -> FinalVideoUsage:
    fv = await get_final_video_or_404(db, final_video_id)
    ensure_final_video_mutable(fv)
    shot = await db.get(Shot, req.source_shot_id)
    if shot is None:
        raise HTTPException(status_code=404, detail="来源镜头不存在")
    asset = await db.get(Asset, shot.asset_id)
    if asset is None:
        raise HTTPException(status_code=404, detail="来源素材不存在")
    _ensure_shot_usable(shot, asset)
    if shot.asset_id == fv.asset_id:
        raise HTTPException(
            status_code=409, detail="来源镜头与成片是同一个媒体文件，禁止自引用"
        )

    usage = FinalVideoUsage(
        final_video_id=fv.id,
        source_shot_id=shot.id,
        source_asset_id=shot.asset_id,
        source_shot_generation=shot.generation,
        status=FinalVideoUsageStatus.PROPOSED,
        evidence_method=req.evidence_method,
        confidence=req.confidence,
        evidence_summary=req.evidence_summary,
        actor_label=req.actor_label,
        review_note=req.review_note,
    )
    db.add(usage)
    try:
        await db.flush()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(
            status_code=409, detail="该成片与该镜头已存在引用关系（一对关系仅一条）"
        ) from None
    _add_event(
        db,
        usage.id,
        "manual_add",
        before_status=None,
        after_status=FinalVideoUsageStatus.PROPOSED.value,
        actor_label=req.actor_label,
        note=req.review_note,
    )
    await db.commit()
    await db.refresh(usage)
    return usage


async def update_usage(
    db: AsyncSession, usage_id: int, req: UsageUpdateRequest
) -> FinalVideoUsage:
    """PATCH 元信息（不改状态、不写事件；状态变更走专用动作接口）。"""
    usage = await get_usage_or_404(db, usage_id)
    fv = await get_final_video_or_404(db, usage.final_video_id)
    ensure_final_video_mutable(fv)
    data = req.model_dump(exclude_unset=True)
    if usage.status != FinalVideoUsageStatus.PROPOSED and "confidence" in data:
        raise HTTPException(
            status_code=409, detail="仅 proposed 状态允许修改 confidence"
        )
    for field, value in data.items():
        setattr(usage, field, value)
    await db.commit()
    await db.refresh(usage)
    return usage


async def confirm_usage(
    db: AsyncSession, usage_id: int, *, actor_label: str | None, note: str | None
) -> FinalVideoUsage:
    usage = await _get_usage_locked(db, usage_id)
    fv = await get_final_video_or_404(db, usage.final_video_id)
    ensure_final_video_mutable(fv)  # archived 成片不允许确认新 Usage
    if usage.status == FinalVideoUsageStatus.CONFIRMED:
        raise HTTPException(status_code=409, detail="该引用已是 confirmed")
    if usage.status in (
        FinalVideoUsageStatus.REJECTED,
        FinalVideoUsageStatus.REVOKED,
    ):
        raise HTTPException(
            status_code=409, detail="已驳回/已撤销的引用须先恢复为 proposed 再确认"
        )
    if usage.evidence_method not in CONFIRMABLE_EVIDENCE_METHODS:
        raise HTTPException(
            status_code=409,
            detail=f"证据来源 {usage.evidence_method} 本阶段不允许确认",
        )
    shot = await db.get(Shot, usage.source_shot_id)
    asset = await db.get(Asset, usage.source_asset_id)
    if shot is None or asset is None:
        raise HTTPException(status_code=409, detail="来源镜头/素材已不可用")
    _ensure_shot_usable(shot, asset)

    before = usage.status.value
    usage.status = FinalVideoUsageStatus.CONFIRMED
    usage.confirmed_at = utcnow()
    if actor_label:
        usage.actor_label = actor_label
    if note:
        usage.review_note = note
    _add_event(
        db,
        usage.id,
        "confirm",
        before_status=before,
        after_status=usage.status.value,
        actor_label=actor_label,
        note=note,
    )
    await db.commit()
    await db.refresh(usage)
    return usage


async def reject_usage(
    db: AsyncSession, usage_id: int, *, actor_label: str | None, note: str | None
) -> FinalVideoUsage:
    usage = await _get_usage_locked(db, usage_id)
    fv = await get_final_video_or_404(db, usage.final_video_id)
    ensure_final_video_mutable(fv)
    if usage.status not in (
        FinalVideoUsageStatus.PROPOSED,
        FinalVideoUsageStatus.SUSPECTED,
    ):
        raise HTTPException(
            status_code=409,
            detail="仅 proposed/suspected 可驳回（已确认的引用请用撤销）",
        )
    before = usage.status.value
    usage.status = FinalVideoUsageStatus.REJECTED
    usage.rejected_at = utcnow()
    if actor_label:
        usage.actor_label = actor_label
    if note:
        usage.review_note = note
    _add_event(
        db,
        usage.id,
        "reject",
        before_status=before,
        after_status=usage.status.value,
        actor_label=actor_label,
        note=note,
    )
    await db.commit()
    await db.refresh(usage)
    return usage


async def revoke_usage(
    db: AsyncSession, usage_id: int, *, actor_label: str | None, note: str | None
) -> FinalVideoUsage:
    """撤销已确认引用（使用次数立即减少；归档成片也允许撤销——减少计数是合法治理动作）。"""
    usage = await _get_usage_locked(db, usage_id)
    if usage.status != FinalVideoUsageStatus.CONFIRMED:
        raise HTTPException(status_code=409, detail="仅 confirmed 可撤销")
    before = usage.status.value
    usage.status = FinalVideoUsageStatus.REVOKED
    usage.revoked_at = utcnow()
    if actor_label:
        usage.actor_label = actor_label
    if note:
        usage.review_note = note
    _add_event(
        db,
        usage.id,
        "revoke",
        before_status=before,
        after_status=usage.status.value,
        actor_label=actor_label,
        note=note,
    )
    await db.commit()
    await db.refresh(usage)
    return usage


async def restore_usage_proposal(
    db: AsyncSession, usage_id: int, *, actor_label: str | None, note: str | None
) -> FinalVideoUsage:
    usage = await _get_usage_locked(db, usage_id)
    fv = await get_final_video_or_404(db, usage.final_video_id)
    ensure_final_video_mutable(fv)
    if usage.status not in (
        FinalVideoUsageStatus.REJECTED,
        FinalVideoUsageStatus.REVOKED,
    ):
        raise HTTPException(status_code=409, detail="仅 rejected/revoked 可恢复为 proposed")
    before = usage.status.value
    usage.status = FinalVideoUsageStatus.PROPOSED
    usage.confirmed_at = None
    usage.rejected_at = None
    usage.revoked_at = None
    if actor_label:
        usage.actor_label = actor_label
    if note:
        usage.review_note = note
    _add_event(
        db,
        usage.id,
        "restore_proposal",
        before_status=before,
        after_status=usage.status.value,
        actor_label=actor_label,
        note=note,
    )
    await db.commit()
    await db.refresh(usage)
    return usage


async def list_usages(
    db: AsyncSession,
    final_video_id: int,
    *,
    status: FinalVideoUsageStatus | None,
) -> tuple[list[FinalVideoUsage], int]:
    await get_final_video_or_404(db, final_video_id)
    base = select(FinalVideoUsage).where(
        FinalVideoUsage.final_video_id == final_video_id
    )
    if status is not None:
        base = base.where(FinalVideoUsage.status == status)
    rows = (
        await db.scalars(base.order_by(FinalVideoUsage.id.asc()))
    ).all()
    return list(rows), len(rows)


# ============================ Occurrence ============================


def _validate_occurrence_times(
    *,
    source_start_ms: int,
    source_end_ms: int,
    final_start_ms: int,
    final_end_ms: int,
    shot: Shot,
    final_asset: Asset | None,
) -> None:
    if source_end_ms <= source_start_ms:
        raise HTTPException(status_code=422, detail="source_end_ms 必须大于 source_start_ms")
    if final_end_ms <= final_start_ms:
        raise HTTPException(status_code=422, detail="final_end_ms 必须大于 final_start_ms")
    # source 时间段必须落在 Source Shot 区间内（毫秒边界取整容差）
    shot_start_ms = math.floor(shot.start_time * 1000)
    shot_end_ms = math.ceil(shot.end_time * 1000)
    if source_start_ms < shot_start_ms or source_end_ms > shot_end_ms:
        raise HTTPException(
            status_code=422,
            detail=(
                f"source 时间段须在来源镜头范围内（{shot_start_ms}–{shot_end_ms} ms）"
            ),
        )
    # final 时间段不能越过成片时长（成片素材 duration 未知时跳过上界校验）
    if final_asset is not None and final_asset.duration is not None:
        final_max_ms = math.ceil(final_asset.duration * 1000)
        if final_end_ms > final_max_ms:
            raise HTTPException(
                status_code=422,
                detail=f"final 时间段超出成片时长（最大 {final_max_ms} ms）",
            )


async def list_occurrences(
    db: AsyncSession, usage_id: int
) -> list[FinalVideoUsageOccurrence]:
    await get_usage_or_404(db, usage_id)
    rows = (
        await db.scalars(
            select(FinalVideoUsageOccurrence)
            .where(FinalVideoUsageOccurrence.usage_id == usage_id)
            .order_by(FinalVideoUsageOccurrence.occurrence_index)
        )
    ).all()
    return list(rows)


async def create_occurrence(
    db: AsyncSession, usage_id: int, req: OccurrenceCreateRequest
) -> FinalVideoUsageOccurrence:
    usage = await _get_usage_locked(db, usage_id)  # 锁 usage 串行化 index 分配
    fv = await get_final_video_or_404(db, usage.final_video_id)
    ensure_final_video_mutable(fv)
    shot = await db.get(Shot, usage.source_shot_id)
    if shot is None:
        raise HTTPException(status_code=409, detail="来源镜头已不可用")
    final_asset = await db.get(Asset, fv.asset_id)
    _validate_occurrence_times(
        source_start_ms=req.source_start_ms,
        source_end_ms=req.source_end_ms,
        final_start_ms=req.final_start_ms,
        final_end_ms=req.final_end_ms,
        shot=shot,
        final_asset=final_asset,
    )
    next_index = (
        await db.scalar(
            select(
                func.coalesce(func.max(FinalVideoUsageOccurrence.occurrence_index), -1)
            ).where(FinalVideoUsageOccurrence.usage_id == usage_id)
        )
    ) + 1
    occ = FinalVideoUsageOccurrence(
        usage_id=usage_id,
        occurrence_index=next_index,
        source_start_ms=req.source_start_ms,
        source_end_ms=req.source_end_ms,
        final_start_ms=req.final_start_ms,
        final_end_ms=req.final_end_ms,
    )
    db.add(occ)
    await db.flush()
    _add_event(
        db,
        usage_id,
        "occurrence_add",
        before_status=usage.status.value,
        after_status=usage.status.value,
        note=f"occurrence #{next_index}",
    )
    await db.commit()
    await db.refresh(occ)
    return occ


async def get_occurrence_or_404(
    db: AsyncSession, occurrence_id: int
) -> FinalVideoUsageOccurrence:
    occ = await db.get(FinalVideoUsageOccurrence, occurrence_id)
    if occ is None:
        raise HTTPException(status_code=404, detail="出现时间段不存在")
    return occ


async def update_occurrence(
    db: AsyncSession, occurrence_id: int, req: OccurrenceUpdateRequest
) -> FinalVideoUsageOccurrence:
    occ = await get_occurrence_or_404(db, occurrence_id)
    usage = await get_usage_or_404(db, occ.usage_id)
    fv = await get_final_video_or_404(db, usage.final_video_id)
    ensure_final_video_mutable(fv)
    shot = await db.get(Shot, usage.source_shot_id)
    if shot is None:
        raise HTTPException(status_code=409, detail="来源镜头已不可用")
    final_asset = await db.get(Asset, fv.asset_id)
    data = req.model_dump(exclude_unset=True)
    merged = {
        "source_start_ms": data.get("source_start_ms", occ.source_start_ms),
        "source_end_ms": data.get("source_end_ms", occ.source_end_ms),
        "final_start_ms": data.get("final_start_ms", occ.final_start_ms),
        "final_end_ms": data.get("final_end_ms", occ.final_end_ms),
    }
    _validate_occurrence_times(**merged, shot=shot, final_asset=final_asset)
    for field, value in merged.items():
        setattr(occ, field, value)
    _add_event(
        db,
        usage.id,
        "occurrence_update",
        before_status=usage.status.value,
        after_status=usage.status.value,
        note=f"occurrence #{occ.occurrence_index}",
    )
    await db.commit()
    await db.refresh(occ)
    return occ


async def delete_occurrence(db: AsyncSession, occurrence_id: int) -> None:
    occ = await get_occurrence_or_404(db, occurrence_id)
    usage = await get_usage_or_404(db, occ.usage_id)
    fv = await get_final_video_or_404(db, usage.final_video_id)
    ensure_final_video_mutable(fv)
    _add_event(
        db,
        usage.id,
        "occurrence_delete",
        before_status=usage.status.value,
        after_status=usage.status.value,
        note=f"occurrence #{occ.occurrence_index}",
    )
    await db.delete(occ)
    await db.commit()


# ============================ 从项目生成候选 ============================


async def propose_from_project(
    db: AsyncSession, final_video_id: int, *, actor_label: str | None
) -> ProposeFromProjectOut:
    """从绑定 Project/Script 的**已选择/已锁定**镜头生成 proposed 候选（幂等）。

    只使用 script_segment.locked_shot_id / selected_shot_id（明确人工动作）；
    project_shot 成员、搜索结果、导出历史一律不生成（不扩大推断）。
    绝不覆盖已存在关系（任何状态）；绝不修改 Project/Script 的选择与锁定。
    """
    fv = await get_final_video_or_404(db, final_video_id)
    ensure_final_video_mutable(fv)

    script_ids: set[int] = set()
    if fv.script_project_id is not None:
        script_ids.add(fv.script_project_id)
    if fv.project_id is not None:
        rows = (
            await db.scalars(
                select(ScriptProject.id).where(ScriptProject.project_id == fv.project_id)
            )
        ).all()
        script_ids.update(rows)
    if not script_ids:
        raise HTTPException(
            status_code=409,
            detail="成片未绑定项目或脚本，或绑定项目下没有脚本，无法生成候选",
        )

    segments = (
        await db.scalars(
            select(ScriptSegment).where(ScriptSegment.script_project_id.in_(script_ids))
        )
    ).all()
    # shot_id → 结构化来源引用（locked 优先记录，同镜头多段合并）
    shot_refs: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for seg in segments:
        if seg.locked_shot_id is not None:
            shot_refs[seg.locked_shot_id].append(
                {
                    "script_project_id": seg.script_project_id,
                    "segment_id": seg.id,
                    "kind": "locked",
                }
            )
        if seg.selected_shot_id is not None and seg.selected_shot_id != seg.locked_shot_id:
            shot_refs[seg.selected_shot_id].append(
                {
                    "script_project_id": seg.script_project_id,
                    "segment_id": seg.id,
                    "kind": "selected",
                }
            )

    out = ProposeFromProjectOut(segments_scanned=len(segments))
    if not shot_refs:
        return out

    existing_ids = set(
        (
            await db.scalars(
                select(FinalVideoUsage.source_shot_id).where(
                    FinalVideoUsage.final_video_id == fv.id,
                    FinalVideoUsage.source_shot_id.in_(shot_refs.keys()),
                )
            )
        ).all()
    )
    shots = {
        s.id: s
        for s in (
            await db.scalars(select(Shot).where(Shot.id.in_(shot_refs.keys())))
        ).all()
    }
    asset_ids = {s.asset_id for s in shots.values()}
    assets = {
        a.id: a
        for a in (await db.scalars(select(Asset).where(Asset.id.in_(asset_ids)))).all()
    }

    for shot_id, refs in sorted(shot_refs.items()):
        if shot_id in existing_ids:
            out.existing += 1
            continue
        shot = shots.get(shot_id)
        if shot is None:
            out.skipped_unavailable += 1
            continue
        asset = assets.get(shot.asset_id)
        if (
            asset is None
            or shot.status != ShotStatus.READY
            or shot.retired_at is not None
            or asset.status == AssetStatus.SOURCE_MISSING
        ):
            out.skipped_unavailable += 1
            continue
        if shot.asset_id == fv.asset_id:
            out.conflicts += 1
            continue
        kinds = {r["kind"] for r in refs}
        if kinds == {"locked"}:
            kind_label = "锁定镜头"
        elif kinds == {"selected"}:
            kind_label = "选择镜头"
        else:
            kind_label = "锁定/选择镜头"
        summary = f"来自项目脚本段落的{kind_label}"
        usage = FinalVideoUsage(
            final_video_id=fv.id,
            source_shot_id=shot_id,
            source_asset_id=shot.asset_id,
            source_shot_generation=shot.generation,
            status=FinalVideoUsageStatus.PROPOSED,
            evidence_method="clipmind_project",
            evidence_summary=summary,
            evidence_refs={"segments": refs},
            actor_label=actor_label,
        )
        db.add(usage)
        try:
            async with db.begin_nested():
                await db.flush()
        except IntegrityError:
            # 并发下已被其他请求创建：视作已存在
            out.existing += 1
            continue
        _add_event(
            db,
            usage.id,
            "create_proposal",
            before_status=None,
            after_status=FinalVideoUsageStatus.PROPOSED.value,
            actor_label=actor_label,
            note=summary,
        )
        out.created += 1
        out.created_usage_ids.append(usage.id)

    await db.commit()
    return out


# ============================ 统计 / 血缘 / 事件 ============================


async def get_final_video_lineage(
    db: AsyncSession, final_video_id: int
) -> FinalVideoLineageOut:
    fv = await get_final_video_or_404(db, final_video_id)
    usages, _ = await list_usages(db, final_video_id, status=None)
    fv_out = (await _to_final_video_outs(db, [fv]))[0]
    usage_outs = await _to_usage_outs(db, usages, with_occurrences=True)
    return FinalVideoLineageOut(final_video=fv_out, usages=usage_outs)


async def list_usage_events(
    db: AsyncSession, usage_id: int
) -> list[FinalVideoUsageEvent]:
    await get_usage_or_404(db, usage_id)
    rows = (
        await db.scalars(
            select(FinalVideoUsageEvent)
            .where(FinalVideoUsageEvent.usage_id == usage_id)
            .order_by(FinalVideoUsageEvent.id.asc())
        )
    ).all()
    return list(rows)


async def get_shot_usage_summary(db: AsyncSession, shot_id: int) -> ShotUsageSummaryOut:
    shot = await db.get(Shot, shot_id)
    if shot is None:
        raise HTTPException(status_code=404, detail="镜头不存在")
    rows = (
        await db.execute(
            select(FinalVideoUsage, FinalVideo)
            .join(FinalVideo, FinalVideo.id == FinalVideoUsage.final_video_id)
            .where(FinalVideoUsage.source_shot_id == shot_id)
            .order_by(FinalVideoUsage.confirmed_at.desc().nulls_last())
        )
    ).all()
    out = ShotUsageSummaryOut(shot_id=shot_id)
    for usage, fv in rows:
        if usage.status == FinalVideoUsageStatus.CONFIRMED:
            out.confirmed_usage_count += 1
            out.final_videos.append(
                FinalVideoBriefOut(
                    final_video_id=fv.id,
                    title=fv.title,
                    status=fv.status,
                    confirmed_at=usage.confirmed_at,
                )
            )
            if usage.confirmed_at is not None and (
                out.last_used_at is None or usage.confirmed_at > out.last_used_at
            ):
                out.last_used_at = usage.confirmed_at
        elif usage.status == FinalVideoUsageStatus.PROPOSED:
            out.proposed_count += 1
        elif usage.status == FinalVideoUsageStatus.SUSPECTED:
            out.suspected_count += 1
    return out


async def get_shot_usage_counts(
    db: AsyncSession, shot_ids: list[int]
) -> list[ShotUsageCountOut]:
    """批量轻量计数（镜头卡片徽标；一次分组聚合，避免 N+1）。"""
    result: dict[int, ShotUsageCountOut] = {
        sid: ShotUsageCountOut(shot_id=sid) for sid in shot_ids
    }
    if not shot_ids:
        return []
    rows = (
        await db.execute(
            select(
                FinalVideoUsage.source_shot_id,
                FinalVideoUsage.status,
                func.count(FinalVideoUsage.id),
            )
            .where(
                FinalVideoUsage.source_shot_id.in_(shot_ids),
                FinalVideoUsage.status.in_(
                    [FinalVideoUsageStatus.CONFIRMED, FinalVideoUsageStatus.PROPOSED]
                ),
            )
            .group_by(FinalVideoUsage.source_shot_id, FinalVideoUsage.status)
        )
    ).all()
    for sid, status_, cnt in rows:
        if status_ == FinalVideoUsageStatus.CONFIRMED:
            result[sid].confirmed_usage_count = cnt
        else:
            result[sid].proposed_count = cnt
    return [result[sid] for sid in shot_ids]


async def get_asset_usage_summary(
    db: AsyncSession, asset_id: int
) -> AssetUsageSummaryOut:
    asset = await db.get(Asset, asset_id)
    if asset is None:
        raise HTTPException(status_code=404, detail="素材不存在")
    total_shots = int(
        await db.scalar(
            select(func.count(Shot.id)).where(
                Shot.asset_id == asset_id,
                Shot.status == ShotStatus.READY,
                Shot.retired_at.is_(None),
            )
        )
        or 0
    )
    per_shot = (
        await db.execute(
            select(
                FinalVideoUsage.source_shot_id,
                func.count(FinalVideoUsage.id),
            )
            .where(
                FinalVideoUsage.source_asset_id == asset_id,
                FinalVideoUsage.status == FinalVideoUsageStatus.CONFIRMED,
            )
            .group_by(FinalVideoUsage.source_shot_id)
        )
    ).all()
    distinct_fv = int(
        await db.scalar(
            select(func.count(func.distinct(FinalVideoUsage.final_video_id))).where(
                FinalVideoUsage.source_asset_id == asset_id,
                FinalVideoUsage.status == FinalVideoUsageStatus.CONFIRMED,
            )
        )
        or 0
    )
    last_used_at: datetime | None = await db.scalar(
        select(func.max(FinalVideoUsage.confirmed_at)).where(
            FinalVideoUsage.source_asset_id == asset_id,
            FinalVideoUsage.status == FinalVideoUsageStatus.CONFIRMED,
        )
    )
    used_shot_count = len(per_shot)
    distribution: dict[str, int] = defaultdict(int)
    distribution["0"] = max(total_shots - used_shot_count, 0)
    for _sid, cnt in per_shot:
        distribution[str(cnt)] += 1
    confirmed_total = int(sum(cnt for _sid, cnt in per_shot))
    # PR-C Gate B：历史弱证据只做并列展示——绝不并入上面的 confirmed 统计
    from app.services import legacy_evidence_service

    legacy_counts = await legacy_evidence_service.legacy_counts_for_asset(db, asset_id)
    return AssetUsageSummaryOut(
        asset_id=asset_id,
        total_shots=total_shots,
        used_shot_count=used_shot_count,
        never_used_shot_count=max(total_shots - used_shot_count, 0),
        distinct_final_video_count=distinct_fv,
        usage_distribution=dict(distribution),
        last_used_at=last_used_at,
        confirmed_usage_count=confirmed_total,
        accepted_legacy_evidence_count=legacy_counts.get("accepted", 0),
        pending_legacy_evidence_count=legacy_counts.get("pending", 0),
        rejected_legacy_evidence_count=legacy_counts.get("rejected", 0),
        conflict_legacy_evidence_count=legacy_counts.get("conflict", 0),
        legacy_usage_state=legacy_evidence_service.derive_legacy_state(legacy_counts),
        usage_count_known=confirmed_total > 0,
        final_video_known=distinct_fv > 0,
    )


async def count_usage_refs_for_asset(db: AsyncSession, asset_id: int) -> int:
    """素材下镜头被血缘引用的条数（镜头重新分析守卫用）。"""
    return int(
        await db.scalar(
            select(func.count(FinalVideoUsage.id)).where(
                FinalVideoUsage.source_asset_id == asset_id
            )
        )
        or 0
    )
