"""PR-A1 通用产品目录服务（catalog_service）。

5 层实体（Category / Family / Variant / SKU / Alias）的 CRUD + 生命周期 + 合并 + 解析 + 树。

设计约束（方案 B，与既有扁平 `product` 表并存、不改动后者）：
- **稳定 code**：更名（改 name_*）不改 code / id；code 缺省由归一化名自动生成并保证唯一。
- **code 唯一作用域（大小写/首尾空白无关，存 normalized_code）**：Category/Family 全局；
  Variant/SKU 同一 Family 内；SKU 的 sku_code 非空时全局唯一（normalized_sku_code）。
- **生命周期**：draft/active/paused/archived/merged；archive/merge 非物理删除。
  层级激活校验：Family 激活须 Category 存在且 active；Variant 激活须 Family active；
  SKU 激活须 Family active 且（有 Variant 时）Variant active；merged 不可复活。
- **更名自动历史别名**：改 name_zh/name_en 时在**同一事务**建 historical_name 别名（幂等）。
- **合并**：merged_into_id 指向 canonical；禁自合并/环/跨不兼容层级；**有子级时禁合并（409）**。
- **归档保护**：Category 下有活跃 Family 时禁归档（409）。
- **歧义安全解析**：resolve 返回 resolved / ambiguous / not_found，绝不任取第一条。
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

from app.services import revision_service

LEVELS = {
    "category": ProductCategory,
    "family": ProductFamily,
    "variant": ProductVariant,
    "sku": ProductSKU,
}
_HIDDEN = (CatalogStatus.ARCHIVED, CatalogStatus.MERGED)
_TRANSITIONS: dict[CatalogStatus, set[CatalogStatus]] = {
    CatalogStatus.DRAFT: {CatalogStatus.ACTIVE, CatalogStatus.ARCHIVED},
    CatalogStatus.ACTIVE: {CatalogStatus.PAUSED, CatalogStatus.ARCHIVED},
    CatalogStatus.PAUSED: {CatalogStatus.ACTIVE, CatalogStatus.ARCHIVED},
    CatalogStatus.ARCHIVED: {CatalogStatus.DRAFT, CatalogStatus.ACTIVE},  # 恢复
    CatalogStatus.MERGED: set(),  # 终态
}
_TARGET_ATTR = {
    "category": "category_id", "family": "family_id",
    "variant": "variant_id", "sku": "sku_id",
}


class CatalogError(Exception):
    """目录业务错误（校验/约束）。默认 422。"""


class CatalogConflict(CatalogError):
    """唯一性/冲突（409）。"""


def _norm(s: str | None) -> str:
    return normalize_name((s or "").strip())


def _slug(text: str) -> str:
    s = normalize_name(text)
    s = re.sub(r"[^\w一-鿿]+", "-", s, flags=re.UNICODE).strip("-")
    return s[:48] or "item"


async def _unique_code(
    db: AsyncSession, model: type, base: str, *, family_id: int | None = None
) -> str:
    """生成 code：Category/Family 全局唯一；Variant/SKU 在 family_id 作用域内唯一。"""
    base = base[:48] or "item"
    candidate = base
    n = 1
    while True:
        stmt = select(model.id).where(model.normalized_code == _norm(candidate))
        if family_id is not None and hasattr(model, "family_id"):
            stmt = stmt.where(model.family_id == family_id)
        if await db.scalar(stmt.limit(1)) is None:
            return candidate
        n += 1
        candidate = f"{base}-{n}"[:64]


def _require_zh(name_zh: str | None) -> str:
    name_zh = (name_zh or "").strip()
    if not name_zh:
        raise CatalogError("中文正式名称必填")
    return name_zh


async def _get_or_error(db: AsyncSession, level: str, obj_id: int):
    obj = await db.get(LEVELS[level], obj_id)
    if obj is None:
        raise CatalogError(f"{level} 不存在: {obj_id}")
    return obj


def _conflict_detail(exc: IntegrityError) -> str:
    t = str(getattr(exc, "orig", exc))
    if "norm_sku_code" in t:
        return "SKU 编码已存在（大小写/空白无关全局唯一）"
    if "variant_family_ncode" in t or "sku_family_ncode" in t:
        return "同一 family 内 code 已存在"
    if "ncode" in t:
        return "code 已存在（大小写/空白无关）"
    if "normalized_alias" in t or "catalog_alias" in t:
        return "同一目标下已存在该别名"
    if "legacy_product" in t:
        return "该 legacy 产品已被其它 family 桥接"
    return "唯一约束冲突"


# --------------------------------------------------------------------------- #
# 创建
# --------------------------------------------------------------------------- #


async def create_category(db: AsyncSession, data: dict[str, Any]) -> ProductCategory:
    name_zh = _require_zh(data.get("name_zh"))
    code = (data.get("code") or "").strip() or await _unique_code(
        db, ProductCategory, _slug(name_zh)
    )
    row = ProductCategory(
        code=code, normalized_code=_norm(code), name_zh=name_zh,
        name_en=(data.get("name_en") or None), description=(data.get("description") or None),
        status=CatalogStatus.DRAFT, sort_order=int(data.get("sort_order") or 0),
    )
    return await _add(db, row, rev_type="category", rev_summary="创建产品类别")


async def create_family(db: AsyncSession, data: dict[str, Any]) -> ProductFamily:
    name_zh = _require_zh(data.get("name_zh"))
    category_id = data.get("category_id")
    if category_id is not None:
        await _get_or_error(db, "category", int(category_id))
    code = (data.get("code") or "").strip() or await _unique_code(
        db, ProductFamily, _slug(name_zh)
    )
    row = ProductFamily(
        category_id=category_id, code=code, normalized_code=_norm(code), name_zh=name_zh,
        name_en=(data.get("name_en") or None), description=(data.get("description") or None),
        status=CatalogStatus.DRAFT, legacy_product_id=data.get("legacy_product_id"),
    )
    return await _add(db, row, rev_type="family", rev_summary="创建产品系列")


async def create_variant(db: AsyncSession, data: dict[str, Any]) -> ProductVariant:
    name_zh = _require_zh(data.get("name_zh"))
    family = await _get_or_error(db, "family", int(data["family_id"]))
    code = (data.get("code") or "").strip() or await _unique_code(
        db, ProductVariant, _slug(name_zh), family_id=family.id
    )
    row = ProductVariant(
        family_id=family.id, code=code, normalized_code=_norm(code), name_zh=name_zh,
        name_en=(data.get("name_en") or None), description=(data.get("description") or None),
        status=CatalogStatus.DRAFT,
    )
    return await _add(db, row, rev_type="variant", rev_summary="创建产品变体")


async def create_sku(db: AsyncSession, data: dict[str, Any]) -> ProductSKU:
    name_zh = _require_zh(data.get("name_zh"))
    family = await _get_or_error(db, "family", int(data["family_id"]))
    variant_id = data.get("variant_id")
    if variant_id is not None:
        variant = await _get_or_error(db, "variant", int(variant_id))
        if variant.family_id != family.id:
            raise CatalogError("SKU 的 variant 必须属于同一 family（不允许跨 family）")
    code = (data.get("code") or "").strip() or await _unique_code(
        db, ProductSKU, _slug(name_zh), family_id=family.id
    )
    sku_code = (data.get("sku_code") or "").strip() or None
    row = ProductSKU(
        family_id=family.id, variant_id=variant_id, code=code, normalized_code=_norm(code),
        sku_code=sku_code, normalized_sku_code=(_norm(sku_code) if sku_code else None),
        name_zh=name_zh, name_en=(data.get("name_en") or None), status=CatalogStatus.DRAFT,
    )
    return await _add(db, row, rev_type="sku", rev_summary="创建产品 SKU")


async def _add(db: AsyncSession, row, *, rev_type: str | None = None,
               rev_summary: str | None = None):
    """新增行并提交；rev_type 非空时在**同一事务**内追加 create 变更事件。"""
    db.add(row)
    try:
        if rev_type:
            await db.flush()
            await revision_service.record(
                db, entity_type=rev_type, entity_id=row.id, action="create",
                after=revision_service.snapshot(rev_type, row), summary=rev_summary,
            )
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        raise CatalogConflict(_conflict_detail(exc)) from exc
    await db.refresh(row)
    return row


# --------------------------------------------------------------------------- #
# 读取 / 列表 / 树 / 搜索
# --------------------------------------------------------------------------- #


async def list_level(
    db: AsyncSession, level: str, *, q: str | None = None,
    status: CatalogStatus | None = None, include_archived: bool = False,
    category_id: int | None = None, family_id: int | None = None,
    variant_id: int | None = None, limit: int = 50, offset: int = 0,
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
        like = f"%{q.strip()}%"
        conds = [func.lower(model.name_zh).like(func.lower(like)), model.code.like(like)]
        if hasattr(model, "name_en"):
            conds.append(func.lower(model.name_en).like(func.lower(like)))
        if hasattr(model, "sku_code"):
            conds.append(model.sku_code.like(like))
        stmt = stmt.where(or_(*conds))
    total = await db.scalar(select(func.count()).select_from(stmt.subquery()))
    order_cols = (
        [model.sort_order.asc(), model.id.asc()]
        if hasattr(model, "sort_order") else [model.id.asc()]
    )
    stmt = stmt.order_by(*order_cols).limit(max(1, min(limit, 500))).offset(max(0, offset))
    rows = list((await db.execute(stmt)).scalars().all())
    return rows, int(total or 0)


async def get_tree(db: AsyncSession, *, include_archived: bool = False) -> list[dict]:
    def _visible(rows):
        return [r for r in rows if include_archived or r.status not in _HIDDEN]

    cats = _visible((await db.execute(select(ProductCategory))).scalars().all())
    fams = _visible((await db.execute(select(ProductFamily))).scalars().all())
    vars_ = _visible((await db.execute(select(ProductVariant))).scalars().all())
    skus = _visible((await db.execute(select(ProductSKU))).scalars().all())

    sku_by_variant: dict[int, list] = {}
    sku_by_family_no_variant: dict[int, list] = {}
    for s in skus:
        (sku_by_variant if s.variant_id else sku_by_family_no_variant).setdefault(
            s.variant_id if s.variant_id else s.family_id, []
        ).append(s)
    var_by_family: dict[int, list] = {}
    for v in vars_:
        var_by_family.setdefault(v.family_id, []).append(v)
    fam_by_cat: dict[int | None, list] = {}
    for f in fams:
        fam_by_cat.setdefault(f.category_id, []).append(f)

    def _node(obj, level, children):
        return {
            "level": level, "id": obj.id, "code": obj.code, "name_zh": obj.name_zh,
            "name_en": getattr(obj, "name_en", None), "status": obj.status, "children": children,
        }

    def _family_node(f):
        children = [
            _node(v, "variant", [_node(s, "sku", []) for s in sku_by_variant.get(v.id, [])])
            for v in var_by_family.get(f.id, [])
        ]
        children += [_node(s, "sku", []) for s in sku_by_family_no_variant.get(f.id, [])]
        return _node(f, "family", children)

    tree = [
        _node(c, "category", [_family_node(f) for f in fam_by_cat.get(c.id, [])]) for c in cats
    ]
    orphan = [_family_node(f) for f in fam_by_cat.get(None, [])]
    if orphan:
        tree.append({
            "level": "category", "id": None, "code": "__uncategorized__",
            "name_zh": "未分类", "name_en": None, "status": CatalogStatus.ACTIVE,
            "children": orphan,
        })
    return tree


async def search_catalog(db: AsyncSession, q: str, *, limit: int = 20) -> list[dict]:
    results: list[dict] = []
    for level in ("category", "family", "variant", "sku"):
        rows, _ = await list_level(db, level, q=q, include_archived=False, limit=limit)
        results.extend(_brief(level, r) for r in rows)
    return results[:limit]


def _brief(level: str, obj) -> dict:
    return {
        "level": level, "id": obj.id, "code": obj.code, "name_zh": obj.name_zh,
        "name_en": getattr(obj, "name_en", None), "sku_code": getattr(obj, "sku_code", None),
        "status": obj.status,
    }


# --------------------------------------------------------------------------- #
# 解析（歧义安全）
# --------------------------------------------------------------------------- #


async def _canonical(db: AsyncSession, level: str, obj):
    """沿 merged_into_id 到 canonical（防环，≤20 跳）。返回 (level, obj)。"""
    model = LEVELS[level]
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
    return level, obj


async def resolve(db: AsyncSession, value: str) -> dict:
    """歧义安全解析。优先级：sku_code → code → 正式名 → 别名（均跟随 merge 重定向）。

    返回 {status: resolved|ambiguous|not_found, canonical, candidates}。
    单一 canonical → resolved；多个不同 canonical → ambiguous；无 → 下一优先级；全无 → not_found。
    绝不任取第一条、绝不靠 DB 返回顺序。
    """
    value = (value or "").strip()
    if not value:
        return {"status": "not_found", "canonical": None, "candidates": []}
    nv = _norm(value)

    async def _dedup(pairs: list[tuple[str, Any]]) -> list[dict]:
        seen: set[tuple[str, int]] = set()
        out: list[dict] = []
        for level, obj in pairs:
            clevel, cobj = await _canonical(db, level, obj)
            key = (clevel, cobj.id)
            if key not in seen:
                seen.add(key)
                out.append({**_brief(clevel, cobj), "redirected": cobj.id != obj.id})
        return out

    # 1) sku_code（全局唯一 normalized_sku_code）
    skus = (await db.execute(
        select(ProductSKU).where(ProductSKU.normalized_sku_code == nv)
    )).scalars().all()
    cands = await _dedup([("sku", s) for s in skus])
    if cands:
        return _result(cands)

    # 2) code（normalized_code；variant/sku family 作用域 → 可能多命中）
    pairs: list[tuple[str, Any]] = []
    for level in ("category", "family", "variant", "sku"):
        model = LEVELS[level]
        rows = (await db.execute(
            select(model).where(model.normalized_code == nv)
        )).scalars().all()
        pairs += [(level, r) for r in rows]
    cands = await _dedup(pairs)
    if cands:
        return _result(cands)

    # 3) 正式名（name_zh / name_en，大小写无关）
    pairs = []
    for level in ("category", "family", "variant", "sku"):
        model = LEVELS[level]
        conds = [func.lower(cast(model.name_zh, String)) == value.lower()]
        conds.append(func.lower(cast(model.name_en, String)) == value.lower())
        rows = (await db.execute(select(model).where(or_(*conds)))).scalars().all()
        pairs += [(level, r) for r in rows]
    cands = await _dedup(pairs)
    if cands:
        return _result(cands)

    # 4) 别名（normalized_alias）
    aliases = (await db.execute(
        select(ProductCatalogAlias).where(ProductCatalogAlias.normalized_alias == nv)
    )).scalars().all()
    pairs = []
    for a in aliases:
        for level, attr in _TARGET_ATTR.items():
            tid = getattr(a, attr)
            if tid is not None:
                obj = await db.get(LEVELS[level], tid)
                if obj is not None:
                    pairs.append((level, obj))
                break
    cands = await _dedup(pairs)
    if cands:
        return _result(cands)

    return {"status": "not_found", "canonical": None, "candidates": []}


def _result(cands: list[dict]) -> dict:
    if len(cands) == 1:
        return {"status": "resolved", "canonical": cands[0], "candidates": cands}
    return {"status": "ambiguous", "canonical": None, "candidates": cands}


# --------------------------------------------------------------------------- #
# 更新 / 更名（自动历史别名）/ 生命周期
# --------------------------------------------------------------------------- #


async def _add_historical_alias(
    db: AsyncSession, level: str, target_id: int, alias: str, language: str,
    correlation_id: str | None = None,
) -> None:
    """同事务追加 historical_name 别名（幂等：同目标同 normalized_alias 已存在则跳过）。"""
    na = _norm(alias)
    if not na:
        return
    attr = _TARGET_ATTR[level]
    exists = await db.scalar(
        select(ProductCatalogAlias.id).where(
            getattr(ProductCatalogAlias, attr) == target_id,
            ProductCatalogAlias.normalized_alias == na,
        ).limit(1)
    )
    if exists is not None:
        return
    row = ProductCatalogAlias(
        alias=alias.strip(), normalized_alias=na, language=language,
        alias_type="historical_name", is_primary=False,
    )
    setattr(row, attr, target_id)
    db.add(row)
    await db.flush()
    await revision_service.record(
        db, entity_type="alias", entity_id=row.id, action="create",
        after=revision_service.snapshot("alias", row),
        summary="更名自动保留历史名称别名", correlation_id=correlation_id,
    )


async def update_node(db: AsyncSession, level: str, obj, data: dict[str, Any]):
    """更新名称/描述等（**更名不改 id/code**；改名同事务自动建历史别名）。"""
    before = revision_service.snapshot(level, obj)
    corr = revision_service.new_correlation_id()
    if "name_zh" in data:
        new_zh = _require_zh(data["name_zh"])
        if obj.name_zh and obj.name_zh.strip() and _norm(obj.name_zh) != _norm(new_zh):
            await _add_historical_alias(db, level, obj.id, obj.name_zh, "zh", corr)
        obj.name_zh = new_zh
    if "name_en" in data and hasattr(obj, "name_en"):
        new_en = (data["name_en"] or None)
        old_en = obj.name_en
        if old_en and old_en.strip() and _norm(old_en) != _norm(new_en or ""):
            await _add_historical_alias(db, level, obj.id, old_en, "en", corr)
        obj.name_en = new_en
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
        sc = (data["sku_code"] or "").strip() or None
        obj.sku_code = sc
        obj.normalized_sku_code = _norm(sc) if sc else None
    await revision_service.record(
        db, entity_type=level, entity_id=obj.id, action="update",
        before=before, after=revision_service.snapshot(level, obj),
        summary=f"更新 {level} 基础信息", correlation_id=corr,
    )
    return await _commit(db, obj)


async def _check_activation(db: AsyncSession, level: str, obj) -> None:
    """激活（→active）时的层级校验。"""
    if level == "family":
        if obj.category_id is None:
            raise CatalogError("激活 Family 前必须归属一个 Category")
        cat = await db.get(ProductCategory, obj.category_id)
        if cat is None or cat.status != CatalogStatus.ACTIVE:
            raise CatalogError("所属 Category 必须为 active")
    elif level == "variant":
        fam = await db.get(ProductFamily, obj.family_id)
        if fam is None or fam.status != CatalogStatus.ACTIVE:
            raise CatalogError("所属 Family 必须为 active")
    elif level == "sku":
        fam = await db.get(ProductFamily, obj.family_id)
        if fam is None or fam.status != CatalogStatus.ACTIVE:
            raise CatalogError("所属 Family 必须为 active")
        if obj.variant_id is not None:
            var = await db.get(ProductVariant, obj.variant_id)
            if var is None or var.status != CatalogStatus.ACTIVE:
                raise CatalogError("所属 Variant 必须为 active")


async def set_status(db: AsyncSession, level: str, obj, new_status: CatalogStatus):
    if obj.status == CatalogStatus.MERGED:
        raise CatalogError("已合并节点不可变更状态")
    if new_status == CatalogStatus.MERGED:
        raise CatalogError("合并请用 merge 接口")
    if new_status != obj.status and new_status not in _TRANSITIONS.get(obj.status, set()):
        raise CatalogError(f"不允许的状态转换：{obj.status} -> {new_status}")
    if new_status == CatalogStatus.ARCHIVED:
        await _check_archive(db, level, obj)
    if new_status == CatalogStatus.ACTIVE:
        await _check_activation(db, level, obj)
    before = revision_service.snapshot(level, obj)
    obj.status = new_status
    obj.archived_at = utcnow() if new_status == CatalogStatus.ARCHIVED else None
    action = "archive" if new_status == CatalogStatus.ARCHIVED else "status"
    await revision_service.record(
        db, entity_type=level, entity_id=obj.id, action=action,
        before=before, after=revision_service.snapshot(level, obj),
        summary=f"{level} 状态变更为 {new_status.value}",
    )
    return await _commit(db, obj)


async def _check_archive(db: AsyncSession, level: str, obj) -> None:
    """Category 下存在活跃 Family 时禁止归档（避免活跃 Family 静默从树消失）。"""
    if level == "category":
        cnt = await db.scalar(
            select(func.count()).select_from(ProductFamily).where(
                ProductFamily.category_id == obj.id,
                ProductFamily.status.notin_(_HIDDEN),
            )
        )
        if cnt:
            raise CatalogConflict(
                f"该类别下仍有 {int(cnt)} 个未归档产品系列，请先归档/迁移它们"
            )


async def archive(db: AsyncSession, level: str, obj):
    return await set_status(db, level, obj, CatalogStatus.ARCHIVED)


async def restore(db: AsyncSession, level: str, obj):
    """归档恢复为 active（须通过层级激活校验）。"""
    if obj.status != CatalogStatus.ARCHIVED:
        raise CatalogError("仅归档节点可恢复")
    before = revision_service.snapshot(level, obj)
    obj.status = CatalogStatus.ACTIVE
    await _check_activation(db, level, obj)
    obj.archived_at = None
    await revision_service.record(
        db, entity_type=level, entity_id=obj.id, action="restore",
        before=before, after=revision_service.snapshot(level, obj),
        summary=f"恢复 {level}",
    )
    return await _commit(db, obj)


async def _has_live_children(db: AsyncSession, level: str, obj) -> str | None:
    """返回阻止合并的原因（有子级），否则 None。"""
    if level == "family":
        vcnt = await db.scalar(
            select(func.count()).select_from(ProductVariant).where(
                ProductVariant.family_id == obj.id, ProductVariant.status.notin_(_HIDDEN)
            )
        )
        scnt = await db.scalar(
            select(func.count()).select_from(ProductSKU).where(
                ProductSKU.family_id == obj.id, ProductSKU.status.notin_(_HIDDEN)
            )
        )
        if vcnt or scnt:
            return f"该系列仍有 {int(vcnt or 0)} 变体、{int(scnt or 0)} SKU，请先处理子级"
    elif level == "variant":
        scnt = await db.scalar(
            select(func.count()).select_from(ProductSKU).where(
                ProductSKU.variant_id == obj.id, ProductSKU.status.notin_(_HIDDEN)
            )
        )
        if scnt:
            return f"该变体仍有 {int(scnt)} 个 SKU，请先处理子级再合并"
    return None


async def merge(db: AsyncSession, level: str, source, target_id: int):
    """把 source 合并到 target（同层级）。source 保留（merged, merged_into_id=target）。

    最小安全策略：source 有活跃子级时禁止合并（不做重新挂载）。
    """
    if source.id == target_id:
        raise CatalogError("不允许自合并")
    model = LEVELS[level]
    target = await db.get(model, target_id)
    if target is None:
        raise CatalogError(f"目标 {level} 不存在: {target_id}")
    if target.status == CatalogStatus.MERGED:
        raise CatalogError("目标节点已被合并，请合并到其 canonical 目标")
    if level in ("variant", "sku") and source.family_id != target.family_id:
        raise CatalogError("不允许跨 family 合并")
    # 子级保护（409）
    blocked = await _has_live_children(db, level, source)
    if blocked:
        raise CatalogConflict(blocked)
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
    before = revision_service.snapshot(level, source)
    source.status = CatalogStatus.MERGED
    source.merged_into_id = target.id
    source.archived_at = utcnow()
    await revision_service.record(
        db, entity_type=level, entity_id=source.id, action="merge",
        before=before, after=revision_service.snapshot(level, source),
        summary=f"{level} #{source.id} 合并到 #{target.id}",
    )
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
        alias=alias, normalized_alias=_norm(alias), language=(data.get("language") or None),
        alias_type=alias_type, is_primary=bool(data.get("is_primary")),
    )
    setattr(row, _TARGET_ATTR[level], int(target_id))
    return await _add(db, row, rev_type="alias", rev_summary="创建产品别名")


async def update_alias(db: AsyncSession, alias_id: int, data: dict[str, Any]):
    row = await db.get(ProductCatalogAlias, alias_id)
    if row is None:
        raise CatalogError("别名不存在")
    before = revision_service.snapshot("alias", row)
    if "alias" in data:
        a = (data["alias"] or "").strip()
        if not a:
            raise CatalogError("别名不能为空")
        row.alias = a
        row.normalized_alias = _norm(a)
    if "language" in data:
        row.language = data["language"] or None
    if "alias_type" in data:
        at = (data["alias_type"] or "").strip()
        if at not in CATALOG_ALIAS_TYPES:
            raise CatalogError(f"未知别名类型: {at}")
        row.alias_type = at
    if "is_primary" in data:
        row.is_primary = bool(data["is_primary"])
    await revision_service.record(
        db, entity_type="alias", entity_id=row.id, action="update",
        before=before, after=revision_service.snapshot("alias", row),
        summary="更新产品别名",
    )
    return await _commit(db, row)


async def delete_alias(db: AsyncSession, alias_id: int) -> bool:
    row = await db.get(ProductCatalogAlias, alias_id)
    if row is None:
        return False
    before = revision_service.snapshot("alias", row)
    rid = row.id
    await db.delete(row)
    await revision_service.record(
        db, entity_type="alias", entity_id=rid, action="delete",
        before=before, summary="删除产品别名",
    )
    await db.commit()
    return True
