"""PR-05 Gate A：脚本项目 / 段落 路由（注册前缀 /api，见 main.py）。

Gate A 只覆盖：创建脚本、拆段、读取、改名、单段编辑、段落重排。
**不返回伪造候选、不自动匹配、不自动写 locked_shot_id、不接受任意 SQL 字段/任意 task 名。**
匹配（候选/选择/锁定执行/重匹配/导出）见 Gate B。
"""

from __future__ import annotations

from clipmind_shared.script.parser import get_script_parser
from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings, get_settings
from app.db import get_db
from app.schemas.script import (
    ScriptCreateRequest,
    ScriptDetailOut,
    ScriptListResponse,
    ScriptParseRequest,
    ScriptProjectOut,
    ScriptSegmentOut,
    ScriptUpdateRequest,
    SegmentReorderRequest,
    SegmentUpdateRequest,
)
from app.services import script_service
from app.services.script_providers import get_script_parser_for_settings

router = APIRouter(prefix="/scripts", tags=["scripts"])


def _to_project_out(proj, segment_count: int) -> ScriptProjectOut:
    out = ScriptProjectOut.model_validate(proj)
    out.segment_count = segment_count
    return out


@router.post("", response_model=ScriptProjectOut, status_code=status.HTTP_201_CREATED)
async def create_script(
    req: ScriptCreateRequest,
    db: AsyncSession = Depends(get_db),
) -> ScriptProjectOut:
    proj = await script_service.create_script(db, req)
    count = await script_service._segment_count(db, proj.id)
    return _to_project_out(proj, count)


@router.get("", response_model=ScriptListResponse)
async def list_scripts(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
) -> ScriptListResponse:
    rows, counts, total = await script_service.list_scripts(db, page, page_size)
    items = [_to_project_out(p, c) for p, c in zip(rows, counts, strict=True)]
    return ScriptListResponse(items=items, total=total, page=page, page_size=page_size)


@router.get("/{script_id}", response_model=ScriptDetailOut)
async def get_script(
    script_id: int,
    db: AsyncSession = Depends(get_db),
) -> ScriptDetailOut:
    proj = await script_service.get_project_or_404(db, script_id)
    segs = await script_service.list_segments(db, script_id)
    out = ScriptDetailOut.model_validate(proj)
    out.segment_count = len(segs)
    out.segments = [ScriptSegmentOut.model_validate(s) for s in segs]
    return out


@router.patch("/{script_id}", response_model=ScriptProjectOut)
async def update_script(
    script_id: int,
    req: ScriptUpdateRequest,
    db: AsyncSession = Depends(get_db),
) -> ScriptProjectOut:
    if req.name is not None:
        proj = await script_service.update_script_name(db, script_id, req.name)
    else:
        proj = await script_service.get_project_or_404(db, script_id)
    count = await script_service._segment_count(db, proj.id)
    return _to_project_out(proj, count)


@router.post("/{script_id}/parse", response_model=ScriptDetailOut)
async def parse_script(
    script_id: int,
    req: ScriptParseRequest | None = None,
    force: bool = Query(False, description="存在锁定段落时仍强制重新拆段（会丢失锁定）"),
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> ScriptDetailOut:
    override = (req.parser if req else None) or ""
    if override.strip().lower() in ("rulebased", "fake", "mimo"):
        parser = get_script_parser(
            override.strip().lower(),
            base_url=settings.ai_base_url,
            api_key=settings.ai_api_key,
            model=settings.script_parser_model or settings.ai_model or None,
            timeout=settings.script_parser_timeout,
            api_key_header=settings.ai_api_key_header,
        )
    else:
        parser = get_script_parser_for_settings(settings)
    proj = await script_service.parse_script(db, script_id, parser, force=force)
    segs = await script_service.list_segments(db, script_id)
    out = ScriptDetailOut.model_validate(proj)
    out.segment_count = len(segs)
    out.segments = [ScriptSegmentOut.model_validate(s) for s in segs]
    return out


@router.patch(
    "/{script_id}/segments/{segment_id}", response_model=ScriptSegmentOut
)
async def update_segment(
    script_id: int,
    segment_id: int,
    req: SegmentUpdateRequest,
    db: AsyncSession = Depends(get_db),
) -> ScriptSegmentOut:
    seg = await script_service.update_segment(db, script_id, segment_id, req)
    return ScriptSegmentOut.model_validate(seg)


@router.post("/{script_id}/segments/reorder", response_model=ScriptDetailOut)
async def reorder_segments(
    script_id: int,
    req: SegmentReorderRequest,
    db: AsyncSession = Depends(get_db),
) -> ScriptDetailOut:
    segs = await script_service.reorder_segments(db, script_id, req)
    proj = await script_service.get_project_or_404(db, script_id)
    out = ScriptDetailOut.model_validate(proj)
    out.segment_count = len(segs)
    out.segments = [ScriptSegmentOut.model_validate(s) for s in segs]
    return out
