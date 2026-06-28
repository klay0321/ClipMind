"""PR-05 Gate B：脚本段落候选匹配 / 人工选择锁定 / 剪辑清单 业务逻辑。

设计红线（与 PR 要求一致）：
- 候选生成**复用** ``run_description_match``（→ Hybrid Search 库内召回 + 规则解释），绝不另写一套
  搜索、绝不把全量镜头读进 Python、绝不让 LLM 返回/决定 shot_id、绝不编造匹配理由。
- 段落硬约束（product_id / excluded_risks / allow_similar_*=False 的场景动作）不静默放宽。
- 代次原子替换：单段重匹配生成新代次，旧代次在新代次完整成功前可用；当前代次为空=真实无匹配。
- 人工选择/锁定经 ``lock_version`` 乐观锁（DB 条件 UPDATE，rowcount=0 → 409）；不改镜头审核状态。
- 剪辑清单/全局分配用 ``clipmind_shared.script.editlist`` 纯逻辑（确定性，与 export-worker 共用）。
"""

from __future__ import annotations

from typing import Any

from clipmind_shared.db.base import utcnow
from clipmind_shared.models import (
    Asset,
    AssetProduct,
    Product,
    ScriptProject,
    ScriptSegment,
    ScriptShotCandidate,
    Shot,
    ShotReviewState,
    ShotTag,
    Tag,
)
from clipmind_shared.models.enums import ReviewStatus, ShotStatus, TagType
from clipmind_shared.script import editlist as E
from clipmind_shared.script import viewbuild
from fastapi import HTTPException
from sqlalchemy import and_, func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.schemas.search import DescriptionMatchRequest
from app.services import search_service

_HUMAN = (ReviewStatus.CONFIRMED, ReviewStatus.MODIFIED)
_EXCLUDED = (ReviewStatus.REJECTED, ReviewStatus.UNABLE)


# ============================ 取段落 / 项目 ============================


async def _get_segment_or_404(
    db: AsyncSession, project_id: int, segment_id: int
) -> ScriptSegment:
    seg = await db.get(ScriptSegment, segment_id)
    if seg is None or seg.script_project_id != project_id:
        raise HTTPException(status_code=404, detail="脚本段落不存在")
    return seg


async def get_project_or_404(db: AsyncSession, project_id: int) -> ScriptProject:
    proj = await db.get(ScriptProject, project_id)
    if proj is None:
        raise HTTPException(status_code=404, detail="脚本项目不存在")
    return proj


# ============================ 候选生成（复用描述匹配） ============================


_terms = viewbuild.term_list  # 会话无关：从 structured_requirements 取去重字符串列表


def build_match_request(
    seg: ScriptSegment, *, limit: int, minimum_score: float
) -> DescriptionMatchRequest:
    """把段落需求装配为描述匹配请求（硬约束显式、软信号精确注入，绝不依赖脆弱文本解析）。"""
    structured = seg.structured_requirements or {}
    # 自由文本（供解析器/词法/向量）：段文案 + 画面需求 + 卖点 + 必含 + 人物 + 物体
    text_parts = [seg.segment_text or "", seg.visual_requirement or ""]
    for key in ("selling_points", "must_include", "people", "objects"):
        text_parts.extend(_terms(structured, key))
    target_description = " ".join(p for p in text_parts if p).strip() or (seg.segment_text or "")

    return DescriptionMatchRequest(
        target_description=target_description,
        product_id=seg.product_id,                       # 产品硬约束
        limit=limit,
        minimum_score=minimum_score,
        exclude_risks=list(seg.excluded_risks or []),    # 风险硬排除
        # 段落文本常含"不超过3秒/5秒展示"等时长措辞；时长是软偏好（剪辑清单单独算建议），
        # 绝不据文本时长硬过滤镜头，否则会错误排除有效镜头。
        suppress_parsed_duration=True,
        allow_similar_scene=seg.allow_similar_scene,     # False → 场景硬过滤
        allow_similar_action=seg.allow_similar_action,   # False → 动作硬过滤
        # 显式结构化软信号（并入软通道；不传时长作为硬过滤——时长是软偏好，单独算建议）
        scenes=_terms(structured, "scenes"),
        actions=_terms(structured, "actions"),
        shot_types=_terms(structured, "shot_types"),
        marketing_uses=_terms(structured, "marketing_uses"),
        quality_levels=_terms(structured, "quality_requirements"),
        negative_terms=list(seg.negative_terms or []),   # 否定关键词 → 词法硬排除
    )


def _seg_view_for_outcome(seg: ScriptSegment) -> E.SegmentView:
    structured = seg.structured_requirements or {}
    return E.SegmentView(
        segment_id=seg.id,
        order_index=seg.order_index,
        segment_text=seg.segment_text,
        product_id=seg.product_id,
        scenes=_terms(structured, "scenes"),
        actions=_terms(structured, "actions"),
        excluded_risks=list(seg.excluded_risks or []),
        allow_similar_scene=seg.allow_similar_scene,
        allow_similar_action=seg.allow_similar_action,
        target_duration_min=seg.target_duration_min,
        target_duration_max=seg.target_duration_max,
    )


async def _resolve_product_name(db: AsyncSession, product_id: int | None) -> str | None:
    if product_id is None:
        return None
    p = await db.get(Product, product_id)
    return p.name if p else None


async def match_segment(
    db: AsyncSession,
    project_id: int,
    segment_id: int,
    *,
    parser,
    embedding_provider,
    settings: Settings,
    match_token: str | None = None,
    candidate_limit: int | None = None,
) -> ScriptSegment:
    """单段匹配/重匹配：复用描述匹配召回 → 代次原子替换写候选 → 更新匹配摘要。

    幂等：若 ``match_token`` 与段落上次匹配 token 相同，直接返回（不再生成新代次）。
    """
    seg = await _get_segment_or_404(db, project_id, segment_id)

    if (
        match_token
        and seg.match_summary
        and seg.match_summary.get("match_token") == match_token
    ):
        return seg  # 幂等：同一请求重试不产生重复代次

    limit = candidate_limit or settings.script_match_candidate_limit
    limit = max(1, min(E.MAX_CANDIDATE_LIMIT, limit))
    request = build_match_request(seg, limit=limit, minimum_score=settings.script_match_min_score)

    resp = await search_service.run_description_match(
        db, request, parser=parser, embedding_provider=embedding_provider, settings=settings
    )
    items = resp.items  # 已按综合分排序、已过 minimum_score 与 limit

    # 目标代次：首次=current_generation（拆段后=1）；重匹配=已有最大代次+1（旧代次保留）
    max_gen = await db.scalar(
        select(func.max(ScriptShotCandidate.generation)).where(
            ScriptShotCandidate.script_segment_id == segment_id
        )
    )
    target_gen = (max_gen + 1) if max_gen is not None else max(seg.current_generation, 1)

    sv = _seg_view_for_outcome(seg)
    sv.product_name = await _resolve_product_name(db, seg.product_id)
    best_score = items[0].score if items else None
    outcome = E.derive_match_outcome(
        sv, candidate_count=len(items), best_score=best_score, degraded=resp.degraded
    )
    outcome["generation"] = target_gen
    outcome["match_token"] = match_token
    outcome["degradation_reasons"] = list(resp.degradation_reasons or [])

    # 事务写入：同代次候选 + 段落摘要一次提交（失败回滚 → 不留半代候选、不切 current_generation）
    for rank, it in enumerate(items):
        db.add(
            ScriptShotCandidate(
                script_segment_id=segment_id,
                generation=target_gen,
                shot_id=it.shot_id,
                rank=rank,
                final_score=it.score,
                semantic_score=it.semantic_score,
                lexical_score=it.lexical_score,
                tag_score=it.tag_score,
                product_score=it.product_score,
                quality_score=it.quality_score,
                review_bonus=it.review_bonus,
                risk_penalty=it.risk_penalty,
                matched_reasons=it.matched_reasons or None,
                unmatched_requirements=it.unmatched_requirements or None,
                risk_warnings=it.risk_warnings or None,
            )
        )
    seg.current_generation = target_gen
    seg.match_status = outcome["match_status"]
    seg.match_summary = outcome
    seg.matched_at = utcnow()
    seg.candidates_stale = False
    try:
        await db.commit()
    except IntegrityError:
        # 并发同段匹配：另一请求已占用该代次（唯一约束）→ 409，请重试（不静默丢结果）
        await db.rollback()
        raise HTTPException(
            status_code=409, detail="该段落正在并发匹配，请稍后重试"
        ) from None
    await db.refresh(seg)
    return seg


async def match_script(
    db: AsyncSession,
    project_id: int,
    *,
    parser,
    embedding_provider,
    settings: Settings,
    match_token: str | None = None,
    candidate_limit: int | None = None,
    skip_locked: bool = True,
) -> dict[str, Any]:
    """全脚本匹配（同步处理：逐段复用单段匹配；锁定段默认跳过不覆盖）。

    部分失败语义：某段失败记入 failed，不影响其他已提交段落。返回逐段状态汇总。
    """
    await get_project_or_404(db, project_id)
    segs = list(
        (
            await db.scalars(
                select(ScriptSegment)
                .where(ScriptSegment.script_project_id == project_id)
                .order_by(ScriptSegment.order_index)
            )
        ).all()
    )
    completed: list[int] = []
    skipped: list[int] = []
    failed: list[dict] = []
    for seg in segs:
        if skip_locked and seg.locked_shot_id is not None:
            skipped.append(seg.id)  # 锁定段不重匹配、不覆盖
            continue
        seg_token = f"{match_token}:{seg.id}" if match_token else None
        try:
            await match_segment(
                db, project_id, seg.id, parser=parser,
                embedding_provider=embedding_provider, settings=settings,
                match_token=seg_token, candidate_limit=candidate_limit,
            )
            completed.append(seg.id)
        except HTTPException:
            raise
        except Exception as exc:  # noqa: BLE001 - 单段失败不影响其余
            await db.rollback()
            failed.append({"segment_id": seg.id, "error": str(exc)[:200]})

    return {
        "script_id": project_id,
        "total_segments": len(segs),
        "completed_segments": completed,
        "skipped_locked_segments": skipped,
        "failed_segments": failed,
        "match_token": match_token,
    }


# ============================ 候选查询 ============================


def _shot_urls(shot: Shot) -> dict[str, str | None]:
    base = f"/api/shots/{shot.id}"
    preview = f"{base}/preview" if shot.proxy_path else None
    return {
        "preview_url": preview,
        "thumbnail_url": f"{base}/thumbnail" if shot.thumbnail_path else None,
        "keyframe_url": f"{base}/keyframe" if shot.keyframe_path else None,
    }


async def candidate_shot_briefs(db: AsyncSession, shot_ids: list[int]) -> dict[int, dict]:
    """候选镜头展示 brief（序号/时间码/时长/预览URL），供候选列表与人工核对。"""
    if not shot_ids:
        return {}
    ids = list(dict.fromkeys(shot_ids))
    shots = (await db.scalars(select(Shot).where(Shot.id.in_(ids)))).all()
    out: dict[int, dict] = {}
    for s in shots:
        urls = _shot_urls(s)
        out[s.id] = {
            "asset_id": s.asset_id,
            "sequence_no": s.sequence_no,
            "start_time": s.start_time,
            "end_time": s.end_time,
            "duration": s.duration,
            **urls,
        }
    return out


async def list_candidates(
    db: AsyncSession, project_id: int, segment_id: int, *, generation: int | None = None
) -> tuple[ScriptSegment, int, list[ScriptShotCandidate]]:
    """返回 (段落, 代次, 候选列表)。默认当前代次；当前代次为空即真实无匹配（不回退旧代次）。"""
    seg = await _get_segment_or_404(db, project_id, segment_id)
    gen = generation if generation is not None else seg.current_generation
    rows = list(
        (
            await db.scalars(
                select(ScriptShotCandidate)
                .where(
                    ScriptShotCandidate.script_segment_id == segment_id,
                    ScriptShotCandidate.generation == gen,
                )
                .order_by(ScriptShotCandidate.rank, ScriptShotCandidate.shot_id)
            )
        ).all()
    )
    return seg, gen, rows


# ============================ 人工选择 / 锁定 / 解锁 ============================


async def _validate_pick(
    db: AsyncSession, seg: ScriptSegment, shot_id: int, *, allow_override: bool
) -> None:
    """校验选择/锁定目标：镜头存在且 READY、未被审核排除、属于当前候选（或显式 override）。"""
    shot = await db.get(Shot, shot_id)
    if shot is None or shot.status != ShotStatus.READY:
        raise HTTPException(status_code=422, detail="镜头不存在或不可用")
    # 审核排除态的镜头不可被选/锁（即便 override；excluded 不进推荐）
    rs = await db.scalar(
        select(ShotReviewState.review_status).where(
            ShotReviewState.shot_id == shot_id,
            ShotReviewState.shot_generation == shot.generation,
        )
    )
    if rs in _EXCLUDED:
        raise HTTPException(status_code=422, detail="镜头已被审核排除，不可选用")
    if not allow_override:
        in_pool = await db.scalar(
            select(func.count(ScriptShotCandidate.id)).where(
                ScriptShotCandidate.script_segment_id == seg.id,
                ScriptShotCandidate.generation == seg.current_generation,
                ScriptShotCandidate.shot_id == shot_id,
            )
        )
        if not in_pool:
            raise HTTPException(
                status_code=422,
                detail="镜头不在当前候选中；如确需指定请传 allow_override=true",
            )


async def _conditional_update(
    db: AsyncSession, segment_id: int, lock_version: int, values: dict
) -> None:
    values = {**values, "lock_version": lock_version + 1, "updated_at": utcnow()}
    result = await db.execute(
        update(ScriptSegment)
        .where(
            ScriptSegment.id == segment_id,
            ScriptSegment.lock_version == lock_version,
        )
        .values(**values)
    )
    if result.rowcount == 0:
        await db.rollback()
        raise HTTPException(
            status_code=409, detail="段落已被更新（lock_version 不匹配），请刷新后重试"
        )
    await db.commit()


async def select_shot(
    db: AsyncSession,
    project_id: int,
    segment_id: int,
    *,
    shot_id: int,
    lock_version: int,
    allow_override: bool = False,
) -> ScriptSegment:
    """人工选择镜头（不锁定）。乐观锁；不修改镜头审核状态。"""
    seg = await _get_segment_or_404(db, project_id, segment_id)
    await _validate_pick(db, seg, shot_id, allow_override=allow_override)
    await _conditional_update(db, segment_id, lock_version, {"selected_shot_id": shot_id})
    await db.refresh(seg)
    return seg


async def lock_shot(
    db: AsyncSession,
    project_id: int,
    segment_id: int,
    *,
    shot_id: int,
    lock_version: int,
    allow_override: bool = False,
    force: bool = False,
) -> ScriptSegment:
    """人工锁定镜头（后续自动匹配不得覆盖）。替换已存在的不同锁定须显式 force。"""
    seg = await _get_segment_or_404(db, project_id, segment_id)
    if (
        seg.locked_shot_id is not None
        and seg.locked_shot_id != shot_id
        and not force
    ):
        raise HTTPException(
            status_code=409,
            detail="段落已锁定其它镜头；如确需替换请传 force=true",
        )
    await _validate_pick(db, seg, shot_id, allow_override=allow_override)
    await _conditional_update(
        db, segment_id, lock_version,
        {"locked_shot_id": shot_id, "selected_shot_id": shot_id},
    )
    await db.refresh(seg)
    return seg


async def unlock_segment(
    db: AsyncSession, project_id: int, segment_id: int, *, lock_version: int
) -> ScriptSegment:
    """解锁：清空锁定（保留人工选择记录），允许后续重匹配。不删除历史候选。"""
    seg = await _get_segment_or_404(db, project_id, segment_id)
    await _conditional_update(db, segment_id, lock_version, {"locked_shot_id": None})
    await db.refresh(seg)
    return seg


# ============================ 镜头事实加载（剪辑清单 / 状态） ============================


async def _load_shot_facts(db: AsyncSession, shot_ids: list[int]) -> dict[int, dict]:
    """批量加载镜头事实（时间码/素材/产品/有效来源场景动作标签/审核有效性），避免 N+1。

    行→事实/标签/产品 的转换复用 ``viewbuild``，与 export-worker（sync）保持完全一致。
    """
    if not shot_ids:
        return {}
    ids = list(dict.fromkeys(shot_ids))
    stmt = (
        select(
            Shot.id, Shot.asset_id, Shot.sequence_no, Shot.start_time, Shot.end_time,
            Shot.duration, Shot.status, Shot.generation,
            Asset.filename,
            ShotReviewState.review_status, ShotReviewState.stale_at,
            ShotReviewState.confirmed_product_id,
        )
        .join(Asset, Asset.id == Shot.asset_id)
        .outerjoin(
            ShotReviewState,
            and_(
                ShotReviewState.shot_id == Shot.id,
                ShotReviewState.shot_generation == Shot.generation,
            ),
        )
        .where(Shot.id.in_(ids))
    )
    facts: dict[int, dict] = {}
    confirmed_pid: dict[int, int | None] = {}
    for r in (await db.execute(stmt)).all():
        facts[int(r.id)] = viewbuild.new_fact(
            asset_id=r.asset_id, sequence_no=r.sequence_no,
            start_time=r.start_time, end_time=r.end_time, duration=r.duration,
            asset_filename=r.filename, status=r.status,
            review_status=r.review_status, stale_at=r.stale_at,
        )
        confirmed_pid[int(r.id)] = (
            int(r.confirmed_product_id) if r.confirmed_product_id is not None else None
        )

    tstmt = (
        select(ShotTag.shot_id, ShotTag.source, Tag.tag_type, Tag.tag_name)
        .join(Tag, Tag.id == ShotTag.tag_id)
        .where(
            ShotTag.shot_id.in_(ids),
            ShotTag.active.is_(True),
            Tag.tag_type.in_([TagType.SCENE, TagType.ACTION]),
        )
    )
    for sid, source, ttype, tname in (await db.execute(tstmt)).all():
        fact = facts.get(int(sid))
        if fact is not None:
            viewbuild.apply_tag(fact, source=source, tag_type=ttype, tag_name=tname)

    # 产品名：优先 shot 级 confirmed_product，否则素材级关联
    wanted_pids = {pid for pid in confirmed_pid.values() if pid is not None}
    asset_ids = {f["asset_id"] for f in facts.values()}
    asset_prod: dict[int, int] = {}
    if asset_ids:
        apstmt = (
            select(AssetProduct.asset_id, AssetProduct.product_id)
            .where(AssetProduct.asset_id.in_(list(asset_ids)), AssetProduct.active.is_(True))
            .order_by(AssetProduct.id)
        )
        for aid, pid in (await db.execute(apstmt)).all():
            asset_prod.setdefault(int(aid), int(pid))
            wanted_pids.add(int(pid))
    prod_names: dict[int, str] = {}
    if wanted_pids:
        for p in (
            await db.scalars(select(Product).where(Product.id.in_(list(wanted_pids))))
        ).all():
            prod_names[p.id] = p.name
    for sid, fact in facts.items():
        pid = confirmed_pid.get(sid)
        if pid is None:
            pid = asset_prod.get(fact["asset_id"])
        fact["product_name"] = prod_names.get(pid) if pid is not None else None
    return facts


async def build_segment_views(db: AsyncSession, project_id: int) -> list[E.SegmentView]:
    """组装全项目段落视图（当前代次候选 + 锁定/选择 override 镜头事实），供剪辑清单/状态。"""
    segs = list(
        (
            await db.scalars(
                select(ScriptSegment)
                .where(ScriptSegment.script_project_id == project_id)
                .order_by(ScriptSegment.order_index)
            )
        ).all()
    )
    if not segs:
        return []

    seg_ids = [s.id for s in segs]
    # 当前代次候选（一次查全部段，Python 内按各段 current_generation 过滤）
    all_cands = list(
        (
            await db.scalars(
                select(ScriptShotCandidate)
                .where(ScriptShotCandidate.script_segment_id.in_(seg_ids))
                .order_by(ScriptShotCandidate.rank, ScriptShotCandidate.shot_id)
            )
        ).all()
    )
    cur_gen = {s.id: s.current_generation for s in segs}
    by_seg: dict[int, list[ScriptShotCandidate]] = {}
    for c in all_cands:
        if c.generation == cur_gen.get(c.script_segment_id):
            by_seg.setdefault(c.script_segment_id, []).append(c)

    # 收集所有镜头 id（候选 + 锁定 + 选择）批量取事实
    shot_ids: list[int] = []
    for c in all_cands:
        shot_ids.append(c.shot_id)
    for s in segs:
        if s.locked_shot_id is not None:
            shot_ids.append(s.locked_shot_id)
        if s.selected_shot_id is not None:
            shot_ids.append(s.selected_shot_id)
    facts = await _load_shot_facts(db, shot_ids)

    views: list[E.SegmentView] = []
    for s in segs:
        cand_views = [
            viewbuild.candidate_view(c, facts.get(c.shot_id), in_pool=True)
            for c in by_seg.get(s.id, [])
        ]
        pool_ids = {c.shot_id for c in by_seg.get(s.id, [])}
        # 锁定/选择的 override 镜头不在候选 → 追加其事实视图
        for ovr in (s.locked_shot_id, s.selected_shot_id):
            if ovr is not None and ovr not in pool_ids:
                cand_views.append(viewbuild.override_view(ovr, facts.get(ovr)))
                pool_ids.add(ovr)
        views.append(viewbuild.assemble_segment_view(s, cand_views))
    return views


async def get_edit_list(
    db: AsyncSession, project_id: int, *, settings: Settings
) -> tuple[list[E.EditListRow], E.EditListSummary]:
    await get_project_or_404(db, project_id)
    views = await build_segment_views(db, project_id)
    return E.build_edit_list(views, max_reuse=settings.script_match_max_reuse)


async def get_match_status(db: AsyncSession, project_id: int) -> dict[str, Any]:
    """全项目匹配状态汇总（逐段 + 整体），供 GET /match-status。"""
    await get_project_or_404(db, project_id)
    segs = list(
        (
            await db.scalars(
                select(ScriptSegment)
                .where(ScriptSegment.script_project_id == project_id)
                .order_by(ScriptSegment.order_index)
            )
        ).all()
    )
    # 各段当前代次候选数
    counts: dict[int, int] = {}
    if segs:
        rows = await db.execute(
            select(
                ScriptShotCandidate.script_segment_id,
                ScriptShotCandidate.generation,
                func.count(ScriptShotCandidate.id),
            )
            .where(ScriptShotCandidate.script_segment_id.in_([s.id for s in segs]))
            .group_by(ScriptShotCandidate.script_segment_id, ScriptShotCandidate.generation)
        )
        gen_counts: dict[tuple[int, int], int] = {
            (int(sid), int(gen)): int(n) for sid, gen, n in rows.all()
        }
        for s in segs:
            counts[s.id] = gen_counts.get((s.id, s.current_generation), 0)

    seg_status = []
    matched = gap = locked = selected = pending = 0
    for s in segs:
        summary = s.match_summary or {}
        if s.locked_shot_id is not None:
            locked += 1
        elif s.selected_shot_id is not None:
            selected += 1
        if s.match_status in ("matched", "degraded"):
            matched += 1
        elif s.match_status == "gap":
            gap += 1
        elif s.match_status == "pending":
            pending += 1
        seg_status.append(
            {
                "segment_id": s.id,
                "order_index": s.order_index,
                "match_status": s.match_status,
                "current_generation": s.current_generation,
                "candidate_count": counts.get(s.id, 0),
                "best_score": summary.get("best_score"),
                "gap_reasons": summary.get("gap_reasons", []),
                "reshoot_recommendation": summary.get("reshoot_recommendation", []),
                "requires_human_confirmation": summary.get(
                    "requires_human_confirmation", s.match_status != "matched"
                ),
                "degraded": summary.get("degraded", False),
                "candidates_stale": s.candidates_stale,
                "selected_shot_id": s.selected_shot_id,
                "locked_shot_id": s.locked_shot_id,
                "lock_version": s.lock_version,
            }
        )

    return {
        "script_id": project_id,
        "total_segments": len(segs),
        "matched_segments": matched,
        "gap_segments": gap,
        "locked_segments": locked,
        "selected_segments": selected,
        "pending_segments": pending,
        "segments": seg_status,
    }
