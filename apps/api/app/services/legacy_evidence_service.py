"""PR-C Gate B：历史使用证据业务逻辑（规则 / 预览 / 导入 / 人工审核 / 汇总）。

隔离铁律（docs/LEGACY_USAGE_EVIDENCE.md，测试锁定）：
- 证据与 final_video_usage 零关联；accept **不创建** FinalVideoUsage、
  **不改变** confirmed 使用次数；系统不存在任何手工输入 usage_count 的入口；
- preview 零写入；正式导入幂等（evidence_key 唯一 + 观察数累加），
  绝不把 accepted/rejected/conflict 覆盖回 pending；
- 事件 append-only 与状态变化同事务；规则修改不重解释历史证据（快照冻结）。
"""

from __future__ import annotations

from collections import defaultdict
from typing import Any

from clipmind_shared.db.base import utcnow
from clipmind_shared.legacy_rules import (
    RuleSpec,
    RuleValidationError,
    compute_evidence_key,
    compute_snapshot_hash,
    match_rule,
    normalize_text,
    validate_rule_config,
)
from clipmind_shared.models import (
    Asset,
    AssetLocation,
    FinalVideoUsage,
    LegacyUsageEvidence,
    LegacyUsageEvidenceEvent,
    LegacyUsageImportRun,
    LegacyUsageRule,
    Product,
    SourceDirectory,
)
from clipmind_shared.models.enums import FinalVideoUsageStatus
from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.schemas.legacy_evidence import (
    AssetLegacySummaryOut,
    BulkReviewOut,
    EvidenceOut,
    ImportRequest,
    PreviewOut,
    PreviewSampleOut,
    RuleCreateRequest,
    RuleOut,
    RuleUpdateRequest,
)
from app.tasks_client import enqueue_legacy_import

PREVIEW_SAMPLE_MAX = 20


# ============================ 规则 CRUD ============================


async def get_rule_or_404(db: AsyncSession, rule_id: int) -> LegacyUsageRule:
    rule = await db.get(LegacyUsageRule, rule_id)
    if rule is None:
        raise HTTPException(status_code=404, detail="规则不存在")
    return rule


def _normalized_pattern(pattern: str, case_sensitive: bool) -> str:
    return normalize_text(pattern, case_sensitive=case_sensitive)


def _semantic_tuple(rule: LegacyUsageRule) -> tuple:
    """影响匹配语义的字段元组（任一变化 => version+1）。"""
    return (
        rule.match_target,
        rule.match_operator,
        rule.normalized_pattern,
        rule.case_sensitive,
        rule.source_directory_id,
        rule.include_present_locations,
        rule.include_missing_locations,
        rule.include_historical_locations,
    )


def _rule_snapshot_hash(rule: LegacyUsageRule) -> str:
    return compute_snapshot_hash(
        rule_id=rule.id,
        match_target=rule.match_target,
        match_operator=rule.match_operator,
        normalized_pattern=rule.normalized_pattern,
        case_sensitive=rule.case_sensitive,
        source_directory_id=rule.source_directory_id,
        include_present_locations=rule.include_present_locations,
        include_missing_locations=rule.include_missing_locations,
        include_historical_locations=rule.include_historical_locations,
    )


async def create_rule(db: AsyncSession, req: RuleCreateRequest) -> LegacyUsageRule:
    try:
        pattern = validate_rule_config(req.match_target, req.match_operator, req.pattern)
    except RuleValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if req.source_directory_id is not None:
        if await db.get(SourceDirectory, req.source_directory_id) is None:
            raise HTTPException(status_code=404, detail="来源目录不存在")
    rule = LegacyUsageRule(
        name=req.name,
        description=req.description,
        source_directory_id=req.source_directory_id,
        match_target=req.match_target,
        match_operator=req.match_operator,
        pattern=pattern,
        normalized_pattern=_normalized_pattern(pattern, req.case_sensitive),
        case_sensitive=req.case_sensitive,
        include_present_locations=req.include_present_locations,
        include_missing_locations=req.include_missing_locations,
        include_historical_locations=req.include_historical_locations,
        priority=req.priority,
        version=1,
        snapshot_hash="",
    )
    db.add(rule)
    await db.flush()  # 先拿 id，语义指纹含 rule_id
    rule.snapshot_hash = _rule_snapshot_hash(rule)
    await db.commit()
    await db.refresh(rule)
    return rule


async def list_rules(
    db: AsyncSession, *, include_archived: bool = False
) -> tuple[list[LegacyUsageRule], int]:
    base = select(LegacyUsageRule)
    if not include_archived:
        base = base.where(LegacyUsageRule.archived_at.is_(None))
    rows = (
        await db.scalars(
            base.order_by(LegacyUsageRule.priority, LegacyUsageRule.id)
        )
    ).all()
    return list(rows), len(rows)


async def rules_to_out(db: AsyncSession, rules: list[LegacyUsageRule]) -> list[RuleOut]:
    if not rules:
        return []
    sd_ids = {r.source_directory_id for r in rules if r.source_directory_id is not None}
    sd_names: dict[int, str] = {}
    if sd_ids:
        sd_names = {
            s.id: s.name
            for s in (
                await db.scalars(
                    select(SourceDirectory).where(SourceDirectory.id.in_(sd_ids))
                )
            ).all()
        }
    counts = {
        rid: cnt
        for rid, cnt in (
            await db.execute(
                select(LegacyUsageEvidence.rule_id, func.count(LegacyUsageEvidence.id))
                .where(LegacyUsageEvidence.rule_id.in_([r.id for r in rules]))
                .group_by(LegacyUsageEvidence.rule_id)
            )
        ).all()
    }
    outs = []
    for r in rules:
        out = RuleOut.model_validate(r)
        if r.source_directory_id is not None:
            out.source_directory_name = sd_names.get(r.source_directory_id)
        out.evidence_count = counts.get(r.id, 0)
        outs.append(out)
    return outs


async def update_rule(
    db: AsyncSession, rule_id: int, req: RuleUpdateRequest
) -> LegacyUsageRule:
    rule = await get_rule_or_404(db, rule_id)
    if rule.archived_at is not None:
        raise HTTPException(status_code=409, detail="规则已归档，禁止修改（可先恢复）")
    data = req.model_dump(exclude_unset=True)
    target = data.get("match_target", rule.match_target)
    operator = data.get("match_operator", rule.match_operator)
    pattern = data.get("pattern", rule.pattern)
    try:
        pattern = validate_rule_config(target, operator, pattern)
    except RuleValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if data.get("source_directory_id") is not None:
        if await db.get(SourceDirectory, data["source_directory_id"]) is None:
            raise HTTPException(status_code=404, detail="来源目录不存在")
    semantic_before = _semantic_tuple(rule)
    for field, value in data.items():
        setattr(rule, field, value)
    rule.pattern = pattern
    rule.normalized_pattern = _normalized_pattern(pattern, rule.case_sensitive)
    # 语义字段（target/operator/pattern/case/来源/位置范围）任一变化 => 版本 +1；
    # 展示字段（name/description/priority）不加版本（display-only 策略，测试锁定）。
    # 修改只影响后续 preview/import（快照另存）；既有证据不被重解释。
    if _semantic_tuple(rule) != semantic_before:
        rule.version += 1
    rule.snapshot_hash = _rule_snapshot_hash(rule)  # 语义等价则 hash 不变
    await db.commit()
    await db.refresh(rule)
    return rule


async def set_rule_enabled(db: AsyncSession, rule_id: int, enabled: bool) -> LegacyUsageRule:
    rule = await get_rule_or_404(db, rule_id)
    if rule.archived_at is not None:
        raise HTTPException(status_code=409, detail="规则已归档")
    rule.enabled = enabled
    await db.commit()
    await db.refresh(rule)
    return rule


async def archive_rule(db: AsyncSession, rule_id: int) -> LegacyUsageRule:
    rule = await get_rule_or_404(db, rule_id)
    if rule.archived_at is not None:
        raise HTTPException(status_code=409, detail="规则已归档")
    rule.archived_at = utcnow()
    rule.enabled = False
    # 归档不删除既有证据（保留语义）
    await db.commit()
    await db.refresh(rule)
    return rule


async def restore_rule(db: AsyncSession, rule_id: int) -> LegacyUsageRule:
    rule = await get_rule_or_404(db, rule_id)
    if rule.archived_at is None:
        raise HTTPException(status_code=409, detail="规则未归档")
    rule.archived_at = None
    await db.commit()
    await db.refresh(rule)
    return rule


def rule_snapshot(rule: LegacyUsageRule) -> dict[str, Any]:
    """完整冻结快照（脱敏：无绝对路径、无密钥、无媒体内容）。

    worker 执行**只**依据本快照重建规则语义 —— 创建 run 后规则被修改/
    禁用/归档均不影响该 run 的匹配行为；实时 Rule 行仅用于展示与存在性审计。
    """
    return {
        "rule_id": rule.id,
        "rule_version": rule.version,
        "name": rule.name,
        "match_target": rule.match_target,
        "match_operator": rule.match_operator,
        "pattern": rule.pattern,
        "normalized_pattern": rule.normalized_pattern,
        "case_sensitive": rule.case_sensitive,
        "source_directory_id": rule.source_directory_id,
        "include_present_locations": rule.include_present_locations,
        "include_missing_locations": rule.include_missing_locations,
        "include_historical_locations": rule.include_historical_locations,
        "priority": rule.priority,
        "snapshot_hash": rule.snapshot_hash,
    }


# ============================ 匹配（preview / import 共用） ============================


def _location_statuses_for(rule: LegacyUsageRule) -> set[str]:
    scope = set()
    if rule.include_present_locations:
        scope.add("present")
    if rule.include_missing_locations:
        scope.add("missing")
    if rule.include_historical_locations:
        scope.add("historical")
    return scope


async def collect_matches(
    db: AsyncSession,
    *,
    source_directory_id: int | None,
    rule_ids: list[int] | None,
) -> tuple[list[LegacyUsageRule], dict[str, dict[str, Any]], dict[str, int], int]:
    """跑匹配管线（只读）。

    返回 (rules, matched_by_key, by_status_counts, scanned_location_count)。
    matched_by_key[evidence_key] = {asset_id, rule, location, matched_component,
    matched_target, evidence_type, observed_locations}。
    """
    base = select(LegacyUsageRule).where(
        LegacyUsageRule.enabled.is_(True), LegacyUsageRule.archived_at.is_(None)
    )
    if rule_ids:
        base = base.where(LegacyUsageRule.id.in_(rule_ids))
    rules = list((await db.scalars(base.order_by(LegacyUsageRule.priority))).all())
    if not rules:
        return [], {}, {}, 0

    loc_q = select(AssetLocation)
    if source_directory_id is not None:
        loc_q = loc_q.where(AssetLocation.source_root_id == source_directory_id)
    locations = list((await db.scalars(loc_q.order_by(AssetLocation.id))).all())

    matched: dict[str, dict[str, Any]] = {}
    # 统计口径（distinct）：同一 Location 被多规则/多 hit 命中只计一次
    matched_location_ids: set[int] = set()
    status_locations: dict[str, set[int]] = defaultdict(set)
    for loc in locations:
        for rule in rules:
            if (
                rule.source_directory_id is not None
                and loc.source_root_id != rule.source_directory_id
            ):
                continue
            if loc.location_status not in _location_statuses_for(rule):
                continue
            spec = RuleSpec(
                rule_id=rule.id,
                match_target=rule.match_target,
                match_operator=rule.match_operator,
                normalized_pattern=rule.normalized_pattern,
                case_sensitive=rule.case_sensitive,
            )
            for hit in match_rule(loc.relative_path, spec):
                # 与 worker 同口径：evidence_key 基于规则语义指纹（版本化幂等锚）
                key = compute_evidence_key(
                    rule.snapshot_hash, loc.asset_id, hit.match_target,
                    hit.matched_component,
                )
                matched_location_ids.add(loc.id)
                status_locations[loc.location_status].add(loc.id)
                if key in matched:
                    matched[key]["locations"].add(loc.id)
                else:
                    matched[key] = {
                        "asset_id": loc.asset_id,
                        "rule": rule,
                        "location": loc,
                        "matched_target": hit.match_target,
                        "matched_component": hit.matched_component,
                        "evidence_type": hit.evidence_type,
                        "locations": {loc.id},
                    }
    by_status = {k: len(v) for k, v in status_locations.items()}
    return rules, matched, by_status, len(locations)


async def preview_import(db: AsyncSession, req: ImportRequest) -> PreviewOut:
    """只读预览：零写入（不建 run、不建 evidence、不改状态）。"""
    rules, matched, by_status, scanned = await collect_matches(
        db, source_directory_id=req.source_directory_id, rule_ids=req.rule_ids
    )
    existing_keys = set()
    if matched:
        existing_keys = set(
            (
                await db.scalars(
                    select(LegacyUsageEvidence.evidence_key).where(
                        LegacyUsageEvidence.evidence_key.in_(list(matched.keys()))
                    )
                )
            ).all()
        )
    by_rule_locations: dict[str, set[int]] = defaultdict(set)
    samples: list[PreviewSampleOut] = []
    matched_assets = set()
    all_location_ids: set[int] = set()
    for key, hit in matched.items():
        by_rule_locations[str(hit["rule"].id)] |= hit["locations"]
        matched_assets.add(hit["asset_id"])
        all_location_ids |= hit["locations"]
        if len(samples) < PREVIEW_SAMPLE_MAX:
            samples.append(
                PreviewSampleOut(
                    asset_id=hit["asset_id"],
                    relative_path=hit["location"].relative_path[:200],
                    location_status=hit["location"].location_status,
                    rule_id=hit["rule"].id,
                    rule_name=hit["rule"].name,
                    matched_component=hit["matched_component"],
                    already_exists=key in existing_keys,
                )
            )
    return PreviewOut(
        # 统一口径：matched_location_count = 命中的不同 AssetLocation 数；
        # existing_evidence_count = 本次命中的不同既有 Evidence 数
        scanned_location_count=scanned,
        matched_location_count=len(all_location_ids),
        matched_asset_count=len(matched_assets),
        would_create_count=len([k for k in matched if k not in existing_keys]),
        existing_evidence_count=len(existing_keys),
        conflict_count=0,
        error_count=0,
        by_rule={k: len(v) for k, v in by_rule_locations.items()},
        by_location_status=by_status,
        samples=samples,
    )


# ============================ 正式导入（dispatch） ============================


async def request_import(db: AsyncSession, req: ImportRequest) -> LegacyUsageImportRun:
    rules, _, _, _ = await collect_matches(
        db, source_directory_id=req.source_directory_id, rule_ids=req.rule_ids
    )
    if not rules:
        raise HTTPException(status_code=409, detail="没有可用的启用规则")
    run = LegacyUsageImportRun(
        source_directory_id=req.source_directory_id,
        status="pending",
        dry_run=req.dry_run,
        rule_snapshot=[rule_snapshot(r) for r in rules],
        location_scope=sorted(
            {s for r in rules for s in _location_statuses_for(r)}
        ),
    )
    db.add(run)
    await db.commit()
    await db.refresh(run)
    try:
        task_id = enqueue_legacy_import(run.id)
    except Exception as exc:  # noqa: BLE001
        run.status = "failed"
        run.error_summary = f"入队失败: {exc}"[:2000]
        run.completed_at = utcnow()
        await db.commit()
        raise HTTPException(status_code=503, detail=f"无法入队导入任务: {exc}") from exc
    run.celery_task_id = task_id
    await db.commit()
    await db.refresh(run)
    return run


async def get_run_or_404(db: AsyncSession, run_id: int) -> LegacyUsageImportRun:
    run = await db.get(LegacyUsageImportRun, run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="导入运行不存在")
    return run


async def cancel_run(db: AsyncSession, run_id: int) -> LegacyUsageImportRun:
    run = await get_run_or_404(db, run_id)
    if run.status not in ("pending", "running"):
        raise HTTPException(status_code=409, detail="仅 pending/running 可取消")
    run.status = "cancelled"
    run.completed_at = utcnow()
    await db.commit()
    await db.refresh(run)
    return run


async def list_runs(
    db: AsyncSession, *, page: int, page_size: int
) -> tuple[list[LegacyUsageImportRun], int]:
    total = int(
        await db.scalar(select(func.count(LegacyUsageImportRun.id))) or 0
    )
    rows = (
        await db.scalars(
            select(LegacyUsageImportRun)
            .order_by(LegacyUsageImportRun.id.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
    ).all()
    return list(rows), total


# ============================ 审核工作流 ============================


def _add_event(
    db: AsyncSession,
    evidence_id: int,
    action: str,
    *,
    before_status: str | None,
    after_status: str | None,
    actor_label: str | None = None,
    note: str | None = None,
) -> None:
    db.add(
        LegacyUsageEvidenceEvent(
            evidence_id=evidence_id,
            action=action,
            before_status=before_status,
            after_status=after_status,
            actor_label=actor_label,
            note=note,
        )
    )


async def _get_evidence_locked(db: AsyncSession, evidence_id: int) -> LegacyUsageEvidence:
    ev = (
        await db.execute(
            select(LegacyUsageEvidence)
            .where(LegacyUsageEvidence.id == evidence_id)
            .with_for_update()
        )
    ).scalar_one_or_none()
    if ev is None:
        raise HTTPException(status_code=404, detail="证据不存在")
    return ev


async def get_evidence_or_404(db: AsyncSession, evidence_id: int) -> LegacyUsageEvidence:
    ev = await db.get(LegacyUsageEvidence, evidence_id)
    if ev is None:
        raise HTTPException(status_code=404, detail="证据不存在")
    return ev


_REVIEW_TRANSITIONS: dict[str, tuple[set[str], str, str]] = {
    # action -> (允许的前置状态集合, 目标状态, 事件动作)
    "accept": ({"pending"}, "accepted", "accepted"),
    "reject": ({"pending"}, "rejected", "rejected"),
    "mark-conflict": ({"pending", "accepted", "rejected"}, "conflict", "marked_conflict"),
    "reset": ({"accepted", "rejected", "conflict"}, "pending", "reset_to_pending"),
}


async def review_evidence(
    db: AsyncSession,
    evidence_id: int,
    action: str,
    *,
    actor_label: str | None,
    note: str | None,
    event_action_override: str | None = None,
) -> LegacyUsageEvidence:
    """单条审核动作（行锁 + 事件同事务）。

    accept 只代表"有效历史使用线索"——不确认次数/Shot/成片,
    不创建 FinalVideoUsage,不改变 confirmed 使用次数。
    """
    allowed, target, event_action = _REVIEW_TRANSITIONS[action]
    ev = await _get_evidence_locked(db, evidence_id)
    if ev.review_status not in allowed:
        raise HTTPException(
            status_code=409,
            detail=f"当前状态 {ev.review_status} 不允许 {action}",
        )
    before = ev.review_status
    ev.review_status = target
    ev.reviewed_at = utcnow() if target != "pending" else None
    if actor_label:
        ev.actor_label = actor_label
    if note:
        ev.review_note = note
    _add_event(
        db,
        ev.id,
        event_action_override or event_action,
        before_status=before,
        after_status=target,
        actor_label=actor_label,
        note=note,
    )
    await db.commit()
    await db.refresh(ev)
    return ev


async def bulk_review(
    db: AsyncSession,
    evidence_ids: list[int],
    action: str,  # "accept" | "reject"
    *,
    actor_label: str | None,
    note: str | None,
) -> BulkReviewOut:
    """批量审核（显式 id 列表；状态不符跳过；逐条事务化）。"""
    out = BulkReviewOut()
    event_action = "bulk_accepted" if action == "accept" else "bulk_rejected"
    for eid in evidence_ids:
        try:
            await review_evidence(
                db, eid, action,
                actor_label=actor_label, note=note,
                event_action_override=event_action,
            )
            out.succeeded += 1
        except HTTPException as exc:
            await db.rollback()
            if exc.status_code == 409:
                out.skipped += 1
                out.skipped_ids.append(eid)
            elif exc.status_code == 404:
                out.failed += 1
            else:
                raise
    return out


async def list_evidence_events(
    db: AsyncSession, evidence_id: int
) -> list[LegacyUsageEvidenceEvent]:
    await get_evidence_or_404(db, evidence_id)
    rows = (
        await db.scalars(
            select(LegacyUsageEvidenceEvent)
            .where(LegacyUsageEvidenceEvent.evidence_id == evidence_id)
            .order_by(LegacyUsageEvidenceEvent.id)
        )
    ).all()
    return list(rows)


# ============================ 查询 / 装配 ============================


async def list_evidence(
    db: AsyncSession,
    *,
    page: int,
    page_size: int,
    review_status: str | None,
    asset_id: int | None,
    rule_id: int | None,
) -> tuple[list[LegacyUsageEvidence], int]:
    conds = []
    if review_status is not None:
        conds.append(LegacyUsageEvidence.review_status == review_status)
    if asset_id is not None:
        conds.append(LegacyUsageEvidence.asset_id == asset_id)
    if rule_id is not None:
        conds.append(LegacyUsageEvidence.rule_id == rule_id)
    base = select(LegacyUsageEvidence)
    count_q = select(func.count(LegacyUsageEvidence.id))
    for c in conds:
        base = base.where(c)
        count_q = count_q.where(c)
    total = int(await db.scalar(count_q) or 0)
    rows = (
        await db.scalars(
            base.order_by(LegacyUsageEvidence.id.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
    ).all()
    return list(rows), total


async def evidences_to_out(
    db: AsyncSession, evidences: list[LegacyUsageEvidence]
) -> list[EvidenceOut]:
    """批量装配展示字段（asset/位置/规则/产品/正式血缘对照），固定查询数。"""
    if not evidences:
        return []
    asset_ids = {e.asset_id for e in evidences}
    loc_ids = {e.asset_location_id for e in evidences if e.asset_location_id is not None}
    rule_ids = {e.rule_id for e in evidences if e.rule_id is not None}

    assets = {
        a.id: a
        for a in (await db.scalars(select(Asset).where(Asset.id.in_(asset_ids)))).all()
    }
    locations: dict[int, AssetLocation] = {}
    root_names: dict[int, str] = {}
    if loc_ids:
        locations = {
            loc.id: loc
            for loc in (
                await db.scalars(
                    select(AssetLocation).where(AssetLocation.id.in_(loc_ids))
                )
            ).all()
        }
        root_ids = {loc.source_root_id for loc in locations.values()}
        root_names = {
            s.id: s.name
            for s in (
                await db.scalars(
                    select(SourceDirectory).where(SourceDirectory.id.in_(root_ids))
                )
            ).all()
        }
    rule_names: dict[int, str] = {}
    if rule_ids:
        rule_names = {
            r.id: r.name
            for r in (
                await db.scalars(
                    select(LegacyUsageRule).where(LegacyUsageRule.id.in_(rule_ids))
                )
            ).all()
        }
    # 产品名（素材主产品）
    product_names: dict[int, str] = {
        aid: name
        for aid, name in (
            await db.execute(
                select(Asset.id, Product.name)
                .join(Product, Product.id == Asset.primary_product_id)
                .where(Asset.id.in_(asset_ids), Asset.primary_product_id.is_not(None))
            )
        ).all()
    }
    # 正式血缘对照（证据绝不影响它们；此处只读展示）
    confirmed_counts: dict[int, int] = {
        aid: cnt
        for aid, cnt in (
            await db.execute(
                select(FinalVideoUsage.source_asset_id, func.count(FinalVideoUsage.id))
                .where(
                    FinalVideoUsage.source_asset_id.in_(asset_ids),
                    FinalVideoUsage.status == FinalVideoUsageStatus.CONFIRMED,
                )
                .group_by(FinalVideoUsage.source_asset_id)
            )
        ).all()
    }
    any_usage: set[int] = set(
        (
            await db.scalars(
                select(FinalVideoUsage.source_asset_id.distinct()).where(
                    FinalVideoUsage.source_asset_id.in_(asset_ids)
                )
            )
        ).all()
    )

    outs = []
    for e in evidences:
        out = EvidenceOut.model_validate(e)
        asset = assets.get(e.asset_id)
        if asset is not None:
            out.asset_filename = asset.filename
            out.asset_status = asset.status.value
            out.product_name = product_names.get(asset.id)
        loc = locations.get(e.asset_location_id) if e.asset_location_id else None
        if loc is not None:
            out.location_relative_path = loc.relative_path
            out.location_status = loc.location_status
            out.source_root_name = root_names.get(loc.source_root_id)
        if e.rule_id is not None:
            out.rule_name = rule_names.get(e.rule_id)
        elif e.rule_snapshot:
            out.rule_name = e.rule_snapshot.get("name")
        out.confirmed_usage_count = confirmed_counts.get(e.asset_id, 0)
        out.has_final_video_usage = e.asset_id in any_usage
        outs.append(out)
    return outs


def derive_legacy_state(counts: dict[str, int]) -> str:
    """Asset 派生历史使用状态（优先级 conflict > accepted > pending > rejected > none）。"""
    if counts.get("conflict", 0) > 0:
        return "legacy_evidence_conflict"
    if counts.get("accepted", 0) > 0:
        return "legacy_used_unknown"
    if counts.get("pending", 0) > 0:
        return "legacy_evidence_pending"
    if counts.get("rejected", 0) > 0:
        return "legacy_evidence_rejected"
    return "no_legacy_evidence"


async def legacy_counts_for_asset(db: AsyncSession, asset_id: int) -> dict[str, int]:
    rows = (
        await db.execute(
            select(LegacyUsageEvidence.review_status, func.count(LegacyUsageEvidence.id))
            .where(LegacyUsageEvidence.asset_id == asset_id)
            .group_by(LegacyUsageEvidence.review_status)
        )
    ).all()
    return {status: cnt for status, cnt in rows}


async def get_asset_legacy_summary(
    db: AsyncSession, asset_id: int
) -> AssetLegacySummaryOut:
    if await db.get(Asset, asset_id) is None:
        raise HTTPException(status_code=404, detail="素材不存在")
    counts = await legacy_counts_for_asset(db, asset_id)
    rows, _ = await list_evidence(
        db, page=1, page_size=50, review_status=None, asset_id=asset_id, rule_id=None
    )
    return AssetLegacySummaryOut(
        asset_id=asset_id,
        legacy_usage_state=derive_legacy_state(counts),
        accepted_count=counts.get("accepted", 0),
        pending_count=counts.get("pending", 0),
        rejected_count=counts.get("rejected", 0),
        conflict_count=counts.get("conflict", 0),
        evidences=await evidences_to_out(db, rows),
    )
