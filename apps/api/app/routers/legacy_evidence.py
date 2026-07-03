"""PR-C Gate B 历史使用证据路由（注册前缀 /api，见 main.py）。

规则管理 / 只读预览 / 幂等导入 / 人工审核（单条 + 批量）/ append-only 事件。
接受历史证据不等于确认使用次数，也不等于确认对应成片或具体镜头；
证据绝不影响 confirmed 使用次数与 FinalVideoUsage。
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.schemas.legacy_evidence import (
    BulkReviewOut,
    BulkReviewRequest,
    EvidenceEventListResponse,
    EvidenceEventOut,
    EvidenceListResponse,
    EvidenceOut,
    ImportRequest,
    ImportRunListResponse,
    ImportRunOut,
    PreviewOut,
    ReviewActionRequest,
    RuleCreateRequest,
    RuleListResponse,
    RuleOut,
    RuleUpdateRequest,
)
from app.services import legacy_evidence_service as svc

rules_router = APIRouter(prefix="/legacy-usage-rules", tags=["legacy-usage"])
imports_router = APIRouter(prefix="/legacy-usage-imports", tags=["legacy-usage"])
evidence_router = APIRouter(prefix="/legacy-usage-evidence", tags=["legacy-usage"])


# ============================ 规则管理 ============================


@rules_router.get("", response_model=RuleListResponse)
async def list_rules(
    include_archived: bool = Query(False),
    db: AsyncSession = Depends(get_db),
) -> RuleListResponse:
    rows, total = await svc.list_rules(db, include_archived=include_archived)
    return RuleListResponse(items=await svc.rules_to_out(db, rows), total=total)


@rules_router.post("", response_model=RuleOut, status_code=status.HTTP_201_CREATED)
async def create_rule(
    req: RuleCreateRequest, db: AsyncSession = Depends(get_db)
) -> RuleOut:
    rule = await svc.create_rule(db, req)
    return (await svc.rules_to_out(db, [rule]))[0]


@rules_router.get("/{rule_id}", response_model=RuleOut)
async def get_rule(rule_id: int, db: AsyncSession = Depends(get_db)) -> RuleOut:
    rule = await svc.get_rule_or_404(db, rule_id)
    return (await svc.rules_to_out(db, [rule]))[0]


@rules_router.patch("/{rule_id}", response_model=RuleOut)
async def update_rule(
    rule_id: int, req: RuleUpdateRequest, db: AsyncSession = Depends(get_db)
) -> RuleOut:
    rule = await svc.update_rule(db, rule_id, req)
    return (await svc.rules_to_out(db, [rule]))[0]


@rules_router.post("/{rule_id}/enable", response_model=RuleOut)
async def enable_rule(rule_id: int, db: AsyncSession = Depends(get_db)) -> RuleOut:
    rule = await svc.set_rule_enabled(db, rule_id, True)
    return (await svc.rules_to_out(db, [rule]))[0]


@rules_router.post("/{rule_id}/disable", response_model=RuleOut)
async def disable_rule(rule_id: int, db: AsyncSession = Depends(get_db)) -> RuleOut:
    rule = await svc.set_rule_enabled(db, rule_id, False)
    return (await svc.rules_to_out(db, [rule]))[0]


@rules_router.post("/{rule_id}/archive", response_model=RuleOut)
async def archive_rule(rule_id: int, db: AsyncSession = Depends(get_db)) -> RuleOut:
    rule = await svc.archive_rule(db, rule_id)
    return (await svc.rules_to_out(db, [rule]))[0]


@rules_router.post("/{rule_id}/restore", response_model=RuleOut)
async def restore_rule(rule_id: int, db: AsyncSession = Depends(get_db)) -> RuleOut:
    rule = await svc.restore_rule(db, rule_id)
    return (await svc.rules_to_out(db, [rule]))[0]


# ============================ 预览 / 导入 ============================


@imports_router.post("/preview", response_model=PreviewOut)
async def preview_import(
    req: ImportRequest, db: AsyncSession = Depends(get_db)
) -> PreviewOut:
    """只读预览：零写入（不建 run、不建证据、不改状态、不写源目录）。"""
    return await svc.preview_import(db, req)


@imports_router.post("", response_model=ImportRunOut, status_code=status.HTTP_202_ACCEPTED)
async def create_import(
    req: ImportRequest, db: AsyncSession = Depends(get_db)
) -> ImportRunOut:
    run = await svc.request_import(db, req)
    return ImportRunOut.model_validate(run)


@imports_router.get("", response_model=ImportRunListResponse)
async def list_imports(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
) -> ImportRunListResponse:
    rows, total = await svc.list_runs(db, page=page, page_size=page_size)
    return ImportRunListResponse(
        items=[ImportRunOut.model_validate(r) for r in rows], total=total
    )


@imports_router.get("/{run_id}", response_model=ImportRunOut)
async def get_import(run_id: int, db: AsyncSession = Depends(get_db)) -> ImportRunOut:
    run = await svc.get_run_or_404(db, run_id)
    return ImportRunOut.model_validate(run)


@imports_router.post("/{run_id}/cancel", response_model=ImportRunOut)
async def cancel_import(run_id: int, db: AsyncSession = Depends(get_db)) -> ImportRunOut:
    run = await svc.cancel_run(db, run_id)
    return ImportRunOut.model_validate(run)


# ============================ 证据 / 审核 ============================


@evidence_router.get("", response_model=EvidenceListResponse)
async def list_evidence(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    review_status: str | None = Query(None),
    asset_id: int | None = Query(None),
    rule_id: int | None = Query(None),
    db: AsyncSession = Depends(get_db),
) -> EvidenceListResponse:
    rows, total = await svc.list_evidence(
        db,
        page=page,
        page_size=page_size,
        review_status=review_status,
        asset_id=asset_id,
        rule_id=rule_id,
    )
    return EvidenceListResponse(
        items=await svc.evidences_to_out(db, rows),
        total=total,
        page=page,
        page_size=page_size,
    )


@evidence_router.post("/bulk-accept", response_model=BulkReviewOut)
async def bulk_accept(
    req: BulkReviewRequest, db: AsyncSession = Depends(get_db)
) -> BulkReviewOut:
    return await svc.bulk_review(
        db, req.evidence_ids, "accept", actor_label=req.actor_label, note=req.note
    )


@evidence_router.post("/bulk-reject", response_model=BulkReviewOut)
async def bulk_reject(
    req: BulkReviewRequest, db: AsyncSession = Depends(get_db)
) -> BulkReviewOut:
    return await svc.bulk_review(
        db, req.evidence_ids, "reject", actor_label=req.actor_label, note=req.note
    )


@evidence_router.get("/{evidence_id}", response_model=EvidenceOut)
async def get_evidence(
    evidence_id: int, db: AsyncSession = Depends(get_db)
) -> EvidenceOut:
    ev = await svc.get_evidence_or_404(db, evidence_id)
    return (await svc.evidences_to_out(db, [ev]))[0]


async def _single_action(
    db: AsyncSession, evidence_id: int, action: str, req: ReviewActionRequest | None
) -> EvidenceOut:
    ev = await svc.review_evidence(
        db,
        evidence_id,
        action,
        actor_label=req.actor_label if req else None,
        note=req.note if req else None,
    )
    return (await svc.evidences_to_out(db, [ev]))[0]


@evidence_router.post("/{evidence_id}/accept", response_model=EvidenceOut)
async def accept_evidence(
    evidence_id: int,
    req: ReviewActionRequest | None = None,
    db: AsyncSession = Depends(get_db),
) -> EvidenceOut:
    """接受为有效历史线索——不确认次数/Shot/成片，不产生 FinalVideoUsage。"""
    return await _single_action(db, evidence_id, "accept", req)


@evidence_router.post("/{evidence_id}/reject", response_model=EvidenceOut)
async def reject_evidence(
    evidence_id: int,
    req: ReviewActionRequest | None = None,
    db: AsyncSession = Depends(get_db),
) -> EvidenceOut:
    return await _single_action(db, evidence_id, "reject", req)


@evidence_router.post("/{evidence_id}/mark-conflict", response_model=EvidenceOut)
async def mark_conflict(
    evidence_id: int,
    req: ReviewActionRequest | None = None,
    db: AsyncSession = Depends(get_db),
) -> EvidenceOut:
    return await _single_action(db, evidence_id, "mark-conflict", req)


@evidence_router.post("/{evidence_id}/reset", response_model=EvidenceOut)
async def reset_evidence(
    evidence_id: int,
    req: ReviewActionRequest | None = None,
    db: AsyncSession = Depends(get_db),
) -> EvidenceOut:
    """重置回 pending（不删除任何事件历史）。"""
    return await _single_action(db, evidence_id, "reset", req)


@evidence_router.get("/{evidence_id}/events", response_model=EvidenceEventListResponse)
async def list_evidence_events(
    evidence_id: int, db: AsyncSession = Depends(get_db)
) -> EvidenceEventListResponse:
    rows = await svc.list_evidence_events(db, evidence_id)
    return EvidenceEventListResponse(
        items=[EvidenceEventOut.model_validate(e) for e in rows]
    )
