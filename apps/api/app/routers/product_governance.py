"""PR-A2 Gate B 路由：完整度策略 / readiness / 入驻审核 / 混淆关系 / 变更历史（前缀 /api）。

- readiness 与入驻审核由后端基于真实数据计算/守卫，绝不采信前端分数。
- 审批接口**不是**安全权限控制（当前为可信内网人工审核，尚未启用用户权限）。
- catalog-revisions 只读（append-only，无修改历史接口）。
"""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.schemas.product_governance import (
    ConfusionPairIn,
    ConfusionPairListResponse,
    ConfusionPairOut,
    ConfusionPairUpdateIn,
    ConfusionSide,
    OnboardingActionIn,
    OnboardingListResponse,
    OnboardingOut,
    ReadinessOut,
    ReadinessPolicyIn,
    ReadinessPolicyListResponse,
    ReadinessPolicyOut,
    RevisionListResponse,
    RevisionOut,
)
from app.services import governance_service as gov
from app.services import revision_service
from app.services.catalog_service import CatalogConflict, CatalogError

router = APIRouter(tags=["product-governance"])


def _err(exc: CatalogError) -> HTTPException:
    code = 409 if isinstance(exc, CatalogConflict) else 422
    return HTTPException(status_code=code, detail=str(exc))


# ============================ 完整度策略 ============================


@router.get("/product-readiness-policies", response_model=ReadinessPolicyListResponse)
async def list_policies(
    category_id: int | None = None,
    include_archived: bool = False,
    limit: int = 50,
    offset: int = 0,
    db: AsyncSession = Depends(get_db),
) -> ReadinessPolicyListResponse:
    rows, total = await gov.list_policies(
        db, category_id=category_id, include_archived=include_archived,
        limit=limit, offset=offset,
    )
    return ReadinessPolicyListResponse(
        items=[ReadinessPolicyOut.model_validate(r) for r in rows], total=total
    )


@router.post("/product-readiness-policies", response_model=ReadinessPolicyOut, status_code=201)
async def create_policy(
    body: ReadinessPolicyIn, db: AsyncSession = Depends(get_db)
) -> ReadinessPolicyOut:
    try:
        row = await gov.create_policy(db, body.model_dump(exclude_unset=True))
    except CatalogError as exc:
        raise _err(exc) from exc
    return ReadinessPolicyOut.model_validate(row)


async def _fetch_policy(db: AsyncSession, pid: int):
    from clipmind_shared.models import ProductReadinessPolicy

    row = await db.get(ProductReadinessPolicy, pid)
    if row is None:
        raise HTTPException(status_code=404, detail="策略不存在")
    return row


@router.get("/product-readiness-policies/{pid}", response_model=ReadinessPolicyOut)
async def get_policy(pid: int, db: AsyncSession = Depends(get_db)) -> ReadinessPolicyOut:
    return ReadinessPolicyOut.model_validate(await _fetch_policy(db, pid))


@router.post("/product-readiness-policies/{pid}/activate", response_model=ReadinessPolicyOut)
async def activate_policy(pid: int, db: AsyncSession = Depends(get_db)) -> ReadinessPolicyOut:
    row = await _fetch_policy(db, pid)
    try:
        return ReadinessPolicyOut.model_validate(await gov.activate_policy(db, row))
    except CatalogError as exc:
        raise _err(exc) from exc


@router.post("/product-readiness-policies/{pid}/archive", response_model=ReadinessPolicyOut)
async def archive_policy(pid: int, db: AsyncSession = Depends(get_db)) -> ReadinessPolicyOut:
    row = await _fetch_policy(db, pid)
    try:
        return ReadinessPolicyOut.model_validate(await gov.archive_policy(db, row))
    except CatalogError as exc:
        raise _err(exc) from exc


# ============================ Readiness 计算 ============================


@router.get("/product-catalog/{level}/{node_id}/readiness", response_model=ReadinessOut)
async def get_readiness(
    level: str, node_id: int, db: AsyncSession = Depends(get_db)
) -> ReadinessOut:
    try:
        return ReadinessOut.model_validate(await gov.compute_readiness(db, level, node_id))
    except CatalogError as exc:
        raise _err(exc) from exc


@router.post("/product-catalog/{level}/{node_id}/evaluate-readiness", response_model=ReadinessOut)
async def evaluate_readiness(
    level: str, node_id: int, db: AsyncSession = Depends(get_db)
) -> ReadinessOut:
    """重新评估（与 GET 相同的确定性计算；POST 供 UI「重新评估」语义）。"""
    try:
        return ReadinessOut.model_validate(await gov.compute_readiness(db, level, node_id))
    except CatalogError as exc:
        raise _err(exc) from exc


# ============================ 入驻审核 ============================


@router.post("/product-catalog/{level}/{node_id}/submit-review", response_model=OnboardingOut)
async def submit_review(
    level: str, node_id: int, body: OnboardingActionIn | None = None,
    db: AsyncSession = Depends(get_db),
) -> OnboardingOut:
    try:
        row = await gov.submit_review(
            db, level, node_id, submitted_by=(body.actor_label if body else None)
        )
    except CatalogError as exc:
        raise _err(exc) from exc
    return OnboardingOut.model_validate(row)


@router.post("/product-catalog/{level}/{node_id}/approve", response_model=OnboardingOut)
async def approve(
    level: str, node_id: int, body: OnboardingActionIn | None = None,
    db: AsyncSession = Depends(get_db),
) -> OnboardingOut:
    try:
        row = await gov.approve(
            db, level, node_id,
            note=(body.note if body else None),
            reviewed_by=(body.actor_label if body else None),
        )
    except CatalogError as exc:
        raise _err(exc) from exc
    return OnboardingOut.model_validate(row)


@router.post("/product-catalog/{level}/{node_id}/request-changes", response_model=OnboardingOut)
async def request_changes(
    level: str, node_id: int, body: OnboardingActionIn | None = None,
    db: AsyncSession = Depends(get_db),
) -> OnboardingOut:
    try:
        row = await gov.request_changes(
            db, level, node_id,
            note=(body.note if body else None),
            reviewed_by=(body.actor_label if body else None),
        )
    except CatalogError as exc:
        raise _err(exc) from exc
    return OnboardingOut.model_validate(row)


@router.post("/product-catalog/{level}/{node_id}/block", response_model=OnboardingOut)
async def block(
    level: str, node_id: int, body: OnboardingActionIn | None = None,
    db: AsyncSession = Depends(get_db),
) -> OnboardingOut:
    try:
        row = await gov.block(
            db, level, node_id,
            note=(body.note if body else None),
            reviewed_by=(body.actor_label if body else None),
        )
    except CatalogError as exc:
        raise _err(exc) from exc
    return OnboardingOut.model_validate(row)


@router.get("/product-catalog/{level}/{node_id}/onboarding", response_model=OnboardingOut | None)
async def get_onboarding(
    level: str, node_id: int, db: AsyncSession = Depends(get_db)
) -> OnboardingOut | None:
    try:
        row = await gov.get_onboarding(db, level, node_id)
    except CatalogError as exc:
        raise _err(exc) from exc
    return OnboardingOut.model_validate(row) if row else None


@router.get("/product-onboarding-reviews", response_model=OnboardingListResponse)
async def list_onboarding(
    status_filter: str | None = Query(None, alias="status"),
    level: str | None = None,
    limit: int = 50,
    offset: int = 0,
    db: AsyncSession = Depends(get_db),
) -> OnboardingListResponse:
    try:
        rows, total = await gov.list_onboarding(
            db, status=status_filter, level=level, limit=limit, offset=offset
        )
    except CatalogError as exc:
        raise _err(exc) from exc
    return OnboardingListResponse(
        items=[OnboardingOut.model_validate(r) for r in rows], total=total
    )


# ============================ 混淆关系 ============================


async def _pair_out(db: AsyncSession, pair) -> ConfusionPairOut:
    out = ConfusionPairOut.model_validate(pair)
    sides = await gov.pair_sides(db, pair)
    out.left = ConfusionSide.model_validate(sides["left"]) if sides["left"] else None
    out.right = ConfusionSide.model_validate(sides["right"]) if sides["right"] else None
    return out


@router.get("/product-confusion-pairs", response_model=ConfusionPairListResponse)
async def list_pairs(
    target_level: str | None = None,
    target_id: int | None = None,
    include_archived: bool = False,
    limit: int = 50,
    offset: int = 0,
    db: AsyncSession = Depends(get_db),
) -> ConfusionPairListResponse:
    try:
        rows, total = await gov.list_pairs(
            db, target_level=target_level, target_id=target_id,
            include_archived=include_archived, limit=limit, offset=offset,
        )
    except CatalogError as exc:
        raise _err(exc) from exc
    return ConfusionPairListResponse(
        items=[await _pair_out(db, r) for r in rows], total=total
    )


@router.post("/product-confusion-pairs", response_model=ConfusionPairOut, status_code=201)
async def create_pair(
    body: ConfusionPairIn, db: AsyncSession = Depends(get_db)
) -> ConfusionPairOut:
    try:
        row = await gov.create_pair(db, body.model_dump(exclude_unset=True))
    except CatalogError as exc:
        raise _err(exc) from exc
    return await _pair_out(db, row)


async def _fetch_pair(db: AsyncSession, pid: int):
    from clipmind_shared.models import ProductConfusionPair

    row = await db.get(ProductConfusionPair, pid)
    if row is None:
        raise HTTPException(status_code=404, detail="混淆关系不存在")
    return row


@router.get("/product-confusion-pairs/{pid}", response_model=ConfusionPairOut)
async def get_pair(pid: int, db: AsyncSession = Depends(get_db)) -> ConfusionPairOut:
    return await _pair_out(db, await _fetch_pair(db, pid))


@router.patch("/product-confusion-pairs/{pid}", response_model=ConfusionPairOut)
async def update_pair(
    pid: int, body: ConfusionPairUpdateIn, db: AsyncSession = Depends(get_db)
) -> ConfusionPairOut:
    row = await _fetch_pair(db, pid)
    try:
        row = await gov.update_pair(db, row, body.model_dump(exclude_unset=True))
    except CatalogError as exc:
        raise _err(exc) from exc
    return await _pair_out(db, row)


@router.post("/product-confusion-pairs/{pid}/archive", response_model=ConfusionPairOut)
async def archive_pair(pid: int, db: AsyncSession = Depends(get_db)) -> ConfusionPairOut:
    row = await _fetch_pair(db, pid)
    try:
        return await _pair_out(db, await gov.archive_pair(db, row))
    except CatalogError as exc:
        raise _err(exc) from exc


@router.post("/product-confusion-pairs/{pid}/restore", response_model=ConfusionPairOut)
async def restore_pair(pid: int, db: AsyncSession = Depends(get_db)) -> ConfusionPairOut:
    row = await _fetch_pair(db, pid)
    try:
        return await _pair_out(db, await gov.restore_pair(db, row))
    except CatalogError as exc:
        raise _err(exc) from exc


@router.get(
    "/product-catalog/{level}/{node_id}/confusions", response_model=ConfusionPairListResponse
)
async def node_confusions(
    level: str, node_id: int, include_archived: bool = False,
    db: AsyncSession = Depends(get_db),
) -> ConfusionPairListResponse:
    try:
        rows, total = await gov.list_pairs(
            db, target_level=level, target_id=node_id, include_archived=include_archived,
            limit=200, offset=0,
        )
    except CatalogError as exc:
        raise _err(exc) from exc
    return ConfusionPairListResponse(
        items=[await _pair_out(db, r) for r in rows], total=total
    )


# ============================ 变更历史（只读）============================


@router.get("/catalog-revisions", response_model=RevisionListResponse)
async def list_revisions(
    entity_type: str | None = None,
    entity_id: int | None = None,
    action: str | None = None,
    created_from: datetime | None = None,
    created_to: datetime | None = None,
    limit: int = 50,
    offset: int = 0,
    db: AsyncSession = Depends(get_db),
) -> RevisionListResponse:
    rows, total = await revision_service.list_revisions(
        db, entity_type=entity_type, entity_id=entity_id, action=action,
        created_from=created_from, created_to=created_to, limit=limit, offset=offset,
    )
    return RevisionListResponse(items=[RevisionOut.model_validate(r) for r in rows], total=total)


@router.get("/catalog-revisions/{rev_id}", response_model=RevisionOut)
async def get_revision(rev_id: int, db: AsyncSession = Depends(get_db)) -> RevisionOut:
    row = await revision_service.get_revision(db, rev_id)
    if row is None:
        raise HTTPException(status_code=404, detail="变更记录不存在")
    return RevisionOut.model_validate(row)


@router.get("/product-catalog/{level}/{node_id}/revisions", response_model=RevisionListResponse)
async def node_revisions(
    level: str, node_id: int, limit: int = 50, offset: int = 0,
    db: AsyncSession = Depends(get_db),
) -> RevisionListResponse:
    if level not in ("category", "family", "variant", "sku"):
        raise HTTPException(status_code=422, detail="未知层级")
    rows, total = await revision_service.list_revisions(
        db, entity_type=level, entity_id=node_id, limit=limit, offset=offset
    )
    return RevisionListResponse(items=[RevisionOut.model_validate(r) for r in rows], total=total)
