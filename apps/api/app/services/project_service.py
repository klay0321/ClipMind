"""PR-06A：项目（业务工作空间）业务逻辑。

职责：Project CRUD、归档/恢复（乐观锁）、素材/镜头/产品成员关联（批量添加 + 单条移除 + 重排）、
脚本归属 attach/detach、项目可见镜头并集、项目统计。**不删除任何业务实体**（删关联只删关联行；
Project 本阶段无删除接口）。

安全/正确性要点：
- ``ensure_project_mutable`` 统一归档守卫：归档项目除恢复外的写操作一律 409（service 层兜底，
  不依赖前端）。
- 改名/归档/重排用 ``lock_version`` 乐观锁，条件 UPDATE + rowcount 判定，消除读后写竞态。
- 批量添加：去重 → 一次校验目标 → 区分 completed/skipped(重复)/failed(不存在) → 单事务写入，
  IntegrityError 回滚转 409；重复成员依赖唯一约束实现可靠重试。
- 可见镜头并集在数据库层 UNION + 去重，绝不把全部镜头载入 Python；统计为固定数量聚合查询，
  query 数不随成员规模线性增长。
- 绝不反向删除 Asset/Shot/Product/脚本/AI/搜索/导出数据。
"""

from __future__ import annotations

from typing import Any

from clipmind_shared.db.base import utcnow
from clipmind_shared.models import (
    Asset,
    Collection,
    CollectionShot,
    Product,
    Project,
    ProjectAsset,
    ProjectProduct,
    ProjectShot,
    ScriptExport,
    ScriptProject,
    ScriptSegment,
    Shot,
    ShotSearchDocument,
    ShotTag,
    Tag,
)
from clipmind_shared.models.enums import (
    ExportStatus,
    ProjectStatus,
    ReviewStatus,
    ScriptStatus,
    ShotStatus,
    TagType,
)
from fastapi import HTTPException
from sqlalchemy import Select, delete, exists, func, select, union, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from app.schemas.project import ProjectCreateRequest, ProjectUpdateRequest
from app.services.shot_filter import filter_shots

# 重排时把 order_index 临时挪到的安全偏移（远离任何真实 0..n-1，避免唯一约束中途冲突）
_REORDER_OFFSET = 1_000_000


# ============================ 基础 / 守卫 ============================


async def get_project_or_404(db: AsyncSession, project_id: int) -> Project:
    proj = await db.get(Project, project_id)
    if proj is None:
        raise HTTPException(status_code=404, detail="项目不存在")
    return proj


def ensure_project_mutable(proj: Project) -> None:
    """归档项目除恢复外禁止任何写操作。"""
    if proj.status == ProjectStatus.ARCHIVED:
        raise HTTPException(
            status_code=409, detail="项目已归档，禁止修改（仅可恢复后再操作）"
        )


# ============================ 可见镜头并集 ============================


def _visible_shot_ids(project_id: int, source: str = "all") -> Select:
    """项目可见镜头 shot_id 子查询（去重并集）。

    并集来源：ProjectAsset 关联素材的镜头 ∪ ProjectShot 显式镜头 ∪ Project 下 CollectionShot。
    ``source`` 可限定单一来源（asset/explicit/collection）。镜头 READY 过滤由调用方
    （filter_shots 或计数）统一施加。
    """
    sa = aliased(Shot)
    asset_q = (
        select(sa.id.label("shot_id"))
        .select_from(ProjectAsset)
        .join(sa, sa.asset_id == ProjectAsset.asset_id)
        .where(ProjectAsset.project_id == project_id)
    )
    explicit_q = select(ProjectShot.shot_id.label("shot_id")).where(
        ProjectShot.project_id == project_id
    )
    coll_q = (
        select(CollectionShot.shot_id.label("shot_id"))
        .select_from(CollectionShot)
        .join(Collection, Collection.id == CollectionShot.collection_id)
        .where(Collection.project_id == project_id)
    )
    if source == "asset":
        return asset_q
    if source == "explicit":
        return explicit_q
    if source == "collection":
        return coll_q
    u = union(asset_q, explicit_q, coll_q).subquery()
    return select(u.c.shot_id)


# ============================ CRUD ============================


async def create_project(db: AsyncSession, req: ProjectCreateRequest) -> Project:
    proj = Project(
        name=req.name,
        description=req.description,
        status=ProjectStatus.ACTIVE,
        lock_version=1,
    )
    db.add(proj)
    await db.commit()
    await db.refresh(proj)
    return proj


async def list_projects(
    db: AsyncSession, *, page: int, page_size: int, status: ProjectStatus | None
) -> tuple[list[Project], int]:
    base = select(Project)
    count_base = select(func.count(Project.id))
    if status is not None:
        base = base.where(Project.status == status)
        count_base = count_base.where(Project.status == status)
    total = int(await db.scalar(count_base) or 0)
    rows = (
        await db.scalars(
            base.order_by(Project.created_at.desc(), Project.id.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
    ).all()
    return list(rows), total


async def update_project(
    db: AsyncSession, project_id: int, req: ProjectUpdateRequest
) -> Project:
    proj = await get_project_or_404(db, project_id)
    ensure_project_mutable(proj)

    provided = req.model_fields_set - {"lock_version"}
    if not provided:
        raise HTTPException(status_code=422, detail="无可更新字段")

    values: dict[str, Any] = {}
    if "name" in provided:
        values["name"] = req.name
    if "description" in provided:
        values["description"] = req.description
    values["lock_version"] = req.lock_version + 1
    values["updated_at"] = utcnow()

    result = await db.execute(
        update(Project)
        .where(
            Project.id == project_id,
            Project.lock_version == req.lock_version,
            Project.status == ProjectStatus.ACTIVE,
        )
        .values(**values)
    )
    if result.rowcount == 0:
        await db.rollback()
        await _raise_lock_or_archived(db, project_id)
    await db.commit()
    await db.refresh(proj)
    return proj


async def _raise_lock_or_archived(db: AsyncSession, project_id: int) -> None:
    """条件 UPDATE 未命中时区分原因：已归档 vs lock_version 不匹配。"""
    fresh = await db.get(Project, project_id)
    if fresh is None:
        raise HTTPException(status_code=404, detail="项目不存在")
    if fresh.status == ProjectStatus.ARCHIVED:
        raise HTTPException(status_code=409, detail="项目已归档，禁止修改（仅可恢复后再操作）")
    raise HTTPException(
        status_code=409, detail="项目已被更新（lock_version 不匹配），请刷新后重试"
    )


async def archive_project(db: AsyncSession, project_id: int, lock_version: int) -> Project:
    """归档（乐观锁）。已归档则幂等返回；active 但 lock 不匹配返回 409。"""
    result = await db.execute(
        update(Project)
        .where(
            Project.id == project_id,
            Project.lock_version == lock_version,
            Project.status == ProjectStatus.ACTIVE,
        )
        .values(
            status=ProjectStatus.ARCHIVED,
            archived_at=utcnow(),
            lock_version=lock_version + 1,
            updated_at=utcnow(),
        )
    )
    if result.rowcount == 0:
        await db.rollback()
        fresh = await get_project_or_404(db, project_id)
        if fresh.status == ProjectStatus.ARCHIVED:
            return fresh  # 幂等：已归档
        raise HTTPException(
            status_code=409, detail="项目已被更新（lock_version 不匹配），请刷新后重试"
        )
    await db.commit()
    return await get_project_or_404(db, project_id)


async def unarchive_project(db: AsyncSession, project_id: int, lock_version: int) -> Project:
    """恢复（乐观锁）。已 active 则幂等返回；archived 但 lock 不匹配返回 409。"""
    result = await db.execute(
        update(Project)
        .where(
            Project.id == project_id,
            Project.lock_version == lock_version,
            Project.status == ProjectStatus.ARCHIVED,
        )
        .values(
            status=ProjectStatus.ACTIVE,
            archived_at=None,
            lock_version=lock_version + 1,
            updated_at=utcnow(),
        )
    )
    if result.rowcount == 0:
        await db.rollback()
        fresh = await get_project_or_404(db, project_id)
        if fresh.status == ProjectStatus.ACTIVE:
            return fresh  # 幂等：已是 active
        raise HTTPException(
            status_code=409, detail="项目已被更新（lock_version 不匹配），请刷新后重试"
        )
    await db.commit()
    return await get_project_or_404(db, project_id)


# ============================ 成员：素材 / 镜头 / 产品 ============================


async def _batch_add(
    db: AsyncSession,
    *,
    project_id: int,
    assoc_model: type,
    fk_attr: str,
    target_model: type,
    target_label: str,
    ids: list[int],
    ordered: bool,
) -> dict[str, list]:
    """批量加入成员（项目已校验可变）。返回 completed/skipped/failed。"""
    req_ids = list(dict.fromkeys(ids))  # 去重保序
    fk_col = getattr(assoc_model, fk_attr)

    existing_targets = set(
        await db.scalars(select(target_model.id).where(target_model.id.in_(req_ids)))
    )
    member_ids = set(
        await db.scalars(
            select(fk_col).where(assoc_model.project_id == project_id, fk_col.in_(req_ids))
        )
    )

    completed: list[int] = []
    skipped: list[int] = []
    failed: list[dict] = []
    to_add: list[int] = []
    for tid in req_ids:
        if tid not in existing_targets:
            failed.append({"id": tid, "error": f"{target_label}不存在"})
        elif tid in member_ids:
            skipped.append(tid)
        else:
            to_add.append(tid)

    next_order = 0
    if ordered and to_add:
        max_order = await db.scalar(
            select(func.max(assoc_model.order_index)).where(
                assoc_model.project_id == project_id
            )
        )
        next_order = (max_order + 1) if max_order is not None else 0

    for tid in to_add:
        kwargs: dict[str, Any] = {"project_id": project_id, fk_attr: tid}
        if ordered:
            kwargs["order_index"] = next_order
            next_order += 1
        db.add(assoc_model(**kwargs))
        completed.append(tid)

    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(
            status_code=409, detail="成员关联并发冲突，请刷新后重试"
        ) from None
    return {"completed": completed, "skipped": skipped, "failed": failed}


async def add_project_assets(db: AsyncSession, project_id: int, ids: list[int]) -> dict:
    proj = await get_project_or_404(db, project_id)
    ensure_project_mutable(proj)
    return await _batch_add(
        db, project_id=project_id, assoc_model=ProjectAsset, fk_attr="asset_id",
        target_model=Asset, target_label="素材", ids=ids, ordered=True,
    )


async def add_project_shots(db: AsyncSession, project_id: int, ids: list[int]) -> dict:
    proj = await get_project_or_404(db, project_id)
    ensure_project_mutable(proj)
    return await _batch_add(
        db, project_id=project_id, assoc_model=ProjectShot, fk_attr="shot_id",
        target_model=Shot, target_label="镜头", ids=ids, ordered=True,
    )


async def add_project_products(db: AsyncSession, project_id: int, ids: list[int]) -> dict:
    proj = await get_project_or_404(db, project_id)
    ensure_project_mutable(proj)
    return await _batch_add(
        db, project_id=project_id, assoc_model=ProjectProduct, fk_attr="product_id",
        target_model=Product, target_label="产品", ids=ids, ordered=False,
    )


async def _remove_member(
    db: AsyncSession, *, project_id: int, assoc_model: type, fk_attr: str, target_id: int
) -> None:
    proj = await get_project_or_404(db, project_id)
    ensure_project_mutable(proj)
    fk_col = getattr(assoc_model, fk_attr)
    result = await db.execute(
        delete(assoc_model).where(assoc_model.project_id == project_id, fk_col == target_id)
    )
    if result.rowcount == 0:
        raise HTTPException(status_code=404, detail="项目成员关联不存在")
    await db.commit()


async def remove_project_asset(db: AsyncSession, project_id: int, asset_id: int) -> None:
    await _remove_member(
        db, project_id=project_id, assoc_model=ProjectAsset, fk_attr="asset_id", target_id=asset_id
    )


async def remove_project_shot(db: AsyncSession, project_id: int, shot_id: int) -> None:
    await _remove_member(
        db, project_id=project_id, assoc_model=ProjectShot, fk_attr="shot_id", target_id=shot_id
    )


async def remove_project_product(db: AsyncSession, project_id: int, product_id: int) -> None:
    await _remove_member(
        db, project_id=project_id, assoc_model=ProjectProduct, fk_attr="product_id",
        target_id=product_id,
    )


async def _reorder_members(
    db: AsyncSession,
    *,
    project_id: int,
    assoc_model: type,
    fk_attr: str,
    requested_ids: list[int],
    lock_version: int,
) -> Project:
    proj = await get_project_or_404(db, project_id)
    ensure_project_mutable(proj)
    members = (
        await db.scalars(select(assoc_model).where(assoc_model.project_id == project_id))
    ).all()
    by_target = {getattr(m, fk_attr): m for m in members}

    if len(requested_ids) != len(set(requested_ids)):
        raise HTTPException(status_code=422, detail="重排列表含重复 id")
    if set(requested_ids) != set(by_target):
        raise HTTPException(status_code=422, detail="重排列表必须恰好覆盖该项目的全部成员")

    # 乐观锁 + 归档守卫（原子）：项目 lock_version 条件 UPDATE
    result = await db.execute(
        update(Project)
        .where(
            Project.id == project_id,
            Project.lock_version == lock_version,
            Project.status == ProjectStatus.ACTIVE,
        )
        .values(lock_version=lock_version + 1, updated_at=utcnow())
    )
    if result.rowcount == 0:
        await db.rollback()
        await _raise_lock_or_archived(db, project_id)

    # 两阶段：先挪到安全偏移避免唯一约束中途冲突，再写最终 0..n-1
    for m in members:
        m.order_index = m.order_index + _REORDER_OFFSET
    await db.flush()
    for idx, tid in enumerate(requested_ids):
        by_target[tid].order_index = idx
    await db.commit()
    await db.refresh(proj)
    return proj


async def reorder_project_assets(
    db: AsyncSession, project_id: int, requested_ids: list[int], lock_version: int
) -> Project:
    return await _reorder_members(
        db, project_id=project_id, assoc_model=ProjectAsset, fk_attr="asset_id",
        requested_ids=requested_ids, lock_version=lock_version,
    )


async def reorder_project_shots(
    db: AsyncSession, project_id: int, requested_ids: list[int], lock_version: int
) -> Project:
    return await _reorder_members(
        db, project_id=project_id, assoc_model=ProjectShot, fk_attr="shot_id",
        requested_ids=requested_ids, lock_version=lock_version,
    )


# ============================ 成员列表 ============================


async def list_project_assets(
    db: AsyncSession, project_id: int, *, page: int, page_size: int
) -> tuple[list[tuple[int, Asset]], int, dict[int, int]]:
    await get_project_or_404(db, project_id)
    total = int(
        await db.scalar(
            select(func.count(ProjectAsset.id)).where(ProjectAsset.project_id == project_id)
        )
        or 0
    )
    rows = (
        await db.execute(
            select(ProjectAsset.order_index, Asset)
            .join(Asset, Asset.id == ProjectAsset.asset_id)
            .where(ProjectAsset.project_id == project_id)
            .order_by(ProjectAsset.order_index, ProjectAsset.id)
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
    ).all()
    items = [(r[0], r[1]) for r in rows]
    asset_ids = [a.id for _, a in items]
    shot_counts: dict[int, int] = {}
    if asset_ids:
        cnt_rows = (
            await db.execute(
                select(Shot.asset_id, func.count(Shot.id))
                .where(
                    Shot.asset_id.in_(asset_ids),
                    Shot.status == ShotStatus.READY,
                    Shot.retired_at.is_(None),
                )
                .group_by(Shot.asset_id)
            )
        ).all()
        shot_counts = {aid: c for aid, c in cnt_rows}
    return items, total, shot_counts


async def list_project_products(
    db: AsyncSession, project_id: int, *, page: int, page_size: int
) -> tuple[list[Product], int]:
    await get_project_or_404(db, project_id)
    total = int(
        await db.scalar(
            select(func.count(ProjectProduct.id)).where(
                ProjectProduct.project_id == project_id
            )
        )
        or 0
    )
    rows = (
        await db.scalars(
            select(Product)
            .join(ProjectProduct, ProjectProduct.product_id == Product.id)
            .where(ProjectProduct.project_id == project_id)
            .order_by(ProjectProduct.created_at.asc(), ProjectProduct.id.asc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
    ).all()
    return list(rows), total


async def list_project_shots(
    db: AsyncSession,
    project_id: int,
    *,
    source: str,
    page: int,
    page_size: int,
    sort: str,
    product_id: int | None,
    review_status: ReviewStatus | None,
    risk: str | None,
    include_excluded: bool,
) -> tuple[list[Shot], int]:
    await get_project_or_404(db, project_id)

    # 显式来源 + 手工顺序：直接按 project_shot.order_index 排序（其余来源无单一手工序）
    if source == "explicit" and sort == "order":
        base = (
            select(Shot)
            .join(ProjectShot, ProjectShot.shot_id == Shot.id)
            .where(
                ProjectShot.project_id == project_id,
                Shot.status == ShotStatus.READY,
                Shot.retired_at.is_(None),
            )
        )
        total = int(
            (await db.execute(select(func.count()).select_from(base.subquery()))).scalar() or 0
        )
        rows = (
            await db.scalars(
                base.order_by(ProjectShot.order_index, Shot.id)
                .offset((page - 1) * page_size)
                .limit(page_size)
            )
        ).all()
        return list(rows), total

    restrict = _visible_shot_ids(project_id, source)
    has_content_filter = (
        product_id is not None or review_status is not None or risk is not None
    )
    # 快路径（无内容过滤、非 confidence 排序）：ready + 并集，无 outerjoin；
    # 口径与统计 visible_shot_count 一致（不按审核状态排除），且在大项目下计划稳定。
    if not has_content_filter and sort != "confidence":
        base = select(Shot).where(
            Shot.status == ShotStatus.READY, Shot.retired_at.is_(None), Shot.id.in_(restrict)
        )
        total = int(
            (await db.execute(select(func.count()).select_from(base.subquery()))).scalar()
            or 0
        )
        if sort == "newest":
            base = base.order_by(Shot.created_at.desc(), Shot.id.desc())
        else:  # sequence
            base = base.order_by(Shot.asset_id.asc(), Shot.sequence_no.asc(), Shot.id.asc())
        rows = (
            await db.scalars(base.offset((page - 1) * page_size).limit(page_size))
        ).all()
        return list(rows), total

    # 有内容过滤：复用 shot_filter（产品/审核/风险/内容标签 + 默认排除 rejected/unable）
    return await filter_shots(
        db,
        review_status=review_status,
        product_id=product_id,
        risk=risk,
        include_excluded=include_excluded,
        restrict_shot_ids=restrict,
        sort=sort if sort in ("sequence", "newest", "confidence") else "sequence",
        page=page,
        page_size=page_size,
    )


# ============================ 脚本归属 ============================


async def attach_script(
    db: AsyncSession, project_id: int, script_id: int
) -> ScriptProject:
    proj = await get_project_or_404(db, project_id)
    ensure_project_mutable(proj)
    script = await db.get(ScriptProject, script_id)
    if script is None:
        raise HTTPException(status_code=404, detail="脚本项目不存在")
    if script.project_id == project_id:
        return script  # 幂等
    script.project_id = project_id
    await db.commit()
    await db.refresh(script)
    return script


async def detach_script(
    db: AsyncSession, project_id: int, script_id: int
) -> ScriptProject:
    proj = await get_project_or_404(db, project_id)
    ensure_project_mutable(proj)
    script = await db.get(ScriptProject, script_id)
    if script is None or script.project_id != project_id:
        raise HTTPException(status_code=404, detail="该项目下不存在此脚本")
    script.project_id = None
    await db.commit()
    await db.refresh(script)
    return script


async def list_project_scripts(
    db: AsyncSession, project_id: int, *, page: int, page_size: int
) -> tuple[list[ScriptProject], int]:
    await get_project_or_404(db, project_id)
    total = int(
        await db.scalar(
            select(func.count(ScriptProject.id)).where(
                ScriptProject.project_id == project_id
            )
        )
        or 0
    )
    rows = (
        await db.scalars(
            select(ScriptProject)
            .where(ScriptProject.project_id == project_id)
            .order_by(ScriptProject.created_at.desc(), ScriptProject.id.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
    ).all()
    return list(rows), total


# ============================ 统计（单条固定聚合查询）============================


async def get_project_stats(db: AsyncSession, project_id: int) -> dict[str, Any]:
    """固定 2 条聚合查询：① 成员/脚本计数；② 可见镜头并集去重一次 + risk/searchable 单遍 FILTER。

    避免对可见镜头并集重复去重三次（旧实现的热点），保证查询数固定、不随成员规模线性增长。
    """
    proj = await get_project_or_404(db, project_id)

    # ---- 查询 1：成员/脚本计数（标量子查询，索引计数，便宜）----
    counts_stmt = select(
        select(func.count(ProjectAsset.id))
        .where(ProjectAsset.project_id == project_id)
        .scalar_subquery()
        .label("asset_count"),
        select(func.count(ProjectShot.id))
        .where(ProjectShot.project_id == project_id)
        .scalar_subquery()
        .label("explicit_shot_count"),
        select(func.count(Collection.id))
        .where(Collection.project_id == project_id)
        .scalar_subquery()
        .label("collection_count"),
        select(func.count(CollectionShot.id))
        .select_from(CollectionShot)
        .join(Collection, Collection.id == CollectionShot.collection_id)
        .where(Collection.project_id == project_id)
        .scalar_subquery()
        .label("collection_shot_count"),
        select(func.count(ProjectProduct.id))
        .where(ProjectProduct.project_id == project_id)
        .scalar_subquery()
        .label("product_count"),
        select(func.count(ScriptProject.id))
        .where(ScriptProject.project_id == project_id)
        .scalar_subquery()
        .label("script_count"),
        select(func.count(ScriptProject.id))
        .where(
            ScriptProject.project_id == project_id,
            ScriptProject.status != ScriptStatus.FAILED,
        )
        .scalar_subquery()
        .label("active_script_count"),
        select(func.count(ScriptSegment.id))
        .select_from(ScriptSegment)
        .join(ScriptProject, ScriptProject.id == ScriptSegment.script_project_id)
        .where(
            ScriptProject.project_id == project_id,
            ScriptSegment.locked_shot_id.isnot(None),
        )
        .scalar_subquery()
        .label("locked_segment_count"),
        select(func.count(ScriptSegment.id))
        .select_from(ScriptSegment)
        .join(ScriptProject, ScriptProject.id == ScriptSegment.script_project_id)
        .where(
            ScriptProject.project_id == project_id,
            ScriptSegment.match_status == "gap",
        )
        .scalar_subquery()
        .label("gap_segment_count"),
        select(func.count(ScriptExport.id))
        .select_from(ScriptExport)
        .join(ScriptProject, ScriptProject.id == ScriptExport.script_project_id)
        .where(
            ScriptProject.project_id == project_id,
            ScriptExport.status == ExportStatus.COMPLETED,
        )
        .scalar_subquery()
        .label("completed_script_export_count"),
    )
    counts = (await db.execute(counts_stmt)).one()

    # ---- 查询 2：可见镜头并集去重一次（CTE），再对其单遍统计 visible/risk/searchable ----
    vis = (
        select(Shot.id.label("sid"))
        .where(
            Shot.status == ShotStatus.READY,
            Shot.retired_at.is_(None),
            Shot.id.in_(_visible_shot_ids(project_id)),
        )
        .distinct()
        .cte("vis")
    )
    risk_filter = exists(
        select(ShotTag.id)
        .join(Tag, Tag.id == ShotTag.tag_id)
        .where(
            ShotTag.shot_id == vis.c.sid,
            ShotTag.active.is_(True),
            Tag.tag_type == TagType.RISK,
        )
    )
    searchable_filter = exists(
        select(ShotSearchDocument.id).where(
            ShotSearchDocument.shot_id == vis.c.sid,
            ShotSearchDocument.is_searchable.is_(True),
        )
    )
    vis_stmt = select(
        func.count().label("visible_shot_count"),
        func.count().filter(risk_filter).label("risk_shot_count"),
        func.count().filter(searchable_filter).label("searchable_shot_count"),
    ).select_from(vis)
    vrow = (await db.execute(vis_stmt)).one()

    data: dict[str, Any] = dict(counts._mapping)
    data.update(dict(vrow._mapping))
    data["project_id"] = project_id
    data["updated_at"] = proj.updated_at
    return data
