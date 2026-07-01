"""PR-A1 通用产品目录服务（catalog_service）。

5 层实体（Category / Family / Variant / SKU / Alias）的 CRUD + 生命周期 + 合并 + 解析 + 树。

设计约束（方案 B，与既有扁平 `product` 表并存、不改动后者）：
- **稳定 code**：更名（改 name_*）不改 code / id；code 缺省由归一化名自动生成并保证唯一。
- **生命周期**：draft/active/paused/archived/merged；archive/merge **非物理删除**，历史关系保留。
- **合并**：`merged_into_id` 指向 canonical 目标；禁自合并、禁环、禁跨不兼容层级；沿链解析最终目标。
- **层级完整性**：Variant 属 Family；SKU 属 Family，可选属同一 Family 的 Variant（禁跨 Family）。
- **别名**：单表多目标（category/family/variant/sku 恰好一个），同目标 `normalized_alias` 唯一。
- 产品名/层级**绝不硬编码**：全部动态数据行。
"""

from __future__ import annotations

import re
from typing import Any

from clipmind_shared.db.base import utcnow
from clipmind_shared.models import (
    ProductCatalogAlias,
    ProductCategory,
    ProductFamily,
    ProductSKU,
    ProductVariant,
)
from clipmind_shared.models.enums import CATALOG_ALIAS_TYPES, CatalogStatus
from clipmind_shared.review import normalize_name
from sqlalchemy import String, cast, func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

# 目录层级：名称 -> ORM 模型
LEVELS = {
    "category": ProductCategory,
    "family": ProductFamily,
    "variant": ProductVariant,
    "sku": ProductSKU,
}
# 默认从 active 列表隐藏的状态
_HIDDEN = (CatalogStatus.ARCHIVED, CatalogStatus.MERGED)
# 合法生命周期转换（除 merge 外）
_TRANSITIONS: dict[CatalogStatus, set[CatalogStatus]] = {
    CatalogStatus.DRAFT: {CatalogStatus.ACTIVE, CatalogStatus.ARCHIVED},
    CatalogStatus.ACTIVE: {CatalogStatus.PAUSED, CatalogStatus.ARCHIVED},
    CatalogStatus.PAUSED: {CatalogStatus.ACTIVE, CatalogStatus.ARCHIVED},
    CatalogStatus.ARCHIVED: {CatalogStatus.DRAFT, CatalogStatus.ACTIVE},  # 恢复
    CatalogStatus.MERGED: set(),  # 已合并终态
}


class CatalogError(Exception):
    """目录业务错误（校验/约束）。默认映射为 422。"""


class CatalogConflict(CatalogError):
    """唯一性/冲突（映射为 409）。"""


def _slug(text: str) -> str:
    """从名称生成 code 基。保留中英文数字，其余转连字符。"""
    s = normalize_name(text)
    s = re.sub(r"[^\w一-鿿]+", "-", s, flags=re.UNICODE).strip("-")
    return s[:48] or "item"


async def _unique_code(db: AsyncSession, model: type, base: str) -> str:
    """在 model.code 上生成唯一 code（base、base-2、base-3…）。"""
    base = base[:48] or "item"
    candidate = base
    n = 1
    while True:
        exists = await db.scalar(select(model.id).where(model.code == candidate).limit(1))
        if exists is None:
            return candidate
        n += 1
        candidate = f"{base}-{n}"[:64]


def _require_zh(name_zh: str | None) -> str:
    name_zh = (name_zh or "").strip()
    if not name_zh:
        raise CatalogError("中文正式名称必填")
    return name_zh


async def _get_or_error(db: AsyncSession, level: str, obj_id: int):
    model = LEVELS[level]
    obj = await db.get(model, obj_id)
    if obj is None:
        raise CatalogError(f"{level} 不存在: {obj_id}")
    return obj


# --------------------------------------------------------------------------- #
# 创建
# --------------------------------------------------------------------------- #


async def create_category(db: AsyncSession, data: dict[str, Any]) -> ProductCategory:
    name_zh = _require_zh(data.get("name_zh"))
    code = (data.get("code") or "").strip() or await _unique_code(
        db, ProductCategory, _slug(name_zh)
    )
    row = ProductCategory(
        code=code,
        name_zh=name_zh,
        name_en=(data.get("name_en") or None),
        description=(data.get("description") or None),
        status=CatalogStatus.DRAFT,
        sort_order=int(data.get("sort_order") or 0),
    )
    return await _add(db, row)


async def create_family(db: AsyncSession, data: dict[str, Any]) -> ProductFamily:
    name_zh = _require_zh(data.get("name_zh"))
    category_id = data.get("category_id")
    if category_id is not None:
        await _get_or_error(db, "category", int(category_id))
    legacy_product_id = data.get("legacy_product_id")
    code = (data.get("code") or "").strip() or await _unique_code(
        db, ProductFamily, _slug(name_zh)
    )
    row = ProductFamily(
        category_id=category_id,
        code=code,
        name_zh=name_zh,
        name_en=(data.get("name_en") or None),
        description=(data.get("description") or None),
        status=CatalogStatus.DRAFT,
        legacy_product_id=legacy_product_id,
    )
    return await _add(db, row)


async def create_variant(db: AsyncSession, data: dict[str, Any]) -> ProductVariant:
    name_zh = _require_zh(data.get("name_zh"))
    family = await _get_or_error(db, "family", int(data["family_id"]))
    code = (data.get("code") or "").strip() or await _unique_code(
        db, ProductVariant, _slug(name_zh)
    )
    row = ProductVariant(
        family_id=family.id,
        code=code,
        name_zh=name_zh,
        name_en=(data.get("name_en") or None),
        description=(data.get("description") or None),
        status=CatalogStatus.DRAFT,
    )
    return await _add(db, row)


async def create_sku(db: AsyncSession, data: dict[str, Any]) -> ProductSKU:
    name_zh = _require_zh(data.get("name_zh"))
    family = await _get_or_error(db, "family", int(data["family_id"]))
    variant_id = data.get("variant_id")
    if variant_id is not None:
        variant = await _get_or_error(db, "variant", int(variant_id))
        if variant.family_id != family.id:
            raise CatalogError("SKU 的 variant 必须属于同一 family（不允许跨 family）")
    code = (data.get("code") or "").strip() or await _unique_code(
        db, ProductSKU, _slug(name_zh)
    )
    row = ProductSKU(
        family_id=family.id,
        variant_id=variant_id,
        code=code,
        sku_code=(data.get("sku_code") or None),
        name_zh=name_zh,
        name_en=(data.get("name_en") or None),
        status=CatalogStatus.DRAFT,
    )
    return await _add(db, row)


async def _add(db: AsyncSession, row):
    db.add(row)
    try:
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        raise CatalogConflict(_conflict_detail(exc)) from exc
    await db.refresh(row)
    return row


def _conflict_detail(exc: IntegrityError) -> str:
    text = str(getattr(exc, "orig", exc))
    if "uq_product_sku_sku_code" in text:
        return "SKU 编码已存在"
    if "_code" in text:
        return "code 已存在"
    if "normalized_alias" in text or "catalog_alias" in text:
        return "同一目标下已存在该别名"
    return "唯一约束冲突"


# --------------------------------------------------------------------------- #
# 读取 / 列表 / 树 / 搜索 / 解析
# --------------------------------------------------------------------------- #


async def list_level(
    db: AsyncSession,
    level: str,
    *,
    q: str | None = None,
    status: CatalogStatus | None = None,
    include_archived: bool = False,
    category_id: int | None = None,
    family_id: int | None = None,
    variant_id: int | None = None,
    limit: int = 50,
    offset: int = 0,
) -> tuple[list[Any], int]:
    model = LEVELS[level]
    stmt = select(model)
    if status is not None:
        stmt = stmt.where(model.status == status)
    elif not include_archived:
        stmt = stmt.where(model.status.notin_(_HIDDEN))
    if category_id is not None and level == "family":
        stmt = stmt.where(model.category_id == category_id)
    if family_id is not None and level in ("variant", "sku"):
        stmt = stmt.where(model.family_id == family_id)
    if variant_id is not None and level == "sku":
        stmt = stmt.where(model.variant_id == variant_id)
    if q:
        nq = f"%{normalize_name(q)}%"
        like = f"%{q.strip()}%"
        conds = [
            func.lower(model.name_zh).like(func.lower(like)),
            model.code.like(like),
        ]
        if hasattr(model, "name_en"):
            conds.append(func.lower(model.name_en).like(func.lower(like)))
        if hasattr(model, "sku_code"):
            conds.append(model.sku_code.like(like))
        # 归一化名匹配（简易：对 name_zh 归一后 like）
        conds.append(func.lower(model.name_zh).like(nq))
        stmt = stmt.where(or_(*conds))
    total = await db.scalar(select(func.count()).select_from(stmt.subquery()))
    order_cols = (
        [model.sort_order.asc(), model.id.asc()]
        if hasattr(model, "sort_order")
        else [model.id.asc()]
    )
    stmt = stmt.order_by(*order_cols)
    stmt = stmt.limit(max(1, min(limit, 500))).offset(max(0, offset))
    rows = list((await db.execute(stmt)).scalars().all())
    return rows, int(total or 0)


async def get_tree(db: AsyncSession, *, include_archived: bool = False) -> list[dict]:
    """Category → Family → Variant → SKU 只读层级树。"""

    def _visible(rows):
        return [r for r in rows if include_archived or r.status not in _HIDDEN]

    cats = _visible((await db.execute(select(ProductCategory))).scalars().all())
    fams = _visible((await db.execute(select(ProductFamily))).scalars().all())
    vars_ = _visible((await db.execute(select(ProductVariant))).scalars().all())
    skus = _visible((await db.execute(select(ProductSKU))).scalars().all())

    sku_by_variant: dict[int, list] = {}
    sku_by_family_no_variant: dict[int, list] = {}
    for s in skus:
        if s.variant_id is not None:
            sku_by_variant.setdefault(s.variant_id, []).append(s)
        else:
            sku_by_family_no_variant.setdefault(s.family_id, []).append(s)
    var_by_family: dict[int, list] = {}
    for v in vars_:
        var_by_family.setdefault(v.family_id, []).append(v)
    fam_by_cat: dict[int | None, list] = {}
    for f in fams:
        fam_by_cat.setdefault(f.category_id, []).append(f)

    def _node(obj, level, children):
        return {
            "level": level, "id": obj.id, "code": obj.code,
            "name_zh": obj.name_zh, "name_en": getattr(obj, "name_en", None),
            "status": obj.status, "children": children,
        }

    def _variant_node(v):
        return _node(v, "variant", [_node(s, "sku", []) for s in sku_by_variant.get(v.id, [])])

    def _family_node(f):
        children = [_variant_node(v) for v in var_by_family.get(f.id, [])]
        children += [_node(s, "sku", []) for s in sku_by_family_no_variant.get(f.id, [])]
        return _node(f, "family", children)

    tree = [
        _node(c, "category", [_family_node(f) for f in fam_by_cat.get(c.id, [])])
        for c in cats
    ]
    # 未归类 family（category_id 为空）作为顶层"未分类"分组
    orphan = [_family_node(f) for f in fam_by_cat.get(None, [])]
    if orphan:
        tree.append({
            "level": "category", "id": None, "code": "__uncategorized__",
            "name_zh": "未分类", "name_en": None, "status": CatalogStatus.ACTIVE,
            "children": orphan,
        })
    return tree


async def search_catalog(db: AsyncSession, q: str, *, limit: int = 20) -> list[dict]:
    """跨层级搜索（名称/code/sku_code + 别名）。"""
    results: list[dict] = []
    for level in ("category", "family", "variant", "sku"):
        rows, _ = await list_level(db, level, q=q, include_archived=False, limit=limit)
        for r in rows:
            results.append(_brief(level, r))
    return results[:limit]


async def resolve(db: AsyncSession, value: str) -> dict | None:
    """解析产品目录节点：中文名/英文名/code/sku_code/别名/merge 重定向。

    绝不强制猜测：无精确命中返回 None（调用方据此给候选，不臆造）。
    """
    value = (value or "").strip()
    if not value:
        return None
    nv = normalize_name(value)
    # 1) 别名精确命中（归一化）
    alias = (
        await db.execute(
            select(ProductCatalogAlias).where(ProductCatalogAlias.normalized_alias == nv)
        )
    ).scalars().first()
    if alias is not None:
        node = await _alias_target(db, alias)
        if node is not None:
            return await _resolve_redirect(db, node[0], node[1])
    # 2) code / sku_code / 归一化名 精确命中（各层）
    for level in ("sku", "variant", "family", "category"):
        model = LEVELS[level]
        conds = [model.code == value]
        if hasattr(model, "sku_code"):
            conds.append(model.sku_code == value)
        obj = (
            await db.execute(select(model).where(or_(*conds)))
        ).scalars().first()
        if obj is None:
            obj = (
                await db.execute(
                    select(model).where(
                        func.lower(cast(model.name_zh, String)) == value.lower()
                    )
                )
            ).scalars().first()
        if obj is not None:
            return await _resolve_redirect(db, level, obj)
    return None


async def _alias_target(db: AsyncSession, alias: ProductCatalogAlias):
    for level, attr in (
        ("category", "category_id"), ("family", "family_id"),
        ("variant", "variant_id"), ("sku", "sku_id"),
    ):
        tid = getattr(alias, attr)
        if tid is not None:
            obj = await db.get(LEVELS[level], tid)
            return (level, obj) if obj is not None else None
    return None


async def _resolve_redirect(db: AsyncSession, level: str, obj) -> dict:
    """跟随 merged_into_id 到 canonical 目标（防环，最多 20 跳）。"""
    model = LEVELS[level]
    seen = set()
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
    return {**_brief(level, obj), "redirected": hops > 0}


def _brief(level: str, obj) -> dict:
    return {
        "level": level, "id": obj.id, "code": obj.code,
        "name_zh": obj.name_zh, "name_en": getattr(obj, "name_en", None),
        "sku_code": getattr(obj, "sku_code", None),
        "status": obj.status,
    }


# --------------------------------------------------------------------------- #
# 更新 / 更名 / 生命周期
# --------------------------------------------------------------------------- #


async def update_node(db: AsyncSession, level: str, obj, data: dict[str, Any]):
    """更新名称/描述等（**更名不改 id / code**）。"""
    if "name_zh" in data:
        obj.name_zh = _require_zh(data["name_zh"])
    if "name_en" in data:
        obj.name_en = data["name_en"] or None
    if "description" in data and hasattr(obj, "description"):
        obj.description = data["description"] or None
    if "sort_order" in data and hasattr(obj, "sort_order"):
        obj.sort_order = int(data["sort_order"] or 0)
    if "category_id" in data and level == "family":
        cid = data["category_id"]
        if cid is not None:
            await _get_or_error(db, "category", int(cid))
        obj.category_id = cid
    if "sku_code" in data and hasattr(obj, "sku_code"):
        obj.sku_code = data["sku_code"] or None
    return await _commit(db, obj)


async def set_status(db: AsyncSession, level: str, obj, new_status: CatalogStatus):
    if obj.status == CatalogStatus.MERGED:
        raise CatalogError("已合并节点不可变更状态")
    if new_status == CatalogStatus.MERGED:
        raise CatalogError("合并请用 merge 接口")
    if new_status != obj.status and new_status not in _TRANSITIONS.get(obj.status, set()):
        raise CatalogError(f"不允许的状态转换：{obj.status} -> {new_status}")
    obj.status = new_status
    obj.archived_at = utcnow() if new_status == CatalogStatus.ARCHIVED else None
    return await _commit(db, obj)


async def archive(db: AsyncSession, level: str, obj):
    return await set_status(db, level, obj, CatalogStatus.ARCHIVED)


async def restore(db: AsyncSession, level: str, obj):
    if obj.status != CatalogStatus.ARCHIVED:
        raise CatalogError("仅归档节点可恢复")
    obj.status = CatalogStatus.ACTIVE
    obj.archived_at = None
    return await _commit(db, obj)


async def merge(db: AsyncSession, level: str, source, target_id: int):
    """把 source 合并到 target（同层级）。source 保留（status=merged, merged_into_id=target）。"""
    if source.id == target_id:
        raise CatalogError("不允许自合并")
    model = LEVELS[level]
    target = await db.get(model, target_id)
    if target is None:
        raise CatalogError(f"目标 {level} 不存在: {target_id}")
    if target.status == CatalogStatus.MERGED:
        raise CatalogError("目标节点已被合并，请合并到其 canonical 目标")
    # 层级兼容：variant/sku 合并须同 family
    if level in ("variant", "sku") and source.family_id != target.family_id:
        raise CatalogError("不允许跨 family 合并")
    # 防环：target 沿 merged_into 链不得回到 source
    seen = {source.id}
    cur = target
    hops = 0
    while getattr(cur, "merged_into_id", None) is not None and hops < 50:
        if cur.merged_into_id in seen:
            raise CatalogError("合并会形成环")
        seen.add(cur.merged_into_id)
        cur = await db.get(model, cur.merged_into_id)
        if cur is None:
            break
        hops += 1
    source.status = CatalogStatus.MERGED
    source.merged_into_id = target.id
    source.archived_at = utcnow()
    return await _commit(db, source)


async def _commit(db: AsyncSession, obj):
    try:
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        raise CatalogConflict(_conflict_detail(exc)) from exc
    await db.refresh(obj)
    return obj


# --------------------------------------------------------------------------- #
# 别名
# --------------------------------------------------------------------------- #

_TARGET_ATTR = {
    "category": "category_id", "family": "family_id",
    "variant": "variant_id", "sku": "sku_id",
}


async def list_aliases(
    db: AsyncSession, level: str | None = None, target_id: int | None = None
) -> list[ProductCatalogAlias]:
    stmt = select(ProductCatalogAlias)
    if level and target_id is not None:
        stmt = stmt.where(getattr(ProductCatalogAlias, _TARGET_ATTR[level]) == target_id)
    return list((await db.execute(stmt.order_by(ProductCatalogAlias.id.asc()))).scalars().all())


async def add_alias(db: AsyncSession, data: dict[str, Any]) -> ProductCatalogAlias:
    level = data.get("target_level")
    target_id = data.get("target_id")
    if level not in _TARGET_ATTR or target_id is None:
        raise CatalogError("必须指定 target_level 与 target_id")
    await _get_or_error(db, level, int(target_id))
    alias = (data.get("alias") or "").strip()
    if not alias:
        raise CatalogError("别名不能为空")
    alias_type = (data.get("alias_type") or "zh_name").strip()
    if alias_type not in CATALOG_ALIAS_TYPES:
        raise CatalogError(f"未知别名类型: {alias_type}")
    row = ProductCatalogAlias(
        alias=alias,
        normalized_alias=normalize_name(alias),
        language=(data.get("language") or None),
        alias_type=alias_type,
        is_primary=bool(data.get("is_primary")),
    )
    setattr(row, _TARGET_ATTR[level], int(target_id))
    return await _add(db, row)


async def update_alias(db: AsyncSession, alias_id: int, data: dict[str, Any]):
    row = await db.get(ProductCatalogAlias, alias_id)
    if row is None:
        raise CatalogError("别名不存在")
    if "alias" in data:
        a = (data["alias"] or "").strip()
        if not a:
            raise CatalogError("别名不能为空")
        row.alias = a
        row.normalized_alias = normalize_name(a)
    if "language" in data:
        row.language = data["language"] or None
    if "alias_type" in data:
        at = (data["alias_type"] or "").strip()
        if at not in CATALOG_ALIAS_TYPES:
            raise CatalogError(f"未知别名类型: {at}")
        row.alias_type = at
    if "is_primary" in data:
        row.is_primary = bool(data["is_primary"])
    return await _commit(db, row)


async def delete_alias(db: AsyncSession, alias_id: int) -> bool:
    row = await db.get(ProductCatalogAlias, alias_id)
    if row is None:
        return False
    await db.delete(row)
    await db.commit()
    return True
