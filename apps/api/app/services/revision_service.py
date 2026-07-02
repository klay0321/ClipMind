"""PR-A2 Gate B：目录变更历史（CatalogRevision，append-only）。

- `record()` 只 `db.add`（**不 commit**）：由调用方在同一事务内提交业务变更与 revision，
  业务失败整体回滚，绝不单独留下成功 revision。
- `snapshot()` 按实体类型的**字段白名单**提取脱敏业务数据：
  不含图片二进制 / 绝对路径 / 上传临时路径 / API Key / 环境变量；
  参考图仅保存角度、状态、质量、sha256 等受控元数据（不含 image_path/原始文件名）。
- 字符串统一截断（防大字段）；Decimal/date/datetime 序列化为字符串。
- revision_number 取自专用序列 `catalog_revision_seq`（单调递增）。
- 只读查询；**无 update/delete 接口**。actor_label 为非可信显示名。
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from clipmind_shared.models import CatalogRevision
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

# 每类实体允许进入 before/after 的业务字段白名单（勿加路径/文件名/密钥类字段）
_SANITIZED_FIELDS: dict[str, tuple[str, ...]] = {
    "category": ("code", "name_zh", "name_en", "description", "status", "sort_order"),
    "family": (
        "code", "category_id", "name_zh", "name_en", "description",
        "status", "merged_into_id", "legacy_product_id",
    ),
    "variant": ("code", "family_id", "name_zh", "name_en", "description", "status",
                "merged_into_id"),
    "sku": ("code", "family_id", "variant_id", "sku_code", "name_zh", "name_en",
            "status", "merged_into_id"),
    "alias": ("alias", "language", "alias_type", "is_primary",
              "category_id", "family_id", "variant_id", "sku_id"),
    "attribute_definition": (
        "key", "category_id", "name_zh", "name_en", "value_type", "unit",
        "allowed_values", "required", "searchable", "identity_relevant",
        "multi_value", "sort_order", "status",
    ),
    "attribute_value": (
        "definition_id", "family_id", "variant_id", "sku_id",
        "value_text", "value_number", "value_boolean", "value_json", "value_date", "unit",
    ),
    # 参考图：仅受控元数据（明确不含 image_path / thumbnail_path / original_filename）
    "reference_asset": (
        "family_id", "variant_id", "sku_id", "angle", "state", "quality_status",
        "is_primary", "sort_order", "description", "media_type", "sha256",
    ),
    "readiness_policy": (
        "category_id", "version", "name", "min_reference_count", "required_angles",
        "min_identity_attribute_count", "require_primary_reference", "require_name_en",
        "require_alias", "require_sku_for_active_variant", "status",
    ),
    "onboarding_review": (
        "family_id", "variant_id", "sku_id", "status", "policy_id", "policy_version",
        "readiness_score", "reviewer_note", "submitted_by", "reviewed_by",
    ),
    "confusion_pair": (
        "target_level", "left_target_id", "right_target_id", "severity", "reason",
        "distinguishing_features", "review_note", "status",
    ),
}

_MAX_STR = 300  # 单字段字符串截断上限


def new_correlation_id() -> str:
    """同一业务事务共用一个 correlation_id。"""
    return uuid.uuid4().hex


def _clean(v: Any, depth: int = 0) -> Any:
    """递归脱敏/序列化：截断长字符串，非 JSON 原生类型转字符串，限制嵌套深度。"""
    if depth > 4:
        return "..."
    if v is None or isinstance(v, bool | int | float):
        return v
    if isinstance(v, str):
        return v[:_MAX_STR]
    if isinstance(v, Decimal):
        return str(v)
    if isinstance(v, date | datetime):
        return v.isoformat()
    if isinstance(v, dict):
        return {str(k)[:64]: _clean(x, depth + 1) for k, x in list(v.items())[:40]}
    if isinstance(v, list | tuple):
        return [_clean(x, depth + 1) for x in list(v)[:40]]
    # 枚举等其它类型 → 字符串
    return str(v)[:_MAX_STR]


def snapshot(entity_type: str, obj: Any) -> dict[str, Any]:
    """按白名单提取实体的脱敏业务字段快照。"""
    fields = _SANITIZED_FIELDS.get(entity_type, ())
    out: dict[str, Any] = {}
    for f in fields:
        if hasattr(obj, f):
            out[f] = _clean(getattr(obj, f))
    return out


async def record(
    db: AsyncSession,
    *,
    entity_type: str,
    entity_id: int,
    action: str,
    before: dict[str, Any] | None = None,
    after: dict[str, Any] | None = None,
    summary: str | None = None,
    correlation_id: str | None = None,
    actor_label: str | None = None,
) -> None:
    """追加一条变更事件到当前 Session（不 commit，由业务事务统一提交）。"""
    num = await db.scalar(text("SELECT nextval('catalog_revision_seq')"))
    row = CatalogRevision(
        revision_number=int(num),
        entity_type=entity_type[:32],
        entity_id=int(entity_id),
        action=action[:32],
        before_data=_clean(before) if before else None,
        after_data=_clean(after) if after else None,
        change_summary=(summary or "")[:500] or None,
        correlation_id=(correlation_id or new_correlation_id())[:36],
        actor_label=(actor_label or None),
    )
    db.add(row)


# --------------------------------------------------------------------------- #
# 只读查询（无修改接口）
# --------------------------------------------------------------------------- #


async def list_revisions(
    db: AsyncSession,
    *,
    entity_type: str | None = None,
    entity_id: int | None = None,
    action: str | None = None,
    created_from: datetime | None = None,
    created_to: datetime | None = None,
    limit: int = 50,
    offset: int = 0,
) -> tuple[list[CatalogRevision], int]:
    from sqlalchemy import func

    stmt = select(CatalogRevision)
    if entity_type:
        stmt = stmt.where(CatalogRevision.entity_type == entity_type)
    if entity_id is not None:
        stmt = stmt.where(CatalogRevision.entity_id == entity_id)
    if action:
        stmt = stmt.where(CatalogRevision.action == action)
    if created_from is not None:
        stmt = stmt.where(CatalogRevision.created_at >= created_from)
    if created_to is not None:
        stmt = stmt.where(CatalogRevision.created_at <= created_to)
    total = await db.scalar(select(func.count()).select_from(stmt.subquery()))
    stmt = stmt.order_by(CatalogRevision.revision_number.desc())
    stmt = stmt.limit(max(1, min(limit, 200))).offset(max(0, offset))
    rows = list((await db.execute(stmt)).scalars().all())
    return rows, int(total or 0)


async def get_revision(db: AsyncSession, rev_id: int) -> CatalogRevision | None:
    return await db.get(CatalogRevision, rev_id)
