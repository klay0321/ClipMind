"""PR-D 统一使用记录中心（Read Model + typed bulk；docs/USAGE_REVIEW_CENTER.md）。

铁律：
- 展示统一、事实分离——本服务**只读**投影两张事实表，绝不复制 usage 数据、
  绝不直写底层状态字段、绝不绕过原领域 Service 与事件审计；
- confirmed 使用次数只能被 formal confirm/revoke 改变；legacy 动作零影响；
- 两类计数并列，绝不相加为"总使用次数"；
- legacy 证据没有 Shot、没有成片（对应字段恒 null，不造占位对象）。
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from clipmind_shared.models import (
    Asset,
    FinalVideo,
    FinalVideoUsage,
    FinalVideoUsageEvent,
    LegacyUsageEvidence,
    LegacyUsageEvidenceEvent,
    LegacyUsageRule,
    Product,
    ProductFamily,
    ProductVariant,
    Shot,
)
from clipmind_shared.models.enums import FinalVideoUsageStatus
from fastapi import HTTPException
from sqlalchemy import Select, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.schemas.legacy_evidence import EvidenceOut
from app.schemas.usage_review import (
    FORMAL_BULK_ACTIONS,
    LEGACY_BULK_ACTIONS,
    BulkItemResult,
    BulkReviewOut,
    BulkReviewRequest,
    FormalSummaryOut,
    LegacySummaryOut,
    ReviewItemDetailOut,
    ReviewItemOut,
    ReviewListResponse,
    ReviewSummaryOut,
)
from app.services import final_video_service, legacy_evidence_service

# ============================ 映射（冻结） ============================

# formal status -> (review_group, 默认 source_strength)
_FORMAL_GROUP = {
    "proposed": "needs_review",
    "suspected": "needs_review",
    "confirmed": "accepted_or_confirmed",
    "rejected": "rejected",
    "revoked": "revoked",
}
_LEGACY_GROUP = {
    "pending": "needs_review",
    "accepted": "accepted_or_confirmed",
    "rejected": "rejected",
    "conflict": "conflict",
}

# 状态机导出的可用动作（与原领域 Service 守卫一致；bulk 逐条仍走原 Service）
_FORMAL_ACTIONS = {
    "proposed": ["confirm", "reject"],
    "suspected": ["confirm", "reject"],
    "confirmed": ["revoke"],
    "rejected": ["restore_proposal"],
    "revoked": ["restore_proposal"],
}
_LEGACY_ACTIONS = {
    "pending": ["accept", "reject", "mark_conflict"],
    "accepted": ["mark_conflict", "reset"],
    "rejected": ["mark_conflict", "reset"],
    "conflict": ["reset"],
}


def _formal_strength(status: str, evidence_method: str) -> str:
    if status == "confirmed":
        return "confirmed_lineage"
    if status == "suspected":
        return "suspected_lineage"
    if status == "proposed":
        return (
            "manual_proposed_lineage"
            if evidence_method == "manual"
            else "project_proposed_lineage"
        )
    return "rejected_or_conflict"  # rejected / revoked


def _legacy_strength(review_status: str) -> str:
    if review_status == "accepted":
        return "accepted_legacy_evidence"
    if review_status == "pending":
        return "pending_legacy_evidence"
    return "rejected_or_conflict"  # rejected / conflict


_STRENGTH_TO_FORMAL_STATUSES = {
    "confirmed_lineage": ["confirmed"],
    "suspected_lineage": ["suspected"],
    "manual_proposed_lineage": ["proposed"],   # + method 过滤
    "project_proposed_lineage": ["proposed"],  # + method 过滤
    "rejected_or_conflict": ["rejected", "revoked"],
}
_STRENGTH_TO_LEGACY_STATUSES = {
    "accepted_legacy_evidence": ["accepted"],
    "pending_legacy_evidence": ["pending"],
    "rejected_or_conflict": ["rejected", "conflict"],
}
_GROUP_TO_FORMAL = {
    "needs_review": ["proposed", "suspected"],
    "accepted_or_confirmed": ["confirmed"],
    "rejected": ["rejected"],
    "revoked": ["revoked"],
    "conflict": [],
}
_GROUP_TO_LEGACY = {
    "needs_review": ["pending"],
    "accepted_or_confirmed": ["accepted"],
    "rejected": ["rejected"],
    "conflict": ["conflict"],
    "revoked": [],
}


# ============================ Summary ============================


async def get_summary(db: AsyncSession) -> ReviewSummaryOut:
    formal_rows = (
        await db.execute(
            select(FinalVideoUsage.status, func.count(FinalVideoUsage.id))
            .group_by(FinalVideoUsage.status)
        )
    ).all()
    formal = FormalSummaryOut()
    for status_, cnt in formal_rows:
        key = status_.value if hasattr(status_, "value") else str(status_)
        if hasattr(formal, key):
            setattr(formal, key, cnt)
    legacy_rows = (
        await db.execute(
            select(LegacyUsageEvidence.review_status, func.count(LegacyUsageEvidence.id))
            .group_by(LegacyUsageEvidence.review_status)
        )
    ).all()
    legacy = LegacySummaryOut()
    for status_, cnt in legacy_rows:
        if hasattr(legacy, status_):
            setattr(legacy, status_, cnt)
    return ReviewSummaryOut(
        formal=formal,
        legacy=legacy,
        # 审核工作量口径（绝不是使用次数，也绝不做 confirmed+accepted）
        needs_review_total=formal.proposed + formal.suspected + legacy.pending,
    )


# ============================ 列表（归并分页） ============================


class ReviewFilters:
    """统一筛选参数（两个事实来源各自解释）。"""

    def __init__(
        self,
        *,
        item_type: str | None = None,
        review_group: str | None = None,
        source_strength: str | None = None,
        product_family_id: int | None = None,
        product_variant_id: int | None = None,
        asset_id: int | None = None,
        final_video_id: int | None = None,
        source_directory_id: int | None = None,
        created_from: datetime | None = None,
        created_to: datetime | None = None,
        q: str | None = None,
    ) -> None:
        self.item_type = item_type
        self.review_group = review_group
        self.source_strength = source_strength
        self.product_family_id = product_family_id
        self.product_variant_id = product_variant_id
        self.asset_id = asset_id
        self.final_video_id = final_video_id
        self.source_directory_id = source_directory_id
        self.created_from = created_from
        self.created_to = created_to
        self.q = q


async def _bridge_product_ids(db: AsyncSession, f: ReviewFilters) -> list[int] | None:
    """product_family/variant → 兼容桥 legacy_product_id → asset.primary_product_id。

    variant 粒度退化为其 family 的兼容产品（Asset 无 variant 级绑定，文档说明）。
    返回 None=无该维筛选；[]=筛选无匹配（结果应为空）。
    """
    family_id = f.product_family_id
    if f.product_variant_id is not None:
        variant = await db.get(ProductVariant, f.product_variant_id)
        if variant is None:
            return []
        family_id = variant.family_id
    if family_id is None:
        return None
    family = await db.get(ProductFamily, family_id)
    if family is None or family.legacy_product_id is None:
        return []
    return [family.legacy_product_id]


def _apply_formal_filters(
    stmt: Select, f: ReviewFilters, product_ids: list[int] | None
) -> Select | None:
    """返回 None 表示该来源被筛选条件整体排除。"""
    statuses: set[str] | None = None
    if f.review_group:
        statuses = set(_GROUP_TO_FORMAL.get(f.review_group, []))
        if not statuses:
            return None
    if f.source_strength:
        st = _STRENGTH_TO_FORMAL_STATUSES.get(f.source_strength)
        if not st:
            return None
        statuses = set(st) if statuses is None else statuses & set(st)
        if not statuses:
            return None
        if f.source_strength == "manual_proposed_lineage":
            stmt = stmt.where(FinalVideoUsage.evidence_method == "manual")
        elif f.source_strength == "project_proposed_lineage":
            stmt = stmt.where(FinalVideoUsage.evidence_method != "manual")
    if statuses is not None:
        stmt = stmt.where(
            FinalVideoUsage.status.in_([FinalVideoUsageStatus(s) for s in statuses])
        )
    if f.asset_id is not None:
        stmt = stmt.where(FinalVideoUsage.source_asset_id == f.asset_id)
    if f.final_video_id is not None:
        stmt = stmt.where(FinalVideoUsage.final_video_id == f.final_video_id)
    if product_ids is not None:
        stmt = stmt.join(Asset, Asset.id == FinalVideoUsage.source_asset_id).where(
            Asset.primary_product_id.in_(product_ids)
        )
    elif f.source_directory_id is not None or f.q:
        stmt = stmt.join(Asset, Asset.id == FinalVideoUsage.source_asset_id)
    if f.source_directory_id is not None:
        stmt = stmt.where(Asset.source_directory_id == f.source_directory_id)
    if f.created_from is not None:
        stmt = stmt.where(FinalVideoUsage.created_at >= f.created_from)
    if f.created_to is not None:
        stmt = stmt.where(FinalVideoUsage.created_at <= f.created_to)
    if f.q:
        like = f"%{f.q}%"
        stmt = stmt.join(
            FinalVideo, FinalVideo.id == FinalVideoUsage.final_video_id
        ).where(or_(Asset.filename.ilike(like), FinalVideo.title.ilike(like)))
    return stmt


def _apply_legacy_filters(
    stmt: Select, f: ReviewFilters, product_ids: list[int] | None
) -> Select | None:
    if f.final_video_id is not None:
        return None  # 证据没有成片
    statuses: set[str] | None = None
    if f.review_group:
        statuses = set(_GROUP_TO_LEGACY.get(f.review_group, []))
        if not statuses:
            return None
    if f.source_strength:
        st = _STRENGTH_TO_LEGACY_STATUSES.get(f.source_strength)
        if not st:
            return None
        statuses = set(st) if statuses is None else statuses & set(st)
        if not statuses:
            return None
    if statuses is not None:
        stmt = stmt.where(LegacyUsageEvidence.review_status.in_(list(statuses)))
    if f.asset_id is not None:
        stmt = stmt.where(LegacyUsageEvidence.asset_id == f.asset_id)
    need_asset_join = product_ids is not None or f.source_directory_id is not None or bool(f.q)
    if need_asset_join:
        stmt = stmt.join(Asset, Asset.id == LegacyUsageEvidence.asset_id)
    if product_ids is not None:
        stmt = stmt.where(Asset.primary_product_id.in_(product_ids))
    if f.source_directory_id is not None:
        stmt = stmt.where(Asset.source_directory_id == f.source_directory_id)
    if f.created_from is not None:
        stmt = stmt.where(LegacyUsageEvidence.created_at >= f.created_from)
    if f.created_to is not None:
        stmt = stmt.where(LegacyUsageEvidence.created_at <= f.created_to)
    if f.q:
        like = f"%{f.q}%"
        stmt = stmt.where(
            or_(
                Asset.filename.ilike(like),
                LegacyUsageEvidence.matched_component.ilike(like),
            )
        )
    return stmt


async def list_items(
    db: AsyncSession,
    f: ReviewFilters,
    *,
    page: int,
    page_size: int,
    sort: str = "-created_at",
) -> ReviewListResponse:
    """统一列表：两事实表各自筛选 → 归并排序 → 切片（确定性、后端分页）。"""
    if sort not in ("-created_at", "created_at"):
        raise HTTPException(status_code=422, detail="sort 仅支持 ±created_at")
    desc = sort.startswith("-")
    product_ids = await _bridge_product_ids(db, f)
    if product_ids == [] and (
        f.product_family_id is not None or f.product_variant_id is not None
    ):
        return ReviewListResponse(items=[], total=0, page=page, page_size=page_size)

    upper = page * page_size  # 归并上界：各取前 upper 条足以覆盖当前页
    formal_rows: list[FinalVideoUsage] = []
    formal_total = 0
    if f.item_type in (None, "final_video_usage"):
        base = _apply_formal_filters(select(FinalVideoUsage), f, product_ids)
        if base is not None:
            count_stmt = _apply_formal_filters(
                select(func.count(FinalVideoUsage.id)), f, product_ids
            )
            formal_total = int(await db.scalar(count_stmt) or 0)
            order = (
                FinalVideoUsage.created_at.desc() if desc
                else FinalVideoUsage.created_at.asc()
            )
            formal_rows = list(
                (await db.scalars(
                    base.order_by(order, FinalVideoUsage.id.desc()).limit(upper)
                )).all()
            )
    legacy_rows: list[LegacyUsageEvidence] = []
    legacy_total = 0
    if f.item_type in (None, "legacy_usage_evidence"):
        base = _apply_legacy_filters(select(LegacyUsageEvidence), f, product_ids)
        if base is not None:
            count_stmt = _apply_legacy_filters(
                select(func.count(LegacyUsageEvidence.id)), f, product_ids
            )
            legacy_total = int(await db.scalar(count_stmt) or 0)
            order = (
                LegacyUsageEvidence.created_at.desc() if desc
                else LegacyUsageEvidence.created_at.asc()
            )
            legacy_rows = list(
                (await db.scalars(
                    base.order_by(order, LegacyUsageEvidence.id.desc()).limit(upper)
                )).all()
            )

    # 归并（确定性排序键：created_at, item_type, id desc）
    merged: list[tuple[Any, str]] = [(u, "final_video_usage") for u in formal_rows] + [
        (e, "legacy_usage_evidence") for e in legacy_rows
    ]
    merged.sort(
        key=lambda p: (p[0].created_at, p[1], -p[0].id), reverse=desc
    )
    window = merged[(page - 1) * page_size: page * page_size]
    items = await _assemble(db, window)
    return ReviewListResponse(
        items=items, total=formal_total + legacy_total, page=page, page_size=page_size
    )


async def _assemble(
    db: AsyncSession, window: list[tuple[Any, str]]
) -> list[ReviewItemOut]:
    """批量装配展示字段（固定查询数，防 N+1）。"""
    if not window:
        return []
    asset_ids: set[int] = set()
    shot_ids: set[int] = set()
    fv_ids: set[int] = set()
    rule_ids: set[int] = set()
    for row, typ in window:
        if typ == "final_video_usage":
            asset_ids.add(row.source_asset_id)
            shot_ids.add(row.source_shot_id)
            fv_ids.add(row.final_video_id)
        else:
            asset_ids.add(row.asset_id)
            if row.rule_id is not None:
                rule_ids.add(row.rule_id)

    assets = {
        a.id: a
        for a in (await db.scalars(select(Asset).where(Asset.id.in_(asset_ids)))).all()
    } if asset_ids else {}
    shots = {
        s.id: s
        for s in (await db.scalars(select(Shot).where(Shot.id.in_(shot_ids)))).all()
    } if shot_ids else {}
    fvs = {
        v.id: v
        for v in (await db.scalars(select(FinalVideo).where(FinalVideo.id.in_(fv_ids)))).all()
    } if fv_ids else {}
    rules = {
        r.id: r
        for r in (await db.scalars(
            select(LegacyUsageRule).where(LegacyUsageRule.id.in_(rule_ids))
        )).all()
    } if rule_ids else {}
    product_ids = {
        a.primary_product_id for a in assets.values() if a.primary_product_id is not None
    }
    products = {
        p.id: p.name
        for p in (await db.scalars(select(Product).where(Product.id.in_(product_ids)))).all()
    } if product_ids else {}

    out: list[ReviewItemOut] = []
    for row, typ in window:
        if typ == "final_video_usage":
            status = row.status.value if hasattr(row.status, "value") else str(row.status)
            asset = assets.get(row.source_asset_id)
            shot = shots.get(row.source_shot_id)
            fv = fvs.get(row.final_video_id)
            out.append(ReviewItemOut(
                item_type="final_video_usage",
                item_id=row.id,
                review_group=_FORMAL_GROUP.get(status, "needs_review"),
                source_strength=_formal_strength(status, row.evidence_method),
                review_status=status,
                asset_id=row.source_asset_id,
                asset_filename=asset.filename if asset else None,
                shot_id=row.source_shot_id,
                shot_sequence_no=shot.sequence_no if shot else None,
                final_video_id=row.final_video_id,
                final_video_title=fv.title if fv else None,
                product=(
                    products.get(asset.primary_product_id)
                    if asset and asset.primary_product_id else None
                ),
                source_label=row.evidence_method,
                evidence_summary=row.evidence_summary,
                created_at=row.created_at,
                last_observed_at=None,
                reviewed_at=row.confirmed_at or row.rejected_at or row.revoked_at,
                available_actions=_FORMAL_ACTIONS.get(status, []),
            ))
        else:
            asset = assets.get(row.asset_id)
            rule = rules.get(row.rule_id) if row.rule_id else None
            rule_name = rule.name if rule else (row.rule_snapshot or {}).get("name")
            out.append(ReviewItemOut(
                item_type="legacy_usage_evidence",
                item_id=row.id,
                review_group=_LEGACY_GROUP.get(row.review_status, "needs_review"),
                source_strength=_legacy_strength(row.review_status),
                review_status=row.review_status,
                asset_id=row.asset_id,
                asset_filename=asset.filename if asset else None,
                shot_id=None,             # 证据没有 Shot
                final_video_id=None,      # 证据没有成片
                product=(
                    products.get(asset.primary_product_id)
                    if asset and asset.primary_product_id else None
                ),
                source_label=(
                    f"{rule_name} v{row.rule_version}" if rule_name
                    else f"规则已删除 v{row.rule_version}"
                ),
                evidence_summary=row.matched_component,
                created_at=row.created_at,
                last_observed_at=row.last_observed_at,
                reviewed_at=row.reviewed_at,
                available_actions=_LEGACY_ACTIONS.get(row.review_status, []),
            ))
    return out


# ============================ 详情 ============================


async def get_item_detail(
    db: AsyncSession, item_type: str, item_id: int
) -> ReviewItemDetailOut:
    if item_type == "final_video_usage":
        usage = await db.get(FinalVideoUsage, item_id)
        if usage is None:
            raise HTTPException(status_code=404, detail="使用记录不存在")
        head = (await _assemble(db, [(usage, "final_video_usage")]))[0]
        usage_out = (
            await final_video_service._to_usage_outs(
                db, [usage], with_occurrences=True
            )
        )[0]
        events = (
            await db.scalars(
                select(FinalVideoUsageEvent)
                .where(FinalVideoUsageEvent.usage_id == item_id)
                .order_by(FinalVideoUsageEvent.id)
            )
        ).all()
        return ReviewItemDetailOut(
            item=head,
            formal_usage=usage_out.model_dump(mode="json"),
            events=[
                {
                    "id": e.id, "action": e.action,
                    "before_status": e.before_status, "after_status": e.after_status,
                    "actor_label": e.actor_label, "note": e.note,
                    "created_at": e.created_at.isoformat(),
                }
                for e in events
            ],
        )
    if item_type == "legacy_usage_evidence":
        ev = await db.get(LegacyUsageEvidence, item_id)
        if ev is None:
            raise HTTPException(status_code=404, detail="证据不存在")
        head = (await _assemble(db, [(ev, "legacy_usage_evidence")]))[0]
        ev_out: EvidenceOut = (await legacy_evidence_service.evidences_to_out(db, [ev]))[0]
        events = (
            await db.scalars(
                select(LegacyUsageEvidenceEvent)
                .where(LegacyUsageEvidenceEvent.evidence_id == item_id)
                .order_by(LegacyUsageEvidenceEvent.id)
            )
        ).all()
        return ReviewItemDetailOut(
            item=head,
            legacy_evidence=ev_out.model_dump(mode="json"),
            events=[
                {
                    "id": e.id, "action": e.action,
                    "before_status": e.before_status, "after_status": e.after_status,
                    "actor_label": e.actor_label, "note": e.note,
                    "created_at": e.created_at.isoformat(),
                }
                for e in events
            ],
        )
    raise HTTPException(status_code=422, detail=f"不支持的 item_type: {item_type}")


# ============================ typed bulk（走原领域 Service） ============================


async def bulk_review(db: AsyncSession, req: BulkReviewRequest) -> BulkReviewOut:
    """统一批量：显式 items、单一类型批次、逐条调用原状态机 + 原事件审计。

    幂等策略（API/UI/测试统一）：状态不符（含已 confirmed 再 confirm、已
    accepted 再 accept 等 409）→ **skipped** 并给出原因；404 → failed。
    """
    types = {i.item_type for i in req.items}
    if len(types) > 1:
        raise HTTPException(
            status_code=422,
            detail="不支持混合类型批次：请分别提交正式血缘与历史证据的批量操作",
        )
    item_type = next(iter(types))
    if item_type == "final_video_usage":
        if req.action not in FORMAL_BULK_ACTIONS:
            raise HTTPException(
                status_code=422,
                detail=f"正式血缘不支持动作 {req.action}（可用：{'/'.join(FORMAL_BULK_ACTIONS)}）",
            )
        handler = {
            "confirm": final_video_service.confirm_usage,
            "reject": final_video_service.reject_usage,
            "revoke": final_video_service.revoke_usage,
            "restore_proposal": final_video_service.restore_usage_proposal,
        }[req.action]
    else:
        if req.action not in LEGACY_BULK_ACTIONS:
            raise HTTPException(
                status_code=422,
                detail=f"历史证据不支持动作 {req.action}（可用：{'/'.join(LEGACY_BULK_ACTIONS)}）",
            )
        legacy_action = {"mark_conflict": "mark-conflict"}.get(req.action, req.action)

    out = BulkReviewOut()
    for ref in req.items:
        try:
            if item_type == "final_video_usage":
                await handler(
                    db, ref.item_id, actor_label=req.actor_label, note=req.note
                )
            else:
                await legacy_evidence_service.review_evidence(
                    db, ref.item_id, legacy_action,
                    actor_label=req.actor_label, note=req.note,
                )
            out.succeeded += 1
            out.results.append(BulkItemResult(
                item_type=item_type, item_id=ref.item_id, outcome="succeeded"
            ))
        except HTTPException as exc:
            await db.rollback()
            if exc.status_code == 409:
                out.skipped += 1
                out.results.append(BulkItemResult(
                    item_type=item_type, item_id=ref.item_id,
                    outcome="skipped", reason=str(exc.detail),
                ))
            elif exc.status_code == 404:
                out.failed += 1
                out.results.append(BulkItemResult(
                    item_type=item_type, item_id=ref.item_id,
                    outcome="failed", reason=str(exc.detail),
                ))
            else:
                raise
    return out
