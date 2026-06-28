"""PR-05 Gate B export-worker：脚本段落视图的**同步**取数（与 API async 层逻辑一致）。

查询用同步 Session；行→事实/标签/产品/段落视图 的转换复用 ``clipmind_shared.script.viewbuild``，
保证 export-worker 生成的 CSV 与 API ``GET /edit-list`` 对同一数据完全一致。
"""

from __future__ import annotations

from clipmind_shared.models import (
    Asset,
    AssetProduct,
    Product,
    ScriptSegment,
    ScriptShotCandidate,
    Shot,
    ShotReviewState,
    ShotTag,
    Tag,
)
from clipmind_shared.models.enums import TagType
from clipmind_shared.script import editlist as E
from clipmind_shared.script import viewbuild
from sqlalchemy import and_, select
from sqlalchemy.orm import Session


def _load_shot_facts(session: Session, shot_ids: list[int]) -> dict[int, dict]:
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
    for r in session.execute(stmt).all():
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
    for sid, source, ttype, tname in session.execute(tstmt).all():
        fact = facts.get(int(sid))
        if fact is not None:
            viewbuild.apply_tag(fact, source=source, tag_type=ttype, tag_name=tname)

    wanted_pids = {pid for pid in confirmed_pid.values() if pid is not None}
    asset_ids = {f["asset_id"] for f in facts.values()}
    asset_prod: dict[int, int] = {}
    if asset_ids:
        apstmt = (
            select(AssetProduct.asset_id, AssetProduct.product_id)
            .where(AssetProduct.asset_id.in_(list(asset_ids)), AssetProduct.active.is_(True))
            .order_by(AssetProduct.id)
        )
        for aid, pid in session.execute(apstmt).all():
            asset_prod.setdefault(int(aid), int(pid))
            wanted_pids.add(int(pid))
    prod_names: dict[int, str] = {}
    if wanted_pids:
        for p in session.scalars(select(Product).where(Product.id.in_(list(wanted_pids)))).all():
            prod_names[p.id] = p.name
    for sid, fact in facts.items():
        pid = confirmed_pid.get(sid)
        if pid is None:
            pid = asset_prod.get(fact["asset_id"])
        fact["product_name"] = prod_names.get(pid) if pid is not None else None
    return facts


def build_segment_views(session: Session, project_id: int) -> list[E.SegmentView]:
    """同步组装全项目段落视图（当前代次候选 + 锁定/选择 override 镜头事实）。"""
    segs = list(
        session.scalars(
            select(ScriptSegment)
            .where(ScriptSegment.script_project_id == project_id)
            .order_by(ScriptSegment.order_index)
        ).all()
    )
    if not segs:
        return []

    seg_ids = [s.id for s in segs]
    all_cands = list(
        session.scalars(
            select(ScriptShotCandidate)
            .where(ScriptShotCandidate.script_segment_id.in_(seg_ids))
            .order_by(ScriptShotCandidate.rank, ScriptShotCandidate.shot_id)
        ).all()
    )
    cur_gen = {s.id: s.current_generation for s in segs}
    by_seg: dict[int, list[ScriptShotCandidate]] = {}
    for c in all_cands:
        if c.generation == cur_gen.get(c.script_segment_id):
            by_seg.setdefault(c.script_segment_id, []).append(c)

    shot_ids: list[int] = [c.shot_id for c in all_cands]
    for s in segs:
        if s.locked_shot_id is not None:
            shot_ids.append(s.locked_shot_id)
        if s.selected_shot_id is not None:
            shot_ids.append(s.selected_shot_id)
    facts = _load_shot_facts(session, shot_ids)

    views: list[E.SegmentView] = []
    for s in segs:
        cand_views = [
            viewbuild.candidate_view(c, facts.get(c.shot_id), in_pool=True)
            for c in by_seg.get(s.id, [])
        ]
        pool_ids = {c.shot_id for c in by_seg.get(s.id, [])}
        for ovr in (s.locked_shot_id, s.selected_shot_id):
            if ovr is not None and ovr not in pool_ids:
                cand_views.append(viewbuild.override_view(ovr, facts.get(ovr)))
                pool_ids.add(ovr)
        views.append(viewbuild.assemble_segment_view(s, cand_views))
    return views
