"""PR-05 脚本项目 / 段落 / 镜头匹配 路由（注册前缀 /api，见 main.py）。

Gate A：创建脚本、拆段、读取、改名、单段编辑、段落重排。
Gate B：全脚本/单段候选匹配（复用描述匹配）、候选查询、人工选择/锁定/解锁、匹配状态、
        剪辑清单、CSV 导出。**不返回伪造候选、不让 LLM 决定 shot_id、不反向改镜头审核状态、
        不接受任意 SQL 字段/任意 task 名。**
"""

from __future__ import annotations

from clipmind_shared.models import ScriptExport
from clipmind_shared.models.enums import ExportStatus
from clipmind_shared.script.parser import get_script_parser
from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import FileResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings, get_settings
from app.db import get_db
from app.schemas.script import (
    EditListResponse,
    EditListRowOut,
    EditListSummaryOut,
    ScriptCandidateOut,
    ScriptCreateRequest,
    ScriptDetailOut,
    ScriptExportOut,
    ScriptListResponse,
    ScriptMatchRequest,
    ScriptMatchResponse,
    ScriptMatchStatusResponse,
    ScriptParseRequest,
    ScriptProjectOut,
    ScriptSegmentOut,
    ScriptUpdateRequest,
    SegmentCandidatesResponse,
    SegmentLockRequest,
    SegmentMatchRequest,
    SegmentReorderRequest,
    SegmentSelectRequest,
    SegmentUnlockRequest,
    SegmentUpdateRequest,
)
from app.services import files, script_export_service, script_match_service, script_service
from app.services.script_providers import get_script_parser_for_settings
from app.services.search_providers import (
    get_query_embedding_provider,
    get_query_parser_for_settings,
)

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


# ============================ Gate B：匹配 / 候选 / 选择锁定 ============================


async def _candidates_response(db, seg, gen, cands) -> SegmentCandidatesResponse:
    briefs = await script_match_service.candidate_shot_briefs(db, [c.shot_id for c in cands])
    items = []
    for c in cands:
        b = briefs.get(c.shot_id, {})
        items.append(
            ScriptCandidateOut(
                shot_id=c.shot_id,
                asset_id=b.get("asset_id"),
                rank=c.rank,
                final_score=c.final_score,
                semantic_score=c.semantic_score,
                lexical_score=c.lexical_score,
                tag_score=c.tag_score,
                product_score=c.product_score,
                quality_score=c.quality_score,
                review_bonus=c.review_bonus,
                risk_penalty=c.risk_penalty,
                matched_reasons=list(c.matched_reasons or []),
                unmatched_requirements=list(c.unmatched_requirements or []),
                risk_warnings=list(c.risk_warnings or []),
                sequence_no=b.get("sequence_no"),
                start_time=b.get("start_time"),
                end_time=b.get("end_time"),
                duration=b.get("duration"),
                preview_url=b.get("preview_url"),
                thumbnail_url=b.get("thumbnail_url"),
                keyframe_url=b.get("keyframe_url"),
            )
        )
    summary = seg.match_summary or {}
    is_current = gen == seg.current_generation
    return SegmentCandidatesResponse(
        segment_id=seg.id,
        generation=gen,
        current_generation=seg.current_generation,
        match_status=seg.match_status if is_current else "matched",
        candidate_count=len(cands),
        best_score=(
            summary.get("best_score")
            if is_current
            else (cands[0].final_score if cands else None)
        ),
        gap_reasons=list(summary.get("gap_reasons", []) or []) if is_current else [],
        reshoot_recommendation=(
            list(summary.get("reshoot_recommendation", []) or []) if is_current else []
        ),
        requires_human_confirmation=bool(
            summary.get("requires_human_confirmation", seg.match_status != "matched")
            if is_current
            else False
        ),
        degraded=bool(summary.get("degraded", False)) if is_current else False,
        candidates_stale=seg.candidates_stale,
        selected_shot_id=seg.selected_shot_id,
        locked_shot_id=seg.locked_shot_id,
        lock_version=seg.lock_version,
        candidates=items,
    )


@router.post(
    "/{script_id}/match",
    response_model=ScriptMatchResponse,
    status_code=status.HTTP_200_OK,
)
async def match_script(
    script_id: int,
    req: ScriptMatchRequest | None = None,
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> ScriptMatchResponse:
    """全脚本匹配（同步逐段复用描述匹配；锁定段默认跳过不覆盖）。"""
    req = req or ScriptMatchRequest()
    parser = get_query_parser_for_settings(settings)
    embedding_provider = get_query_embedding_provider(settings)
    result = await script_match_service.match_script(
        db, script_id, parser=parser, embedding_provider=embedding_provider,
        settings=settings, match_token=req.match_token,
        candidate_limit=req.candidate_limit, skip_locked=req.skip_locked,
    )
    return ScriptMatchResponse(**result)


@router.post(
    "/{script_id}/segments/{segment_id}/match",
    response_model=SegmentCandidatesResponse,
)
async def match_segment(
    script_id: int,
    segment_id: int,
    req: SegmentMatchRequest | None = None,
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> SegmentCandidatesResponse:
    """单段匹配 / 重匹配（生成新代次；保留锁定）。"""
    req = req or SegmentMatchRequest()
    parser = get_query_parser_for_settings(settings)
    embedding_provider = get_query_embedding_provider(settings)
    await script_match_service.match_segment(
        db, script_id, segment_id, parser=parser,
        embedding_provider=embedding_provider, settings=settings,
        match_token=req.match_token, candidate_limit=req.candidate_limit,
    )
    seg, gen, cands = await script_match_service.list_candidates(db, script_id, segment_id)
    return await _candidates_response(db, seg, gen, cands)


@router.get(
    "/{script_id}/segments/{segment_id}/candidates",
    response_model=SegmentCandidatesResponse,
)
async def get_segment_candidates(
    script_id: int,
    segment_id: int,
    generation: int | None = Query(None, ge=1, description="指定代次；默认当前代次"),
    db: AsyncSession = Depends(get_db),
) -> SegmentCandidatesResponse:
    seg, gen, cands = await script_match_service.list_candidates(
        db, script_id, segment_id, generation=generation
    )
    return await _candidates_response(db, seg, gen, cands)


@router.post(
    "/{script_id}/segments/{segment_id}/select",
    response_model=ScriptSegmentOut,
)
async def select_segment_shot(
    script_id: int,
    segment_id: int,
    req: SegmentSelectRequest,
    db: AsyncSession = Depends(get_db),
) -> ScriptSegmentOut:
    seg = await script_match_service.select_shot(
        db, script_id, segment_id, shot_id=req.shot_id,
        lock_version=req.lock_version, allow_override=req.allow_override,
    )
    return ScriptSegmentOut.model_validate(seg)


@router.post(
    "/{script_id}/segments/{segment_id}/lock",
    response_model=ScriptSegmentOut,
)
async def lock_segment_shot(
    script_id: int,
    segment_id: int,
    req: SegmentLockRequest,
    db: AsyncSession = Depends(get_db),
) -> ScriptSegmentOut:
    seg = await script_match_service.lock_shot(
        db, script_id, segment_id, shot_id=req.shot_id,
        lock_version=req.lock_version, allow_override=req.allow_override, force=req.force,
    )
    return ScriptSegmentOut.model_validate(seg)


@router.post(
    "/{script_id}/segments/{segment_id}/unlock",
    response_model=ScriptSegmentOut,
)
async def unlock_segment_shot(
    script_id: int,
    segment_id: int,
    req: SegmentUnlockRequest,
    db: AsyncSession = Depends(get_db),
) -> ScriptSegmentOut:
    seg = await script_match_service.unlock_segment(
        db, script_id, segment_id, lock_version=req.lock_version
    )
    return ScriptSegmentOut.model_validate(seg)


@router.get("/{script_id}/match-status", response_model=ScriptMatchStatusResponse)
async def get_match_status(
    script_id: int,
    db: AsyncSession = Depends(get_db),
) -> ScriptMatchStatusResponse:
    data = await script_match_service.get_match_status(db, script_id)
    return ScriptMatchStatusResponse(**data)


@router.get("/{script_id}/edit-list", response_model=EditListResponse)
async def get_edit_list(
    script_id: int,
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> EditListResponse:
    rows, summary = await script_match_service.get_edit_list(db, script_id, settings=settings)
    return EditListResponse(
        script_id=script_id,
        summary=EditListSummaryOut(**summary.__dict__),
        rows=[EditListRowOut(**r.__dict__) for r in rows],
    )


# ============================ Gate B：CSV 导出 ============================


def _to_export_out(export: ScriptExport) -> ScriptExportOut:
    out = ScriptExportOut.model_validate(export)
    out.status = export.status.value if hasattr(export.status, "value") else export.status
    out.has_file = bool(export.output_path)
    return out


@router.post(
    "/{script_id}/exports/csv",
    response_model=ScriptExportOut,
    status_code=status.HTTP_202_ACCEPTED,
)
async def create_csv_export(
    script_id: int,
    db: AsyncSession = Depends(get_db),
) -> ScriptExportOut:
    export = await script_export_service.request_csv_export(db, script_id)
    return _to_export_out(export)


@router.get("/{script_id}/exports/{export_id}", response_model=ScriptExportOut)
async def get_csv_export(
    script_id: int,
    export_id: int,
    db: AsyncSession = Depends(get_db),
) -> ScriptExportOut:
    export = await script_export_service.get_export_or_404(db, script_id, export_id)
    return _to_export_out(export)


@router.get("/{script_id}/exports/{export_id}/download")
async def download_csv_export(
    script_id: int,
    export_id: int,
    db: AsyncSession = Depends(get_db),
) -> FileResponse:
    export = await script_export_service.get_export_or_404(db, script_id, export_id)
    if export.status != ExportStatus.COMPLETED or not export.output_path:
        raise HTTPException(status_code=409, detail="导出尚未完成")
    download_name = export.filename or "edit_list.csv"
    return files.serve_derived(
        export.output_path,
        media_type="text/csv; charset=utf-8",
        download_name=download_name,
        immutable=False,
    )
