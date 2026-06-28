"""PR-05 Gate A：脚本项目 / 段落 业务逻辑。

职责：创建（按内容哈希幂等）、拆段（解析器→事务替换段落）、读取、改名、单段编辑（乐观锁）、
段落重排。**不做镜头匹配**（Gate B）。

安全/正确性要点：
- LLM 解析结果只落到受控字段（见 ``ParsedScript`` 校验），绝不直接拼 SQL。
- 重新拆段对**已锁定段落**不静默丢失锁定：存在锁定/候选时须显式 ``force``。
- 单段编辑用 ``lock_version`` 乐观锁；编辑影响需求的字段则标记候选过期（Gate A 不重匹配）。
- 重排在事务内两阶段更新 ``order_index``，避免唯一约束中途冲突；非法集合拒绝。
"""

from __future__ import annotations

import hashlib

from clipmind_shared.db.base import utcnow
from clipmind_shared.models import Product, ScriptProject, ScriptSegment, Shot
from clipmind_shared.models.enums import ScriptParseStatus, ScriptStatus
from clipmind_shared.review.normalize import normalize_name
from clipmind_shared.script.parser import ScriptParser
from clipmind_shared.script.schema import (
    MAX_SCRIPT_LENGTH,
    ParsedScript,
    ParsedScriptSegment,
)
from fastapi import HTTPException
from fastapi.concurrency import run_in_threadpool
from sqlalchemy import delete, func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.schemas.script import (
    ScriptCreateRequest,
    SegmentReorderRequest,
    SegmentUpdateRequest,
)

# 编辑后会使已有候选过期（需 Gate B 重匹配）的字段
_REQUIREMENT_FIELDS = frozenset(
    {
        "segment_text",
        "visual_requirement",
        "target_duration_min",
        "target_duration_max",
        "product_id",
        "structured_requirements",
        "negative_terms",
        "excluded_risks",
        "allow_similar_scene",
        "allow_similar_action",
    }
)
# 重排时把 order_index 临时挪到的安全偏移（远离任何真实 0..n-1）
_REORDER_OFFSET = 1_000_000


def _compute_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _structured_from_parsed(seg: ParsedScriptSegment) -> dict:
    """把解析段落的结构化字段（除已单列的）打包为 structured_requirements。"""
    return {
        "products": seg.products,
        "scenes": seg.scenes,
        "actions": seg.actions,
        "shot_types": seg.shot_types,
        "marketing_uses": seg.marketing_uses,
        "people": seg.people,
        "objects": seg.objects,
        "quality_requirements": seg.quality_requirements,
        "selling_points": seg.selling_points,
        "must_include": seg.must_include,
    }


async def _segment_count(db: AsyncSession, project_id: int) -> int:
    return int(
        await db.scalar(
            select(func.count(ScriptSegment.id)).where(
                ScriptSegment.script_project_id == project_id
            )
        )
        or 0
    )


async def get_project_or_404(db: AsyncSession, project_id: int) -> ScriptProject:
    proj = await db.get(ScriptProject, project_id)
    if proj is None:
        raise HTTPException(status_code=404, detail="脚本项目不存在")
    return proj


async def create_script(db: AsyncSession, req: ScriptCreateRequest) -> ScriptProject:
    raw = req.raw_script.strip()
    if not raw:
        raise HTTPException(status_code=422, detail="脚本内容不能为空")
    if len(raw) > MAX_SCRIPT_LENGTH:
        raise HTTPException(
            status_code=422, detail=f"脚本过长（上限 {MAX_SCRIPT_LENGTH} 字符）"
        )
    script_hash = _compute_hash(raw)
    # 幂等：相同内容已存在则复用，不重复创建项目
    existing = await db.scalar(
        select(ScriptProject).where(ScriptProject.script_hash == script_hash).limit(1)
    )
    if existing is not None:
        return existing

    proj = ScriptProject(
        name=req.name.strip(),
        raw_script=raw,
        normalized_script=normalize_name(raw),
        script_hash=script_hash,
        source_format=(req.source_format or "paste").strip()[:16] or "paste",
        status=ScriptStatus.DRAFT,
        parse_status=ScriptParseStatus.PENDING,
    )
    db.add(proj)
    try:
        await db.commit()
    except IntegrityError:
        # 并发：另一请求已用相同 hash 抢先插入（DB 唯一约束兜底）→ 复用既有项目
        await db.rollback()
        dup = await db.scalar(
            select(ScriptProject).where(ScriptProject.script_hash == script_hash).limit(1)
        )
        if dup is not None:
            return dup
        raise
    await db.refresh(proj)
    return proj


async def parse_script(
    db: AsyncSession,
    project_id: int,
    parser: ScriptParser,
    *,
    force: bool = False,
) -> ScriptProject:
    """拆段：解析器→事务替换段落。存在锁定段落且非 force 时拒绝（不静默丢锁）。"""
    proj = await get_project_or_404(db, project_id)

    existing = (
        await db.scalars(
            select(ScriptSegment).where(ScriptSegment.script_project_id == project_id)
        )
    ).all()
    locked_count = sum(1 for s in existing if s.locked_shot_id is not None)
    if existing and not force and locked_count:
        raise HTTPException(
            status_code=409,
            detail="存在已锁定段落，重新拆段会丢失锁定；如确需重新拆段请传 force=true",
        )

    # 解析（同步解析器在 threadpool 调用，避免阻塞事件循环；MiMo 失败内部降级）
    parsed: ParsedScript = await run_in_threadpool(parser.parse, proj.raw_script)

    # 事务替换：删除旧段落（级联删候选）→ 写入新段落
    await db.execute(
        delete(ScriptSegment).where(ScriptSegment.script_project_id == project_id)
    )
    for seg in parsed.segments:
        db.add(
            ScriptSegment(
                script_project_id=project_id,
                order_index=seg.order_index,
                segment_text=seg.text,
                normalized_text=seg.normalized_text,
                visual_requirement=seg.visual_requirement,
                target_duration_min=seg.target_duration_min,
                target_duration_max=seg.target_duration_max,
                structured_requirements=_structured_from_parsed(seg),
                negative_terms=seg.negative_terms,
                excluded_risks=seg.excluded_risks,
                allow_similar_scene=seg.allow_similar_scene,
                allow_similar_action=seg.allow_similar_action,
                current_generation=1,
                parser_warnings=seg.parser_warnings or None,
            )
        )

    warnings = list(parsed.parser_warnings or [])
    if force and locked_count:
        # force 重拆段不再静默：显式告知丢失了多少个锁定段
        warnings.append(f"forced_reparse_cleared_{locked_count}_locked_segments")
    proj.parse_status = parsed.parser_status
    proj.parser_provider = parsed.parser_provider
    proj.parser_model = parsed.parser_model
    proj.parser_warnings = warnings or None
    proj.result_schema_version = parsed.schema_version
    proj.status = (
        ScriptStatus.PARSED if parsed.segments else ScriptStatus.FAILED
    )
    await db.commit()
    await db.refresh(proj)
    return proj


async def list_segments(db: AsyncSession, project_id: int) -> list[ScriptSegment]:
    rows = await db.scalars(
        select(ScriptSegment)
        .where(ScriptSegment.script_project_id == project_id)
        .order_by(ScriptSegment.order_index)
    )
    return list(rows.all())


async def list_scripts(
    db: AsyncSession, page: int, page_size: int
) -> tuple[list[ScriptProject], list[int], int]:
    total = int(await db.scalar(select(func.count(ScriptProject.id))) or 0)
    rows = (
        await db.scalars(
            select(ScriptProject)
            .order_by(ScriptProject.created_at.desc(), ScriptProject.id.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
    ).all()
    counts = []
    for p in rows:
        counts.append(await _segment_count(db, p.id))
    return list(rows), counts, total


async def update_script_name(
    db: AsyncSession, project_id: int, name: str
) -> ScriptProject:
    proj = await get_project_or_404(db, project_id)
    proj.name = name.strip()
    await db.commit()
    await db.refresh(proj)
    return proj


async def update_segment(
    db: AsyncSession,
    project_id: int,
    segment_id: int,
    req: SegmentUpdateRequest,
) -> ScriptSegment:
    seg = await db.get(ScriptSegment, segment_id)
    if seg is None or seg.script_project_id != project_id:
        raise HTTPException(status_code=404, detail="脚本段落不存在")

    provided = req.model_fields_set - {"lock_version"}
    # 校验外键存在性（避免依赖 DB 错误）
    if "locked_shot_id" in provided and req.locked_shot_id is not None:
        if await db.get(Shot, req.locked_shot_id) is None:
            raise HTTPException(status_code=422, detail="锁定的镜头不存在")
    if "product_id" in provided and req.product_id is not None:
        if await db.get(Product, req.product_id) is None:
            raise HTTPException(status_code=422, detail="指定的产品不存在")

    values: dict = {}
    requirement_changed = False
    for field in provided:
        value = getattr(req, field)
        if field == "segment_text":
            if not (value or "").strip():
                raise HTTPException(status_code=422, detail="段落文案不能为空")
            values["segment_text"] = value.strip()
            values["normalized_text"] = normalize_name(value.strip())
        else:
            values[field] = value
        if field in _REQUIREMENT_FIELDS:
            requirement_changed = True

    if requirement_changed:
        values["candidates_stale"] = True  # 提示需 Gate B 重匹配；Gate A 不自动重匹配
    values["lock_version"] = req.lock_version + 1
    values["updated_at"] = utcnow()

    # 乐观锁在 DB 层原子完成：条件 UPDATE + rowcount 判定，消除读后写的 TOCTOU 竞态
    result = await db.execute(
        update(ScriptSegment)
        .where(
            ScriptSegment.id == segment_id,
            ScriptSegment.lock_version == req.lock_version,
        )
        .values(**values)
    )
    if result.rowcount == 0:
        await db.rollback()
        raise HTTPException(
            status_code=409, detail="段落已被更新（lock_version 不匹配），请刷新后重试"
        )
    await db.commit()
    await db.refresh(seg)
    return seg


async def reorder_segments(
    db: AsyncSession, project_id: int, req: SegmentReorderRequest
) -> list[ScriptSegment]:
    await get_project_or_404(db, project_id)
    segs = await list_segments(db, project_id)
    existing_ids = {s.id for s in segs}
    requested = req.segment_ids
    if len(requested) != len(set(requested)):
        raise HTTPException(status_code=422, detail="重排列表含重复段落 id")
    if set(requested) != existing_ids:
        raise HTTPException(
            status_code=422, detail="重排列表必须恰好覆盖该项目的全部段落"
        )

    by_id = {s.id: s for s in segs}
    # 两阶段：先挪到安全偏移避免唯一约束中途冲突，flush；再写最终 0..n-1
    for s in segs:
        s.order_index = s.order_index + _REORDER_OFFSET
    await db.flush()
    for new_idx, sid in enumerate(requested):
        by_id[sid].order_index = new_idx
    await db.commit()
    return await list_segments(db, project_id)
