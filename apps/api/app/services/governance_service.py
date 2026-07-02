"""PR-A2 Gate B：入驻治理服务（完整度策略 / 完整度计算 / 入驻审核 / 混淆关系）。

原则：
- **两条轴**：Catalog 生命周期（draft/active/...）控制实体是否启用；Onboarding 状态控制资料
  是否准备充分。active ≠ approved；approved 不绕过生命周期；merged/archived 不可提交审核。
- 完整度**基于真实数据确定性计算**（同一输入同一结果；无时间/随机因素；不存神秘 AI 分数）；
  score 0-100 仅为展示指标，`complete` 由硬条件（全部适用检查通过且无 blocking）决定。
- 提交审核时后端**重新计算** readiness，绝不采信前端提交的分数；保存策略版本与快照。
- 混淆关系同层级、无方向（统一 小ID/大ID），创建前解析 merged canonical。
- 所有治理变更与 CatalogRevision **同事务**提交（见 revision_service）。
- 当前无用户认证：submitted_by/reviewed_by/actor_label 为非可信人工显示名。
"""

from __future__ import annotations

from typing import Any

from clipmind_shared.db.base import utcnow
from clipmind_shared.models import (
    ProductCatalogAlias,
    ProductCategory,
    ProductConfusionPair,
    ProductFamily,
    ProductOnboardingReview,
    ProductReadinessPolicy,
    ProductReferenceAsset,
    ProductSKU,
    ProductVariant,
)
from clipmind_shared.models.enums import (
    CONFUSION_SEVERITIES,
    ONBOARDING_STATUSES,
    REFERENCE_ANGLES,
    REFERENCE_HIDDEN_STATES,
    CatalogStatus,
)
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.services import revision_service
from app.services.attribute_service import list_definitions, list_values
from app.services.catalog_service import CatalogConflict, CatalogError

_TARGET_MODELS = {"family": ProductFamily, "variant": ProductVariant, "sku": ProductSKU}
_HIDDEN = (CatalogStatus.ARCHIVED, CatalogStatus.MERGED)
# 明确无效（数据错误）的参考图质量标记
_BAD_QUALITY = ("wrong_product", "duplicate")
_POLICY_INT_BOUNDS = {
    "min_reference_count": (0, 100),
    "min_identity_attribute_count": (0, 50),
}


async def _get_target(db: AsyncSession, level: str, node_id: int):
    model = _TARGET_MODELS.get(level)
    if model is None:
        raise CatalogError("治理目标只能是 family / variant / sku")
    node = await db.get(model, int(node_id))
    if node is None:
        raise CatalogError(f"{level} 不存在: {node_id}")
    return node


async def _target_category_id(db: AsyncSession, level: str, node) -> int | None:
    if level == "family":
        return node.category_id
    fam = await db.get(ProductFamily, node.family_id)
    return fam.category_id if fam else None


# --------------------------------------------------------------------------- #
# 完整度策略（Category 级，版本化，单 active）
# --------------------------------------------------------------------------- #


def _validate_policy_numbers(data: dict[str, Any]) -> None:
    for key, (lo, hi) in _POLICY_INT_BOUNDS.items():
        if key in data and data[key] is not None:
            v = int(data[key])
            if not (lo <= v <= hi):
                raise CatalogError(f"{key} 必须在 {lo}~{hi} 之间")
            data[key] = v
    angles = data.get("required_angles")
    if angles is not None:
        if not isinstance(angles, list):
            raise CatalogError("required_angles 必须是数组")
        bad = [a for a in angles if a not in REFERENCE_ANGLES]
        if bad:
            raise CatalogError(f"未知参考图角度: {bad}")
        data["required_angles"] = list(dict.fromkeys(angles))  # 去重保序


async def create_policy(db: AsyncSession, data: dict[str, Any]) -> ProductReadinessPolicy:
    category_id = data.get("category_id")
    if category_id is None:
        raise CatalogError("策略必须归属一个 Category")
    cat = await db.get(ProductCategory, int(category_id))
    if cat is None:
        raise CatalogError(f"category 不存在: {category_id}")
    _validate_policy_numbers(data)
    # 版本号：该 Category 现有最大版本 + 1（历史版本保留）
    max_ver = await db.scalar(
        select(func.max(ProductReadinessPolicy.version)).where(
            ProductReadinessPolicy.category_id == cat.id
        )
    )
    settings = get_settings()
    row = ProductReadinessPolicy(
        category_id=cat.id,
        version=int(max_ver or 0) + 1,
        name=(data.get("name") or f"策略 v{int(max_ver or 0) + 1}").strip()[:255],
        min_reference_count=int(
            data.get("min_reference_count", settings.readiness_default_min_references)
        ),
        required_angles=data.get("required_angles"),
        min_identity_attribute_count=int(
            data.get(
                "min_identity_attribute_count",
                settings.readiness_default_min_identity_attributes,
            )
        ),
        require_primary_reference=bool(
            data.get("require_primary_reference", settings.readiness_default_require_primary)
        ),
        require_name_en=bool(
            data.get("require_name_en", settings.readiness_default_require_name_en)
        ),
        require_alias=bool(data.get("require_alias", settings.readiness_default_require_alias)),
        require_sku_for_active_variant=bool(data.get("require_sku_for_active_variant", False)),
        status=CatalogStatus.DRAFT,
    )
    db.add(row)
    try:
        await db.flush()
        await revision_service.record(
            db, entity_type="readiness_policy", entity_id=row.id, action="create",
            after=revision_service.snapshot("readiness_policy", row),
            summary=f"创建完整度策略 v{row.version}",
        )
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        raise CatalogConflict("策略版本冲突") from exc
    await db.refresh(row)
    return row


async def activate_policy(
    db: AsyncSession, policy: ProductReadinessPolicy
) -> ProductReadinessPolicy:
    """激活该版本；同 Category 原 active 版本归档（同事务，同 correlation）。"""
    if policy.status == CatalogStatus.ARCHIVED:
        raise CatalogError("已归档策略不可激活，请创建新版本")
    corr = revision_service.new_correlation_id()
    current = (await db.execute(
        select(ProductReadinessPolicy).where(
            ProductReadinessPolicy.category_id == policy.category_id,
            ProductReadinessPolicy.status == CatalogStatus.ACTIVE,
            ProductReadinessPolicy.id != policy.id,
        )
    )).scalars().all()
    now = utcnow()
    for old in current:
        before = revision_service.snapshot("readiness_policy", old)
        old.status = CatalogStatus.ARCHIVED
        old.archived_at = now
        await revision_service.record(
            db, entity_type="readiness_policy", entity_id=old.id, action="archive",
            before=before, after=revision_service.snapshot("readiness_policy", old),
            summary=f"旧策略 v{old.version} 因新版本激活而归档", correlation_id=corr,
        )
    before = revision_service.snapshot("readiness_policy", policy)
    policy.status = CatalogStatus.ACTIVE
    policy.archived_at = None
    await revision_service.record(
        db, entity_type="readiness_policy", entity_id=policy.id, action="activate",
        before=before, after=revision_service.snapshot("readiness_policy", policy),
        summary=f"激活完整度策略 v{policy.version}", correlation_id=corr,
    )
    return await _commit(db, policy)


async def archive_policy(
    db: AsyncSession, policy: ProductReadinessPolicy
) -> ProductReadinessPolicy:
    before = revision_service.snapshot("readiness_policy", policy)
    policy.status = CatalogStatus.ARCHIVED
    policy.archived_at = utcnow()
    await revision_service.record(
        db, entity_type="readiness_policy", entity_id=policy.id, action="archive",
        before=before, after=revision_service.snapshot("readiness_policy", policy),
        summary=f"归档完整度策略 v{policy.version}",
    )
    return await _commit(db, policy)


async def list_policies(
    db: AsyncSession, *, category_id: int | None = None, include_archived: bool = False,
    limit: int = 50, offset: int = 0,
) -> tuple[list[ProductReadinessPolicy], int]:
    stmt = select(ProductReadinessPolicy)
    if category_id is not None:
        stmt = stmt.where(ProductReadinessPolicy.category_id == category_id)
    if not include_archived:
        stmt = stmt.where(ProductReadinessPolicy.status != CatalogStatus.ARCHIVED)
    total = await db.scalar(select(func.count()).select_from(stmt.subquery()))
    stmt = stmt.order_by(
        ProductReadinessPolicy.category_id.asc(), ProductReadinessPolicy.version.desc()
    ).limit(max(1, min(limit, 200))).offset(max(0, offset))
    rows = list((await db.execute(stmt)).scalars().all())
    return rows, int(total or 0)


async def active_policy_for(
    db: AsyncSession, category_id: int | None
) -> ProductReadinessPolicy | None:
    if category_id is None:
        return None
    return (await db.execute(
        select(ProductReadinessPolicy).where(
            ProductReadinessPolicy.category_id == category_id,
            ProductReadinessPolicy.status == CatalogStatus.ACTIVE,
        ).limit(1)
    )).scalar_one_or_none()


def _default_policy_view() -> dict[str, Any]:
    """系统默认策略（未配置时的安全兜底；来自 Settings，可经环境变量调整）。"""
    s = get_settings()
    return {
        "id": None,
        "version": 0,  # 0 = 系统默认策略（无 DB 行）
        "min_reference_count": s.readiness_default_min_references,
        "required_angles": [],
        "min_identity_attribute_count": s.readiness_default_min_identity_attributes,
        "require_primary_reference": s.readiness_default_require_primary,
        "require_name_en": s.readiness_default_require_name_en,
        "require_alias": s.readiness_default_require_alias,
        "require_sku_for_active_variant": False,
    }


def _policy_view(p: ProductReadinessPolicy | None) -> dict[str, Any]:
    if p is None:
        return _default_policy_view()
    return {
        "id": p.id,
        "version": p.version,
        "min_reference_count": p.min_reference_count,
        "required_angles": p.required_angles or [],
        "min_identity_attribute_count": p.min_identity_attribute_count,
        "require_primary_reference": p.require_primary_reference,
        "require_name_en": p.require_name_en,
        "require_alias": p.require_alias,
        "require_sku_for_active_variant": p.require_sku_for_active_variant,
    }


# --------------------------------------------------------------------------- #
# 完整度计算（确定性，真实数据）
# --------------------------------------------------------------------------- #


async def compute_readiness(db: AsyncSession, level: str, node_id: int) -> dict[str, Any]:
    node = await _get_target(db, level, node_id)
    category_id = await _target_category_id(db, level, node)
    policy_row = await active_policy_for(db, category_id)
    policy = _policy_view(policy_row)

    checks: list[dict[str, Any]] = []
    blocking: list[dict[str, Any]] = []

    def check(key: str, passed: bool, current: Any, required: Any) -> None:
        checks.append({
            "key": key, "passed": bool(passed), "current": current, "required": required,
        })

    # ---- blocking：明确错误（高分也不能忽略）----
    if node.status == CatalogStatus.MERGED:
        blocking.append({"key": "target_merged", "detail": "该实体已合并，不可入驻"})
    if node.status == CatalogStatus.ARCHIVED:
        blocking.append({"key": "target_archived", "detail": "该实体已归档，不可入驻"})

    # 参考图集合（活动 = 非 rejected/archived）
    col = getattr(ProductReferenceAsset, f"{level}_id")
    refs = (await db.execute(
        select(ProductReferenceAsset).where(col == node.id)
    )).scalars().all()
    active_refs = [r for r in refs if r.state not in REFERENCE_HIDDEN_STATES]
    bad_refs = [
        r for r in refs
        if r.state == "rejected" or r.quality_status in _BAD_QUALITY
    ]
    if bad_refs:
        blocking.append({
            "key": "invalid_references",
            "detail": f"存在 {len(bad_refs)} 张被标记无效的参考图（错产品/重复/已拒绝），请处理",
        })

    # ---- 基础检查 ----
    check("name_zh", bool((node.name_zh or "").strip()), bool((node.name_zh or "").strip()), True)
    check("category", category_id is not None, category_id is not None, True)
    if policy["require_name_en"]:
        has_en = bool((getattr(node, "name_en", None) or "").strip())
        check("name_en", has_en, has_en, True)
    if policy["require_alias"]:
        alias_col = getattr(ProductCatalogAlias, f"{level}_id")
        alias_cnt = await db.scalar(
            select(func.count()).select_from(ProductCatalogAlias).where(alias_col == node.id)
        )
        check("alias", int(alias_cnt or 0) > 0, int(alias_cnt or 0), 1)

    # ---- 动态属性 ----
    defs, _ = await list_definitions(
        db, category_id=category_id, include_global=True,
        status=CatalogStatus.ACTIVE, limit=500,
    )
    if category_id is None:
        # 无分类目标只适用全局属性定义（list_definitions 在 category_id=None 时不加过滤）
        defs = [d for d in defs if d.category_id is None]
    values = await list_values(db, level, node.id)
    filled_ids = {v.definition_id for v in values}
    required_defs = [d for d in defs if d.required]
    missing_required = [d for d in required_defs if d.id not in filled_ids]
    check(
        "required_attributes",
        not missing_required,
        len(required_defs) - len(missing_required),
        len(required_defs),
    )
    identity_defs = [d for d in defs if d.identity_relevant]
    identity_filled = sum(1 for d in identity_defs if d.id in filled_ids)
    check(
        "identity_attributes",
        identity_filled >= policy["min_identity_attribute_count"],
        identity_filled,
        policy["min_identity_attribute_count"],
    )

    # ---- 参考图 ----
    check(
        "minimum_references",
        len(active_refs) >= policy["min_reference_count"],
        len(active_refs),
        policy["min_reference_count"],
    )
    if policy["require_primary_reference"]:
        has_primary = any(r.is_primary for r in active_refs)
        check("primary_reference", has_primary, has_primary, True)
    if policy["required_angles"]:
        covered = {r.angle for r in active_refs}
        missing_angles = [a for a in policy["required_angles"] if a not in covered]
        check(
            "required_angles",
            not missing_angles,
            sorted(covered & set(policy["required_angles"])),
            policy["required_angles"],
        )

    # ---- 层级 ----
    parent_ok = True
    if level == "family":
        cat = await db.get(ProductCategory, category_id) if category_id else None
        parent_ok = bool(cat and cat.status == CatalogStatus.ACTIVE)
    elif level == "variant":
        fam = await db.get(ProductFamily, node.family_id)
        parent_ok = bool(fam and fam.status == CatalogStatus.ACTIVE)
    else:  # sku
        fam = await db.get(ProductFamily, node.family_id)
        parent_ok = bool(fam and fam.status == CatalogStatus.ACTIVE)
        if parent_ok and node.variant_id is not None:
            var = await db.get(ProductVariant, node.variant_id)
            parent_ok = bool(var and var.status == CatalogStatus.ACTIVE)
    check("parent_active", parent_ok, parent_ok, True)

    if policy["require_sku_for_active_variant"] and level == "variant":
        sku_cnt = await db.scalar(
            select(func.count()).select_from(ProductSKU).where(
                ProductSKU.variant_id == node.id, ProductSKU.status.notin_(_HIDDEN)
            )
        )
        check("sku_for_variant", int(sku_cnt or 0) > 0, int(sku_cnt or 0), 1)

    # ---- 汇总（确定性：仅由上述真实数据决定）----
    passed = sum(1 for c in checks if c["passed"])
    score = round(100 * passed / len(checks)) if checks else 0
    missing_items = [
        {"key": c["key"], "current": c["current"], "required": c["required"]}
        for c in checks if not c["passed"]
    ]
    complete = (not missing_items) and (not blocking)

    return {
        "target_level": level,
        "target_id": node.id,
        "score": score,
        "complete": complete,
        "policy_id": policy["id"],
        "policy_version": policy["version"],
        "checks": checks,
        "missing_items": missing_items,
        "blocking_items": blocking,
        "evaluated_at": utcnow().isoformat(),
        # 诚实声明：完整度是资料统计，不代表 AI 已能识别该产品
        "ai_recognition_enabled": False,
    }


# --------------------------------------------------------------------------- #
# 入驻审核（每目标一条当前记录；历史入 CatalogRevision）
# --------------------------------------------------------------------------- #


async def get_onboarding(
    db: AsyncSession, level: str, node_id: int
) -> ProductOnboardingReview | None:
    await _get_target(db, level, node_id)
    col = getattr(ProductOnboardingReview, f"{level}_id")
    return (await db.execute(
        select(ProductOnboardingReview).where(col == node_id).limit(1)
    )).scalar_one_or_none()


async def _ensure_row(db: AsyncSession, level: str, node_id: int) -> ProductOnboardingReview:
    row = await get_onboarding(db, level, node_id)
    if row is None:
        row = ProductOnboardingReview(status="incomplete")
        setattr(row, f"{level}_id", int(node_id))
        db.add(row)
        await db.flush()
    return row


async def submit_review(
    db: AsyncSession, level: str, node_id: int, *, submitted_by: str | None = None
) -> ProductOnboardingReview:
    """提交审核：后端重算 readiness；不完整则拒绝（422 带缺失项），不采信前端分数。"""
    node = await _get_target(db, level, node_id)
    if node.status in _HIDDEN:
        raise CatalogError("已合并/归档实体不可提交入驻审核")
    readiness = await compute_readiness(db, level, node_id)
    if not readiness["complete"]:
        missing = "、".join(m["key"] for m in readiness["missing_items"][:8])
        blocking = "、".join(b["key"] for b in readiness["blocking_items"][:8])
        parts = []
        if missing:
            parts.append(f"缺失: {missing}")
        if blocking:
            parts.append(f"阻塞: {blocking}")
        raise CatalogError(f"资料未达当前策略要求，无法提交审核（{'；'.join(parts)}）")
    row = await _ensure_row(db, level, node_id)
    if row.status == "approved":
        raise CatalogError("该产品已通过审核；如需重审请先退回修改")
    before = revision_service.snapshot("onboarding_review", row)
    row.status = "ready_for_review"
    row.policy_id = readiness["policy_id"]
    row.policy_version = readiness["policy_version"]
    row.readiness_score = readiness["score"]
    row.readiness_snapshot = {
        "checks": readiness["checks"],
        "missing_items": readiness["missing_items"],
        "blocking_items": readiness["blocking_items"],
        "score": readiness["score"],
        "policy_version": readiness["policy_version"],
    }
    row.submitted_at = utcnow()
    row.submitted_by = (submitted_by or None)
    await revision_service.record(
        db, entity_type="onboarding_review", entity_id=row.id, action="submit_review",
        before=before, after=revision_service.snapshot("onboarding_review", row),
        summary=f"{level} #{node_id} 提交入驻审核（score={row.readiness_score}）",
    )
    return await _commit(db, row)


async def _transition(
    db: AsyncSession, level: str, node_id: int, *,
    to_status: str, action: str, allowed_from: tuple[str, ...],
    note: str | None, reviewed_by: str | None, summary: str,
) -> ProductOnboardingReview:
    assert to_status in ONBOARDING_STATUSES
    await _get_target(db, level, node_id)
    row = await get_onboarding(db, level, node_id)
    if row is None:
        raise CatalogError("该产品尚未提交入驻审核")
    if allowed_from and row.status not in allowed_from:
        raise CatalogError(f"当前状态 {row.status} 不允许该操作")
    before = revision_service.snapshot("onboarding_review", row)
    row.status = to_status
    row.reviewed_at = utcnow()
    if note is not None:
        row.reviewer_note = note[:2000]
    row.reviewed_by = (reviewed_by or None)
    await revision_service.record(
        db, entity_type="onboarding_review", entity_id=row.id, action=action,
        before=before, after=revision_service.snapshot("onboarding_review", row),
        summary=summary,
    )
    return await _commit(db, row)


async def approve(db, level, node_id, *, note=None, reviewed_by=None):
    return await _transition(
        db, level, node_id, to_status="approved", action="approve",
        allowed_from=("ready_for_review",), note=note, reviewed_by=reviewed_by,
        summary=f"{level} #{node_id} 入驻审核通过",
    )


async def request_changes(db, level, node_id, *, note=None, reviewed_by=None):
    return await _transition(
        db, level, node_id, to_status="needs_changes", action="request_changes",
        allowed_from=("ready_for_review",), note=note, reviewed_by=reviewed_by,
        summary=f"{level} #{node_id} 审核退回需修改",
    )


async def block(db, level, node_id, *, note=None, reviewed_by=None):
    # 任意未归档状态 → blocked（目标归档/合并本身由 submit 守卫；block 用于明确错误）
    return await _transition(
        db, level, node_id, to_status="blocked", action="block",
        allowed_from=(), note=note, reviewed_by=reviewed_by,
        summary=f"{level} #{node_id} 被标记为 blocked",
    )


async def list_onboarding(
    db: AsyncSession, *, status: str | None = None, level: str | None = None,
    limit: int = 50, offset: int = 0,
) -> tuple[list[ProductOnboardingReview], int]:
    stmt = select(ProductOnboardingReview)
    if status:
        if status not in ONBOARDING_STATUSES:
            raise CatalogError(f"未知入驻状态: {status}")
        stmt = stmt.where(ProductOnboardingReview.status == status)
    if level:
        if level not in _TARGET_MODELS:
            raise CatalogError("level 只能是 family / variant / sku")
        stmt = stmt.where(getattr(ProductOnboardingReview, f"{level}_id").isnot(None))
    total = await db.scalar(select(func.count()).select_from(stmt.subquery()))
    stmt = stmt.order_by(ProductOnboardingReview.updated_at.desc())
    stmt = stmt.limit(max(1, min(limit, 200))).offset(max(0, offset))
    rows = list((await db.execute(stmt)).scalars().all())
    return rows, int(total or 0)


# --------------------------------------------------------------------------- #
# 易混淆产品关系（同层级、无方向）
# --------------------------------------------------------------------------- #


async def _canonical_id(db: AsyncSession, level: str, node_id: int) -> int:
    """沿 merged_into_id 解析 canonical（≤20 跳，防环）。返回 canonical id。"""
    model = _TARGET_MODELS[level]
    obj = await db.get(model, int(node_id))
    if obj is None:
        raise CatalogError(f"{level} 不存在: {node_id}")
    seen: set[int] = set()
    hops = 0
    while getattr(obj, "merged_into_id", None) is not None and hops < 20:
        if obj.id in seen:
            break
        seen.add(obj.id)
        nxt = await db.get(model, obj.merged_into_id)
        if nxt is None:
            break
        obj = nxt
        hops += 1
    return obj.id


def _validate_features(v: Any) -> list[dict[str, Any]]:
    """校验人工区分特征结构（受控条目列表；不接受大文本单字段）。"""
    if v is None:
        return []
    if not isinstance(v, list):
        raise CatalogError("distinguishing_features 必须是条目数组")
    if len(v) > 40:
        raise CatalogError("区分特征条目过多（≤40）")
    out: list[dict[str, Any]] = []
    for item in v:
        if not isinstance(item, dict):
            raise CatalogError("区分特征条目必须是对象")
        feature = str(item.get("feature") or "").strip()
        if not feature:
            raise CatalogError("每条区分特征必须有 feature 名称")
        out.append({
            "feature": feature[:100],
            "left_value": str(item.get("left_value") or "")[:300],
            "right_value": str(item.get("right_value") or "")[:300],
            "visible_in_reference": bool(item.get("visible_in_reference", False)),
            "identity_relevant": bool(item.get("identity_relevant", False)),
        })
    return out


async def create_pair(db: AsyncSession, data: dict[str, Any]) -> ProductConfusionPair:
    level = data.get("target_level")
    if level not in _TARGET_MODELS:
        raise CatalogError("混淆关系只支持同层级 family/variant/sku")
    a = await _canonical_id(db, level, int(data["left_target_id"]))
    b = await _canonical_id(db, level, int(data["right_target_id"]))
    if a == b:
        raise CatalogError("不允许自己与自己组成混淆关系（含合并到同一 canonical 的情况）")
    # archived 实体不可建新关系
    model = _TARGET_MODELS[level]
    for nid in (a, b):
        node = await db.get(model, nid)
        if node.status == CatalogStatus.ARCHIVED:
            raise CatalogError(f"{level} #{nid} 已归档，不可创建混淆关系")
    left, right = (a, b) if a < b else (b, a)
    severity = (data.get("severity") or "medium").strip().lower()
    if severity not in CONFUSION_SEVERITIES:
        raise CatalogError(f"未知严重程度: {severity}")
    row = ProductConfusionPair(
        target_level=level,
        left_target_id=left,
        right_target_id=right,
        severity=severity,
        reason=(data.get("reason") or None),
        distinguishing_features=_validate_features(data.get("distinguishing_features")) or None,
        review_note=(data.get("review_note") or None),
        status="active",
    )
    db.add(row)
    try:
        await db.flush()
        await revision_service.record(
            db, entity_type="confusion_pair", entity_id=row.id, action="create",
            after=revision_service.snapshot("confusion_pair", row),
            summary=f"创建 {level} 混淆关系 #{left}↔#{right}",
        )
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        raise CatalogConflict("该混淆关系已存在（无方向，反向亦视为重复）") from exc
    await db.refresh(row)
    return row


async def update_pair(
    db: AsyncSession, pair: ProductConfusionPair, data: dict[str, Any]
) -> ProductConfusionPair:
    before = revision_service.snapshot("confusion_pair", pair)
    if "severity" in data and data["severity"] is not None:
        sev = str(data["severity"]).strip().lower()
        if sev not in CONFUSION_SEVERITIES:
            raise CatalogError(f"未知严重程度: {sev}")
        pair.severity = sev
    if "reason" in data:
        pair.reason = data["reason"] or None
    if "distinguishing_features" in data:
        pair.distinguishing_features = _validate_features(data["distinguishing_features"]) or None
    if "review_note" in data:
        pair.review_note = data["review_note"] or None
    await revision_service.record(
        db, entity_type="confusion_pair", entity_id=pair.id, action="update",
        before=before, after=revision_service.snapshot("confusion_pair", pair),
        summary=f"更新混淆关系 #{pair.id}",
    )
    return await _commit(db, pair)


async def archive_pair(db: AsyncSession, pair: ProductConfusionPair) -> ProductConfusionPair:
    before = revision_service.snapshot("confusion_pair", pair)
    pair.status = "archived"
    pair.archived_at = utcnow()
    await revision_service.record(
        db, entity_type="confusion_pair", entity_id=pair.id, action="archive",
        before=before, after=revision_service.snapshot("confusion_pair", pair),
        summary=f"归档混淆关系 #{pair.id}",
    )
    return await _commit(db, pair)


async def restore_pair(db: AsyncSession, pair: ProductConfusionPair) -> ProductConfusionPair:
    before = revision_service.snapshot("confusion_pair", pair)
    pair.status = "active"
    pair.archived_at = None
    await revision_service.record(
        db, entity_type="confusion_pair", entity_id=pair.id, action="restore",
        before=before, after=revision_service.snapshot("confusion_pair", pair),
        summary=f"恢复混淆关系 #{pair.id}",
    )
    return await _commit(db, pair)


async def list_pairs(
    db: AsyncSession, *, target_level: str | None = None, target_id: int | None = None,
    include_archived: bool = False, limit: int = 50, offset: int = 0,
) -> tuple[list[ProductConfusionPair], int]:
    stmt = select(ProductConfusionPair)
    if target_level:
        if target_level not in _TARGET_MODELS:
            raise CatalogError("target_level 只能是 family / variant / sku")
        stmt = stmt.where(ProductConfusionPair.target_level == target_level)
    if target_id is not None:
        stmt = stmt.where(
            (ProductConfusionPair.left_target_id == target_id)
            | (ProductConfusionPair.right_target_id == target_id)
        )
    if not include_archived:
        stmt = stmt.where(ProductConfusionPair.status != "archived")
    total = await db.scalar(select(func.count()).select_from(stmt.subquery()))
    stmt = stmt.order_by(ProductConfusionPair.id.desc())
    stmt = stmt.limit(max(1, min(limit, 200))).offset(max(0, offset))
    rows = list((await db.execute(stmt)).scalars().all())
    return rows, int(total or 0)


async def pair_sides(
    db: AsyncSession, pair: ProductConfusionPair
) -> dict[str, dict[str, Any] | None]:
    """返回混淆对两侧节点的展示信息（供 UI 跳转与显示名称）。"""
    model = _TARGET_MODELS[pair.target_level]
    out: dict[str, dict[str, Any] | None] = {}
    for side, nid in (("left", pair.left_target_id), ("right", pair.right_target_id)):
        node = await db.get(model, nid)
        out[side] = None if node is None else {
            "id": node.id,
            "name_zh": node.name_zh,
            "code": getattr(node, "code", None),
            "status": node.status,
        }
    return out


async def _commit(db: AsyncSession, obj):
    try:
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        raise CatalogConflict("唯一约束冲突") from exc
    await db.refresh(obj)
    return obj
