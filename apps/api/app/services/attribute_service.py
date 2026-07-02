"""PR-A2 Gate A：动态产品属性服务（定义 + 受约束的值 + profile 聚合）。

- 属性定义按 Category 动态创建；`value_type` 取白名单，enum/multi_enum 须带 `allowed_values`。
- 属性值按 `definition.value_type` 落对应 typed column，强类型校验；enum 须命中 allowed_values；
  跨 Category 拒绝；Variant/SKU 继承 Family 的 Category。
- 值 upsert 走「归档旧活动值 + 插新值」保留历史；同目标同定义至多一个活动值。
- profile 为**只读真实统计**（属性完整度 / 参考图数量），**不代表 AI 已能识别**。
- validation_rules 仅白名单键（min/max/max_length/pattern），绝不执行用户表达式/代码。
"""

from __future__ import annotations

import re
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Any

from clipmind_shared.db.base import utcnow
from clipmind_shared.models import (
    ProductAttributeDefinition,
    ProductAttributeValue,
    ProductCategory,
    ProductFamily,
    ProductReferenceAsset,
    ProductSKU,
    ProductVariant,
)
from clipmind_shared.models.enums import (
    ATTRIBUTE_ENUM_TYPES,
    ATTRIBUTE_VALUE_TYPES,
    REFERENCE_HIDDEN_STATES,
    CatalogStatus,
)
from clipmind_shared.review import normalize_name
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.services import revision_service
from app.services.catalog_service import CatalogConflict, CatalogError

_VALIDATION_KEYS = {"min", "max", "max_length", "pattern"}
_TARGET_MODELS = {"family": ProductFamily, "variant": ProductVariant, "sku": ProductSKU}


def _norm(s: str | None) -> str:
    return normalize_name((s or "").strip())


def _slug_key(text: str) -> str:
    s = normalize_name(text)
    s = re.sub(r"[^\w一-鿿]+", "_", s, flags=re.UNICODE).strip("_")
    return s[:48] or "attr"


# --------------------------------------------------------------------------- #
# 属性定义
# --------------------------------------------------------------------------- #


def _validate_definition_shape(data: dict[str, Any]) -> None:
    vt = (data.get("value_type") or "").strip()
    if vt not in ATTRIBUTE_VALUE_TYPES:
        raise CatalogError(f"未知 value_type: {vt}（须为 {', '.join(ATTRIBUTE_VALUE_TYPES)}）")
    allowed = data.get("allowed_values")
    if vt in ATTRIBUTE_ENUM_TYPES:
        if not isinstance(allowed, list) or not allowed:
            raise CatalogError(f"{vt} 必须提供非空 allowed_values 数组")
        if any(not isinstance(x, str) or not x.strip() for x in allowed):
            raise CatalogError("allowed_values 必须为非空字符串数组")
    elif allowed not in (None, [], {}):
        raise CatalogError("仅 enum / multi_enum 可设置 allowed_values")
    if vt == "measurement" and not (data.get("unit") or "").strip():
        raise CatalogError("measurement 必须提供 unit（度量单位）")
    rules = data.get("validation_rules")
    if rules is not None:
        if not isinstance(rules, dict):
            raise CatalogError("validation_rules 必须为对象")
        bad = set(rules) - _VALIDATION_KEYS
        if bad:
            raise CatalogError(f"validation_rules 含未白名单键: {', '.join(sorted(bad))}")


async def _key_scope_check(
    db: AsyncSession, category_id: int | None, normalized_key: str, exclude_id: int | None = None
) -> None:
    stmt = select(ProductAttributeDefinition.id).where(
        ProductAttributeDefinition.normalized_key == normalized_key
    )
    stmt = stmt.where(
        ProductAttributeDefinition.category_id == category_id
        if category_id is not None
        else ProductAttributeDefinition.category_id.is_(None)
    )
    if exclude_id is not None:
        stmt = stmt.where(ProductAttributeDefinition.id != exclude_id)
    if await db.scalar(stmt.limit(1)) is not None:
        raise CatalogConflict("同一 Category 内该属性 key 已存在")


async def create_definition(db: AsyncSession, data: dict[str, Any]) -> ProductAttributeDefinition:
    name_zh = (data.get("name_zh") or "").strip()
    if not name_zh:
        raise CatalogError("中文名称必填")
    _validate_definition_shape(data)
    category_id = data.get("category_id")
    if category_id is not None and await db.get(ProductCategory, int(category_id)) is None:
        raise CatalogError(f"category 不存在: {category_id}")
    key = (data.get("key") or "").strip() or _slug_key(name_zh)
    nkey = _norm(key)
    await _key_scope_check(db, category_id, nkey)
    row = ProductAttributeDefinition(
        category_id=category_id,
        key=key,
        normalized_key=nkey,
        name_zh=name_zh,
        name_en=(data.get("name_en") or None),
        description=(data.get("description") or None),
        value_type=data["value_type"].strip(),
        unit=((data.get("unit") or "").strip() or None),
        allowed_values=(data.get("allowed_values") or None),
        validation_rules=(data.get("validation_rules") or None),
        required=bool(data.get("required")),
        searchable=bool(data.get("searchable")),
        identity_relevant=bool(data.get("identity_relevant")),
        multi_value=bool(data.get("multi_value") or data.get("value_type") == "multi_enum"),
        sort_order=int(data.get("sort_order") or 0),
        status=CatalogStatus.DRAFT,
    )
    return await _add(db, row, rev_type="attribute_definition", rev_summary="创建属性定义")


async def list_definitions(
    db: AsyncSession, *, category_id: int | None = None, include_global: bool = True,
    status: CatalogStatus | None = None, searchable: bool | None = None,
    identity_relevant: bool | None = None, include_archived: bool = False,
    q: str | None = None, limit: int = 100, offset: int = 0,
) -> tuple[list[ProductAttributeDefinition], int]:
    m = ProductAttributeDefinition
    stmt = select(m)
    if category_id is not None:
        stmt = (
            stmt.where((m.category_id == category_id) | m.category_id.is_(None))
            if include_global
            else stmt.where(m.category_id == category_id)
        )
    if status is not None:
        stmt = stmt.where(m.status == status)
    elif not include_archived:
        stmt = stmt.where(m.status != CatalogStatus.ARCHIVED)
    if searchable is not None:
        stmt = stmt.where(m.searchable.is_(searchable))
    if identity_relevant is not None:
        stmt = stmt.where(m.identity_relevant.is_(identity_relevant))
    if q:
        like = f"%{q.strip()}%"
        stmt = stmt.where(
            func.lower(m.name_zh).like(func.lower(like)) | m.key.like(like)
        )
    total = await db.scalar(select(func.count()).select_from(stmt.subquery()))
    stmt = stmt.order_by(m.sort_order.asc(), m.id.asc()).limit(max(1, min(limit, 500))).offset(
        max(0, offset)
    )
    rows = list((await db.execute(stmt)).scalars().all())
    return rows, int(total or 0)


async def update_definition(
    db: AsyncSession, obj: ProductAttributeDefinition, data: dict[str, Any]
) -> ProductAttributeDefinition:
    # value_type 与 key 不可变（改动会破坏既有 typed 值 / 稳定身份）
    before = revision_service.snapshot("attribute_definition", obj)
    if "name_zh" in data and data["name_zh"] is not None:
        nz = data["name_zh"].strip()
        if not nz:
            raise CatalogError("中文名称必填")
        obj.name_zh = nz
    if "name_en" in data:
        obj.name_en = (data["name_en"] or None)
    if "description" in data:
        obj.description = (data["description"] or None)
    if "unit" in data:
        obj.unit = ((data["unit"] or "").strip() or None)
    if "allowed_values" in data and data["allowed_values"] is not None:
        merged = {**_shape_of(obj), "allowed_values": data["allowed_values"]}
        _validate_definition_shape(merged)
        obj.allowed_values = data["allowed_values"] or None
    if "validation_rules" in data:
        merged = {**_shape_of(obj), "validation_rules": data["validation_rules"]}
        _validate_definition_shape(merged)
        obj.validation_rules = (data["validation_rules"] or None)
    for f in ("required", "searchable", "identity_relevant"):
        if f in data and data[f] is not None:
            setattr(obj, f, bool(data[f]))
    if "sort_order" in data and data["sort_order"] is not None:
        obj.sort_order = int(data["sort_order"])
    await revision_service.record(
        db, entity_type="attribute_definition", entity_id=obj.id, action="update",
        before=before, after=revision_service.snapshot("attribute_definition", obj),
        summary="更新属性定义",
    )
    return await _commit(db, obj)


def _shape_of(obj: ProductAttributeDefinition) -> dict[str, Any]:
    return {
        "value_type": obj.value_type, "unit": obj.unit,
        "allowed_values": obj.allowed_values, "validation_rules": obj.validation_rules,
    }


async def set_definition_status(
    db: AsyncSession, obj: ProductAttributeDefinition, status: CatalogStatus
) -> ProductAttributeDefinition:
    if status == CatalogStatus.MERGED:
        raise CatalogError("属性定义不支持 merged")
    before = revision_service.snapshot("attribute_definition", obj)
    obj.status = status
    obj.archived_at = utcnow() if status == CatalogStatus.ARCHIVED else None
    action = "archive" if status == CatalogStatus.ARCHIVED else (
        "restore" if before.get("status") == "archived" else "status"
    )
    await revision_service.record(
        db, entity_type="attribute_definition", entity_id=obj.id, action=action,
        before=before, after=revision_service.snapshot("attribute_definition", obj),
        summary=f"属性定义状态变更为 {status.value}",
    )
    return await _commit(db, obj)


# --------------------------------------------------------------------------- #
# 属性值（受约束 typed columns）
# --------------------------------------------------------------------------- #


async def _target_category_id(db: AsyncSession, target_type: str, target_id: int) -> int | None:
    """返回目标（family/variant/sku）所属 Category id（继承自 Family）。目标不存在则报错。"""
    model = _TARGET_MODELS.get(target_type)
    if model is None:
        raise CatalogError("属性值只能绑定 family / variant / sku")
    obj = await db.get(model, int(target_id))
    if obj is None:
        raise CatalogError(f"{target_type} 不存在: {target_id}")
    if target_type == "family":
        return obj.category_id
    fam = await db.get(ProductFamily, obj.family_id)
    return fam.category_id if fam else None


def _coerce_value(defn: ProductAttributeDefinition, raw: Any) -> dict[str, Any]:
    """按 value_type 校验并映射到 typed column 值。返回要设置的列 dict。"""
    vt = defn.value_type
    rules = defn.validation_rules or {}
    out: dict[str, Any] = {
        "value_text": None, "value_number": None, "value_boolean": None,
        "value_json": None, "value_date": None, "unit": None,
    }
    if raw is None:
        raise CatalogError("属性值不能为空（如需清除请删除该值）")

    if vt == "text":
        s = str(raw)
        _check_text_rules(s, rules)
        out["value_text"] = s
    elif vt == "number":
        out["value_number"] = _to_decimal(raw, rules)
    elif vt == "boolean":
        out["value_boolean"] = _to_bool(raw)
    elif vt == "date":
        out["value_date"] = _to_date(raw)
    elif vt == "enum":
        s = str(raw)
        if s not in (defn.allowed_values or []):
            raise CatalogError(f"值 {s!r} 不在允许取值内")
        out["value_text"] = s
    elif vt == "multi_enum":
        if not isinstance(raw, list):
            raise CatalogError("multi_enum 值必须为数组")
        allowed = set(defn.allowed_values or [])
        vals = [str(x) for x in raw]
        bad = [v for v in vals if v not in allowed]
        if bad:
            raise CatalogError(f"值 {bad} 不在允许取值内")
        out["value_json"] = vals
    elif vt == "measurement":
        out["value_number"] = _to_decimal(raw, rules)
        out["unit"] = defn.unit
    else:  # 理论不可达（定义创建时已校验白名单）
        raise CatalogError(f"未支持的 value_type: {vt}")
    return out


def _to_decimal(raw: Any, rules: dict[str, Any]) -> Decimal:
    try:
        d = Decimal(str(raw))
    except (InvalidOperation, ValueError) as exc:
        raise CatalogError(f"值 {raw!r} 不是合法数值") from exc
    if "min" in rules and d < Decimal(str(rules["min"])):
        raise CatalogError(f"值不得小于 {rules['min']}")
    if "max" in rules and d > Decimal(str(rules["max"])):
        raise CatalogError(f"值不得大于 {rules['max']}")
    return d


def _to_bool(raw: Any) -> bool:
    if isinstance(raw, bool):
        return raw
    s = str(raw).strip().lower()
    if s in ("true", "1", "yes"):
        return True
    if s in ("false", "0", "no"):
        return False
    raise CatalogError(f"值 {raw!r} 不是合法布尔")


def _to_date(raw: Any) -> date:
    try:
        return date.fromisoformat(str(raw)[:10])
    except ValueError as exc:
        raise CatalogError(f"值 {raw!r} 不是合法日期（YYYY-MM-DD）") from exc


def _check_text_rules(s: str, rules: dict[str, Any]) -> None:
    if "max_length" in rules and len(s) > int(rules["max_length"]):
        raise CatalogError(f"文本长度不得超过 {rules['max_length']}")
    pat = rules.get("pattern")
    if pat:
        try:
            if re.fullmatch(pat, s) is None:
                raise CatalogError("文本不匹配要求的格式")
        except re.error as exc:
            raise CatalogError("属性定义的 pattern 非法正则") from exc


async def set_value(
    db: AsyncSession, *, definition_id: int, target_type: str, target_id: int, value: Any
) -> ProductAttributeValue:
    """幂等 upsert：校验 + 归档旧活动值 + 插新值（保留历史）。"""
    defn = await db.get(ProductAttributeDefinition, int(definition_id))
    if defn is None:
        raise CatalogError(f"属性定义不存在: {definition_id}")
    if defn.status == CatalogStatus.ARCHIVED:
        raise CatalogError("已归档属性定义不可写入新值")
    target_cat = await _target_category_id(db, target_type, target_id)
    # Category 作用域：定义限定某 Category 时，目标须属于同一 Category
    if defn.category_id is not None and defn.category_id != target_cat:
        raise CatalogError("该属性不属于此产品的品类（跨 Category 使用被拒绝）")
    cols = _coerce_value(defn, value)

    col_attr = getattr(ProductAttributeValue, f"{target_type}_id")
    existing = (await db.execute(
        select(ProductAttributeValue).where(
            ProductAttributeValue.definition_id == defn.id,
            col_attr == target_id,
            ProductAttributeValue.archived_at.is_(None),
        )
    )).scalars().all()
    now = utcnow()
    old_snapshot = (
        revision_service.snapshot("attribute_value", existing[0]) if existing else None
    )
    for old in existing:
        old.archived_at = now  # 归档旧活动值，保留历史
    await db.flush()

    row = ProductAttributeValue(definition_id=defn.id, **cols)
    setattr(row, f"{target_type}_id", int(target_id))
    return await _add(
        db, row, rev_type="attribute_value", rev_action="update",
        rev_before=old_snapshot, rev_summary=f"写入属性值（{defn.key}）",
    )


async def list_values(
    db: AsyncSession, target_type: str, target_id: int, *, include_archived: bool = False
) -> list[ProductAttributeValue]:
    if target_type not in _TARGET_MODELS:
        raise CatalogError("属性值只能绑定 family / variant / sku")
    col_attr = getattr(ProductAttributeValue, f"{target_type}_id")
    stmt = select(ProductAttributeValue).where(col_attr == target_id)
    if not include_archived:
        stmt = stmt.where(ProductAttributeValue.archived_at.is_(None))
    stmt = stmt.order_by(ProductAttributeValue.id.asc())
    return list((await db.execute(stmt)).scalars().all())


async def delete_value(db: AsyncSession, value: ProductAttributeValue) -> None:
    """软删：归档该值（保留历史，不物理删除）。"""
    if value.archived_at is None:
        before = revision_service.snapshot("attribute_value", value)
        value.archived_at = utcnow()
        await revision_service.record(
            db, entity_type="attribute_value", entity_id=value.id, action="archive",
            before=before, after=revision_service.snapshot("attribute_value", value),
            summary="归档属性值",
        )
        await _commit(db, value)


# --------------------------------------------------------------------------- #
# profile 聚合（只读真实统计）
# --------------------------------------------------------------------------- #

_LEVEL_MODELS = {
    "category": ProductCategory, "family": ProductFamily,
    "variant": ProductVariant, "sku": ProductSKU,
}


async def get_profile(db: AsyncSession, level: str, node_id: int) -> dict[str, Any]:
    model = _LEVEL_MODELS.get(level)
    if model is None:
        raise CatalogError("未知层级")
    node = await db.get(model, int(node_id))
    if node is None:
        raise CatalogError(f"{level} 不存在: {node_id}")

    category_id = await _node_category(db, level, node)
    defs, _ = await list_definitions(
        db, category_id=category_id, include_global=True,
        status=CatalogStatus.ACTIVE, limit=500,
    )
    # 值仅对 family/variant/sku 有意义
    values = [] if level == "category" else await list_values(db, level, node_id)
    filled_def_ids = {v.definition_id for v in values}
    required_defs = [d for d in defs if d.required]
    missing_required = [
        {"definition_id": d.id, "key": d.key, "name_zh": d.name_zh}
        for d in required_defs if d.id not in filled_def_ids
    ]

    ref_counts = await _reference_counts(db, level, node_id)
    total_required = len(required_defs)
    filled_required = total_required - len(missing_required)
    completeness = (filled_required / total_required) if total_required else None

    return {
        "level": level,
        "id": node.id,
        "code": getattr(node, "code", None),
        "name_zh": node.name_zh,
        "category_id": category_id,
        "definition_count": len(defs),
        "value_count": len(values),
        "required_total": total_required,
        "required_filled": filled_required,
        "missing_required": missing_required,
        "completeness": completeness,  # None=无必填项；否则 0..1 真实占比
        "reference_total": ref_counts["total"],
        "reference_by_angle": ref_counts["by_angle"],
        "reference_primary_id": ref_counts["primary_id"],
        # 诚实声明：本阶段完整度仅为真实统计，不代表 AI 已能准确识别
        "ai_recognition_enabled": False,
    }


async def _node_category(db: AsyncSession, level: str, node: Any) -> int | None:
    if level == "category":
        return node.id
    if level == "family":
        return node.category_id
    fam = await db.get(ProductFamily, node.family_id)
    return fam.category_id if fam else None


async def _reference_counts(db: AsyncSession, level: str, node_id: int) -> dict[str, Any]:
    if level == "category":
        return {"total": 0, "by_angle": {}, "primary_id": None}
    col = getattr(ProductReferenceAsset, f"{level}_id")
    rows = (await db.execute(
        select(ProductReferenceAsset).where(
            col == node_id,
            ProductReferenceAsset.state.notin_(REFERENCE_HIDDEN_STATES),
        )
    )).scalars().all()
    by_angle: dict[str, int] = {}
    primary_id = None
    for r in rows:
        by_angle[r.angle] = by_angle.get(r.angle, 0) + 1
        if r.is_primary:
            primary_id = r.id
    return {"total": len(rows), "by_angle": by_angle, "primary_id": primary_id}


# --------------------------------------------------------------------------- #
# 提交助手
# --------------------------------------------------------------------------- #


async def _add(db: AsyncSession, row, *, rev_type: str | None = None,
               rev_summary: str | None = None, rev_action: str = "create",
               rev_before: dict[str, Any] | None = None):
    """新增行并提交；rev_type 非空时在**同一事务**内追加变更事件。"""
    db.add(row)
    try:
        if rev_type:
            await db.flush()
            await revision_service.record(
                db, entity_type=rev_type, entity_id=row.id, action=rev_action,
                before=rev_before, after=revision_service.snapshot(rev_type, row),
                summary=rev_summary,
            )
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        raise CatalogConflict(_conflict_detail(exc)) from exc
    await db.refresh(row)
    return row


async def _commit(db: AsyncSession, row):
    try:
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        raise CatalogConflict(_conflict_detail(exc)) from exc
    await db.refresh(row)
    return row


def _conflict_detail(exc: IntegrityError) -> str:
    t = str(getattr(exc, "orig", exc))
    if "nkey" in t:
        return "同一 Category 内该属性 key 已存在"
    if "attr_value" in t:
        return "同目标同定义已存在活动值"
    return "唯一约束冲突"
