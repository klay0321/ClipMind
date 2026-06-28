"""PR-05 Gate B：脚本匹配 / 选择锁定 / 剪辑清单 / CSV 导出 API 测试。

需要 TEST_DATABASE_URL + pgvector/pg_trgm。复用 FakeEmbedding + Fake 查询解析器（确定性）。
覆盖：候选生成与代次、产品硬约束、风险排除、缺口、选择/锁定/解锁与乐观锁、全局分配、
剪辑清单、匹配状态、CSV 导出落库与（同步）生成、API 状态码、空文档防御。
"""

from __future__ import annotations

import pytest_asyncio
from clipmind_shared.db.base import utcnow
from clipmind_shared.models import (
    Asset,
    AssetProduct,
    Product,
    ScriptProject,
    ScriptSegment,
    Shot,
    ShotSearchDocument,
    ShotTag,
    SourceDirectory,
    Tag,
)
from clipmind_shared.models.enums import (
    AssetStatus,
    ProductStatus,
    ScriptParseStatus,
    ScriptStatus,
    SearchDocumentStatus,
    SearchEmbeddingStatus,
    ShotStatus,
    TagSource,
    TagType,
)
from clipmind_shared.review.normalize import normalize_name

from app.config import Settings, get_settings
from app.main import app
from app.services.search_providers import get_query_embedding_provider


@pytest_asyncio.fixture
async def match_settings():
    s = Settings(
        embedding_provider="fake",
        embedding_model="fake-embed-1",
        embedding_require_pinned_revision=False,
        search_query_parser="fake",
        search_candidate_pool=200,
        script_match_min_score=0.0,
        script_match_candidate_limit=10,
        script_match_max_reuse=1,
    )
    app.dependency_overrides[get_settings] = lambda: s
    yield s
    app.dependency_overrides.pop(get_settings, None)


async def _seed(session, settings):
    """两产品多镜头语料：产品A(吹风机)/产品B(烟灰缸)，含风险、人工确认、双场景。"""
    provider = get_query_embedding_provider(settings)
    version = provider.identity().embedding_version

    sd = SourceDirectory(
        name="d", mount_path="/app/source", include_extensions=["mp4"],
        exclude_patterns=[], recursive=True, read_only=True,
    )
    session.add(sd)
    await session.flush()

    def mk_asset(path, pid_hint):
        a = Asset(
            source_directory_id=sd.id, relative_path=path, normalized_relative_path=path,
            filename=path, extension="mp4", file_size=1, status=AssetStatus.SHOT_SPLIT,
            width=1080, height=1920, duration=60.0, orientation="portrait",
            first_seen_at=utcnow(), last_seen_at=utcnow(),
        )
        session.add(a)
        return a

    asset_a = mk_asset("a.mp4", "A")
    asset_b = mk_asset("b.mp4", "B")
    await session.flush()

    prod_a = Product(name="吹风机", normalized_name=normalize_name("吹风机"),
                     brand="BR", model="HD1", sku="HD1", status=ProductStatus.ACTIVE)
    prod_b = Product(name="烟灰缸", normalized_name=normalize_name("烟灰缸"),
                     brand="BR", model="AT1", sku="AT1", status=ProductStatus.ACTIVE)
    prod_c = Product(name="打火机", normalized_name=normalize_name("打火机"),
                     brand="BR", model="LT1", sku="LT1", status=ProductStatus.ACTIVE)
    session.add_all([prod_a, prod_b, prod_c])
    await session.flush()
    session.add(AssetProduct(asset_id=asset_a.id, product_id=prod_a.id,
                             source=TagSource.HUMAN, active=True))
    session.add(AssetProduct(asset_id=asset_b.id, product_id=prod_b.id,
                             source=TagSource.HUMAN, active=True))

    tags: dict[tuple[str, str], Tag] = {}

    def tag(ttype, name):
        key = (ttype.value, name)
        if key not in tags:
            t = Tag(tag_type=ttype, tag_name=name, normalized_name=normalize_name(name),
                    status=ProductStatus.ACTIVE)
            session.add(t)
            tags[key] = t
        return tags[key]

    t_indoor = tag(TagType.SCENE, "室内")
    t_desk = tag(TagType.SCENE, "桌面")
    t_use = tag(TagType.ACTION, "使用")
    t_show = tag(TagType.ACTION, "展示")
    t_watermark = tag(TagType.RISK, "水印")
    await session.flush()

    seq = [0]

    def mk_shot(asset, dur):
        seq[0] += 1
        shot = Shot(
            asset_id=asset.id, generation=1, sequence_no=seq[0], start_time=0.0,
            end_time=dur, duration=dur, detector_type="fixed", status=ShotStatus.READY,
            keyframe_path="k.webp", thumbnail_path="t.webp", proxy_path="p.mp4",
        )
        session.add(shot)
        return shot

    def add_doc(shot, asset, text, *, embed=True, doc_status=SearchDocumentStatus.INDEXED,
                emb_status=SearchEmbeddingStatus.COMPLETED, searchable=True,
                normalized=None):
        vec = provider.embed_documents([text])[0] if embed else None
        nd = normalize_name(text) if normalized is None else normalized
        session.add(ShotSearchDocument(
            shot_id=shot.id, shot_generation=shot.generation, asset_id=asset.id,
            effective_source="ai", review_status=None,
            search_document=text, normalized_document=nd,
            search_document_hash=f"h{shot.id}", document_template_version=1,
            embedding=vec,
            embedding_provider=provider.identity().provider if embed else None,
            embedding_model=provider.identity().model if embed else None,
            embedding_model_revision=provider.identity().model_revision if embed else None,
            embedding_dimension=384 if embed else None,
            embedding_version=version if embed else None,
            normalization_version="l2-v1" if embed else None,
            document_status=doc_status, embedding_status=emb_status, is_searchable=searchable,
            retry_count=0, indexed_at=utcnow() if searchable else None,
        ))

    def add_tag(shot, t, source=TagSource.AI):
        session.add(ShotTag(shot_id=shot.id, tag_id=t.id, source=source, active=True))

    # 产品A：a1 室内/使用，a2 室内/展示，a3 含水印风险
    a1 = mk_shot(asset_a, 5.0)
    a2 = mk_shot(asset_a, 8.0)
    a3 = mk_shot(asset_a, 4.0)
    # 产品B：b1 室内/使用，b2 桌面/展示
    b1 = mk_shot(asset_b, 6.0)
    b2 = mk_shot(asset_b, 7.0)
    await session.flush()

    for shot, tlist in (
        (a1, [t_indoor, t_use]),
        (a2, [t_indoor, t_show]),
        (a3, [t_indoor, t_watermark]),
        (b1, [t_indoor, t_use]),
        (b2, [t_desk, t_show]),
    ):
        for t in tlist:
            add_tag(shot, t)
    add_doc(a1, asset_a, "吹风机 室内 使用 演示")
    add_doc(a2, asset_a, "吹风机 室内 展示 特写")
    add_doc(a3, asset_a, "吹风机 室内 水印")
    add_doc(b1, asset_b, "烟灰缸 室内 使用")
    add_doc(b2, asset_b, "烟灰缸 桌面 展示")

    await session.commit()
    return {
        "prod_a": prod_a.id, "prod_b": prod_b.id, "prod_c": prod_c.id,
        "a1": a1.id, "a2": a2.id, "a3": a3.id, "b1": b1.id, "b2": b2.id,
        "asset_a": asset_a.id, "asset_b": asset_b.id, "version": version,
    }


async def _make_script(session, segments_spec) -> tuple[int, list[int]]:
    """直接建脚本项目 + 段落（绕过拆段，精确控制 structured/product/risk）。"""
    proj = ScriptProject(
        name="gate-b-test", raw_script="x", normalized_script="x", script_hash=None,
        source_format="paste", status=ScriptStatus.PARSED, parse_status=ScriptParseStatus.OK,
    )
    session.add(proj)
    await session.flush()
    seg_ids = []
    for i, spec in enumerate(segments_spec):
        seg = ScriptSegment(
            script_project_id=proj.id, order_index=i,
            segment_text=spec.get("text", f"段落{i}"),
            visual_requirement=spec.get("visual"),
            product_id=spec.get("product_id"),
            structured_requirements=spec.get("structured"),
            negative_terms=spec.get("negative"),
            excluded_risks=spec.get("excluded_risks"),
            allow_similar_scene=spec.get("allow_similar_scene", True),
            allow_similar_action=spec.get("allow_similar_action", True),
            target_duration_min=spec.get("dmin"),
            target_duration_max=spec.get("dmax"),
            current_generation=1,
        )
        session.add(seg)
        await session.flush()
        seg_ids.append(seg.id)
    await session.commit()
    return proj.id, seg_ids


# ============================ 候选生成 / 产品硬约束 ============================


async def test_full_match_generation_and_product_hard_constraint(client, session, match_settings):
    ids = await _seed(session, match_settings)
    sid, segs = await _make_script(session, [
        {"product_id": ids["prod_a"], "structured": {"scenes": ["室内"], "actions": ["使用"]},
         "text": "吹风机 室内 使用"},
        {"product_id": ids["prod_b"], "text": "烟灰缸 室内"},
    ])
    resp = await client.post(f"/api/scripts/{sid}/match", json={})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["total_segments"] == 2
    assert sorted(body["completed_segments"]) == sorted(segs)

    # 段0 产品硬约束：只返回产品A镜头，绝不混入产品B
    c0 = (await client.get(f"/api/scripts/{sid}/segments/{segs[0]}/candidates")).json()
    assert c0["generation"] == 1 and c0["match_status"] in ("matched", "degraded")
    shots0 = {it["shot_id"] for it in c0["candidates"]}
    assert shots0 <= {ids["a1"], ids["a2"], ids["a3"]}
    assert ids["b1"] not in shots0 and ids["b2"] not in shots0
    # 段1 产品B：只返回产品B镜头
    c1 = (await client.get(f"/api/scripts/{sid}/segments/{segs[1]}/candidates")).json()
    shots1 = {it["shot_id"] for it in c1["candidates"]}
    assert shots1 <= {ids["b1"], ids["b2"]}


async def test_risk_exclusion(client, session, match_settings):
    ids = await _seed(session, match_settings)
    sid, segs = await _make_script(session, [
        {"product_id": ids["prod_a"], "excluded_risks": ["水印"], "text": "吹风机 室内"},
    ])
    await client.post(f"/api/scripts/{sid}/match", json={})
    c = (await client.get(f"/api/scripts/{sid}/segments/{segs[0]}/candidates")).json()
    shots = {it["shot_id"] for it in c["candidates"]}
    assert ids["a3"] not in shots  # 含水印被硬排除
    assert ids["a1"] in shots or ids["a2"] in shots


async def test_gap_when_product_has_no_shots(client, session, match_settings):
    ids = await _seed(session, match_settings)
    sid, segs = await _make_script(session, [
        {"product_id": ids["prod_c"], "product_name": "打火机", "text": "打火机 演示"},
    ])
    await client.post(f"/api/scripts/{sid}/match", json={})
    c = (await client.get(f"/api/scripts/{sid}/segments/{segs[0]}/candidates")).json()
    assert c["candidate_count"] == 0
    assert c["match_status"] == "gap"
    assert c["gap_reasons"]  # 真实缺口，规则派生原因
    assert c["requires_human_confirmation"] is True


async def test_segment_text_duration_not_hard_filter(client, session, match_settings):
    """段落文本含'时长不超过3秒'不得被当成时长硬过滤排除镜头（时长是软偏好）。"""
    ids = await _seed(session, match_settings)
    # 段落文本含时长措辞；产品A镜头时长均非 3s（5/8/4s），若被硬过滤则 0 候选
    sid, segs = await _make_script(session, [
        {"product_id": ids["prod_a"], "text": "展示吹风机整体外观，时长不超过3秒，室内使用"},
    ])
    await client.post(f"/api/scripts/{sid}/match", json={})
    c = (await client.get(f"/api/scripts/{sid}/segments/{segs[0]}/candidates")).json()
    assert c["candidate_count"] >= 1, f"时长措辞不应导致 0 候选: {c}"
    assert c["match_status"] in ("matched", "degraded")


async def test_min_score_forces_gap(client, session, match_settings):
    ids = await _seed(session, match_settings)
    # 提高 min_score 到 0.99 → 无候选达标 → 缺口
    match_settings.script_match_min_score = 0.99
    sid, segs = await _make_script(session, [
        {"product_id": ids["prod_a"], "text": "吹风机 室内"},
    ])
    await client.post(f"/api/scripts/{sid}/match", json={})
    c = (await client.get(f"/api/scripts/{sid}/segments/{segs[0]}/candidates")).json()
    assert c["candidate_count"] == 0 and c["match_status"] == "gap"


# ============================ 代次 / 重匹配 / 幂等 ============================


async def test_rematch_increments_generation_history_kept(client, session, match_settings):
    ids = await _seed(session, match_settings)
    sid, segs = await _make_script(session, [
        {"product_id": ids["prod_a"], "text": "吹风机 室内 使用"},
    ])
    await client.post(f"/api/scripts/{sid}/match", json={})
    c1 = (await client.get(f"/api/scripts/{sid}/segments/{segs[0]}/candidates")).json()
    assert c1["generation"] == 1
    # 单段重匹配 → generation 2
    r = await client.post(f"/api/scripts/{sid}/segments/{segs[0]}/match", json={})
    assert r.status_code == 200
    assert r.json()["generation"] == 2
    # 历史代次仍可查
    hist = (await client.get(
        f"/api/scripts/{sid}/segments/{segs[0]}/candidates?generation=1")).json()
    assert hist["generation"] == 1 and hist["candidate_count"] >= 1


async def test_full_match_partial_failure_records_cleanly(
    client, session, match_settings, monkeypatch
):
    """单段匹配抛非 HTTP 异常 → 记入 failed_segments，不影响其它段、不 MissingGreenlet 崩溃。"""
    from app.services import script_match_service as sms

    ids = await _seed(session, match_settings)
    sid, segs = await _make_script(session, [
        {"product_id": ids["prod_a"], "text": "吹风机"},
        {"product_id": ids["prod_b"], "text": "烟灰缸"},
    ])
    real = sms.match_segment

    async def flaky(db, project_id, segment_id, **kw):
        if segment_id == segs[0]:
            raise ValueError("boom")
        return await real(db, project_id, segment_id, **kw)

    monkeypatch.setattr(sms, "match_segment", flaky)
    r = await client.post(f"/api/scripts/{sid}/match", json={})
    assert r.status_code == 200, r.text
    body = r.json()
    assert any(f["segment_id"] == segs[0] for f in body["failed_segments"])
    assert segs[1] in body["completed_segments"]


async def test_match_idempotent_with_token(client, session, match_settings):
    ids = await _seed(session, match_settings)
    sid, segs = await _make_script(session, [
        {"product_id": ids["prod_a"], "text": "吹风机 室内"},
    ])
    await client.post(f"/api/scripts/{sid}/match", json={"match_token": "tok-1"})
    c1 = (await client.get(f"/api/scripts/{sid}/segments/{segs[0]}/candidates")).json()
    # 同 token 重试 → 不产生新代次
    await client.post(f"/api/scripts/{sid}/match", json={"match_token": "tok-1"})
    c2 = (await client.get(f"/api/scripts/{sid}/segments/{segs[0]}/candidates")).json()
    assert c1["current_generation"] == c2["current_generation"] == 1


# ============================ 选择 / 锁定 / 解锁 ============================


async def _first_candidate(client, sid, seg_id):
    c = (await client.get(f"/api/scripts/{sid}/segments/{seg_id}/candidates")).json()
    return c["candidates"][0]["shot_id"], c["lock_version"]


async def test_select_and_lock_version(client, session, match_settings):
    ids = await _seed(session, match_settings)
    sid, segs = await _make_script(session, [{"product_id": ids["prod_a"], "text": "吹风机"}])
    await client.post(f"/api/scripts/{sid}/match", json={})
    shot, lv = await _first_candidate(client, sid, segs[0])

    r = await client.post(f"/api/scripts/{sid}/segments/{segs[0]}/select",
                          json={"shot_id": shot, "lock_version": lv})
    assert r.status_code == 200
    body = r.json()
    assert body["selected_shot_id"] == shot
    assert body["lock_version"] == lv + 1

    # 旧 lock_version → 409
    conflict = await client.post(f"/api/scripts/{sid}/segments/{segs[0]}/select",
                                 json={"shot_id": shot, "lock_version": lv})
    assert conflict.status_code == 409


async def test_select_rejects_excluded_and_non_candidate(client, session, match_settings):
    ids = await _seed(session, match_settings)
    sid, segs = await _make_script(session, [{"product_id": ids["prod_a"], "text": "吹风机"}])
    await client.post(f"/api/scripts/{sid}/match", json={})
    _shot, lv = await _first_candidate(client, sid, segs[0])

    # 产品B镜头不在产品A段候选 → 422（无 override）
    r = await client.post(f"/api/scripts/{sid}/segments/{segs[0]}/select",
                          json={"shot_id": ids["b1"], "lock_version": lv})
    assert r.status_code == 422
    # override 允许指定非候选（但 b1 非排除态，可选）
    r2 = await client.post(f"/api/scripts/{sid}/segments/{segs[0]}/select",
                           json={"shot_id": ids["b1"], "lock_version": lv, "allow_override": True})
    assert r2.status_code == 200


async def test_lock_not_overwritten_by_full_rematch(client, session, match_settings):
    ids = await _seed(session, match_settings)
    sid, segs = await _make_script(session, [{"product_id": ids["prod_a"], "text": "吹风机"}])
    await client.post(f"/api/scripts/{sid}/match", json={})
    shot, lv = await _first_candidate(client, sid, segs[0])
    r = await client.post(f"/api/scripts/{sid}/segments/{segs[0]}/lock",
                          json={"shot_id": shot, "lock_version": lv})
    assert r.status_code == 200 and r.json()["locked_shot_id"] == shot

    # 全脚本重匹配 → 锁定段跳过，锁定不变
    full = await client.post(f"/api/scripts/{sid}/match", json={})
    assert segs[0] in full.json()["skipped_locked_segments"]
    seg = (await client.get(f"/api/scripts/{sid}/segments/{segs[0]}/candidates")).json()
    assert seg["locked_shot_id"] == shot

    # 解锁 → 可重新选择
    unlock = await client.post(f"/api/scripts/{sid}/segments/{segs[0]}/unlock",
                               json={"lock_version": seg["lock_version"]})
    assert unlock.status_code == 200 and unlock.json()["locked_shot_id"] is None


async def test_lock_replace_requires_force(client, session, match_settings):
    ids = await _seed(session, match_settings)
    sid, segs = await _make_script(session, [{"product_id": ids["prod_a"], "text": "吹风机"}])
    await client.post(f"/api/scripts/{sid}/match", json={})
    c = (await client.get(f"/api/scripts/{sid}/segments/{segs[0]}/candidates")).json()
    shots = [it["shot_id"] for it in c["candidates"]]
    lv = c["lock_version"]
    r1 = await client.post(f"/api/scripts/{sid}/segments/{segs[0]}/lock",
                           json={"shot_id": shots[0], "lock_version": lv})
    lv2 = r1.json()["lock_version"]
    # 换锁不同镜头无 force → 409
    if len(shots) > 1:
        r2 = await client.post(f"/api/scripts/{sid}/segments/{segs[0]}/lock",
                               json={"shot_id": shots[1], "lock_version": lv2})
        assert r2.status_code == 409
        r3 = await client.post(f"/api/scripts/{sid}/segments/{segs[0]}/lock",
                               json={"shot_id": shots[1], "lock_version": lv2, "force": True})
        assert r3.status_code == 200


# ============================ 全局分配 / 剪辑清单 / 状态 ============================


async def test_edit_list_and_global_allocation(client, session, match_settings):
    ids = await _seed(session, match_settings)
    sid, segs = await _make_script(session, [
        {"product_id": ids["prod_a"], "text": "吹风机 室内 使用", "dmin": 2.0, "dmax": 4.0},
        {"product_id": ids["prod_a"], "text": "吹风机 室内 展示"},
        {"product_id": ids["prod_c"], "text": "打火机"},  # 缺口段
    ])
    await client.post(f"/api/scripts/{sid}/match", json={})
    el = (await client.get(f"/api/scripts/{sid}/edit-list")).json()
    assert el["summary"]["total_segments"] == 3
    assert el["summary"]["gap_segments"] == 1
    rows = el["rows"]
    assert len(rows) == 3
    # 缺口段无 shot
    gap_row = next(r for r in rows if r["match_status"] == "gap")
    assert gap_row["shot_id"] is None and gap_row["gap_reasons"]
    # 推荐行不得标成人工已选
    rec_rows = [r for r in rows if r["selection_status"] == "recommended"]
    assert rec_rows
    # 时长建议存在
    assert rows[0]["duration_status"] in ("fit", "too_long", "too_short", "no_target")


async def test_match_status_endpoint(client, session, match_settings):
    ids = await _seed(session, match_settings)
    sid, segs = await _make_script(session, [
        {"product_id": ids["prod_a"], "text": "吹风机"},
        {"product_id": ids["prod_c"], "text": "打火机"},
    ])
    await client.post(f"/api/scripts/{sid}/match", json={})
    st = (await client.get(f"/api/scripts/{sid}/match-status")).json()
    assert st["total_segments"] == 2
    assert st["gap_segments"] == 1
    assert len(st["segments"]) == 2


# ============================ CSV 导出（落库 + 同步生成） ============================


async def test_csv_export_row_created(client, session, match_settings, monkeypatch):
    monkeypatch.setattr(
        "app.services.script_export_service.enqueue_export_script_csv",
        lambda eid: f"csvtask-{eid}",
    )
    ids = await _seed(session, match_settings)
    sid, segs = await _make_script(session, [{"product_id": ids["prod_a"], "text": "吹风机"}])
    await client.post(f"/api/scripts/{sid}/match", json={})
    r = await client.post(f"/api/scripts/{sid}/exports/csv")
    assert r.status_code == 202, r.text
    body = r.json()
    assert body["status"] == "queued" and body["export_format"] == "csv"
    assert body["celery_task_id"] == f"csvtask-{body['id']}"
    # 状态查询
    st = await client.get(f"/api/scripts/{sid}/exports/{body['id']}")
    assert st.status_code == 200 and st.json()["id"] == body["id"]
    # 未完成下载 → 409
    dl = await client.get(f"/api/scripts/{sid}/exports/{body['id']}/download")
    assert dl.status_code == 409


def test_worker_csv_generation_sync():
    """export-worker 同步取数 + CSV 生成（不经 Celery）：自建小数据，验证引用真实 shot_id。"""
    import os

    from clipmind_shared.models import ScriptShotCandidate
    from clipmind_shared.script import editlist as E
    from clipmind_worker.exports.factload import build_segment_views
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session

    test_url = os.environ["TEST_DATABASE_URL"].replace("+asyncpg", "+psycopg")
    eng = create_engine(test_url, future=True)
    try:
        with Session(eng) as s:
            sd = SourceDirectory(
                name="wd", mount_path="/app/source", include_extensions=["mp4"],
                exclude_patterns=[], recursive=True, read_only=True,
            )
            s.add(sd)
            s.flush()
            asset = Asset(
                source_directory_id=sd.id, relative_path="w.mp4",
                normalized_relative_path="w.mp4", filename="w.mp4", extension="mp4",
                file_size=1, status=AssetStatus.SHOT_SPLIT, width=1080, height=1920,
                duration=10.0, orientation="portrait",
                first_seen_at=utcnow(), last_seen_at=utcnow(),
            )
            s.add(asset)
            s.flush()
            shot = Shot(
                asset_id=asset.id, generation=1, sequence_no=1, start_time=0.0,
                end_time=6.0, duration=6.0, detector_type="fixed", status=ShotStatus.READY,
                keyframe_path="k.webp", thumbnail_path="t.webp", proxy_path="p.mp4",
            )
            s.add(shot)
            proj = ScriptProject(
                name="导出,含逗号", raw_script="x", normalized_script="x",
                source_format="paste", status=ScriptStatus.MATCHED,
                parse_status=ScriptParseStatus.OK,
            )
            s.add(proj)
            s.flush()
            seg = ScriptSegment(
                script_project_id=proj.id, order_index=0, segment_text="=SUM(A1) 危险开头",
                current_generation=1, match_status="matched", target_duration_min=2.0,
                target_duration_max=4.0,
            )
            s.add(seg)
            s.flush()
            s.add(ScriptShotCandidate(
                script_segment_id=seg.id, generation=1, shot_id=shot.id, rank=0,
                final_score=0.9, matched_reasons=["产品匹配：x"],
            ))
            s.commit()

            views = build_segment_views(s, proj.id)
            rows, summary = E.build_edit_list(views, max_reuse=1)
            data = E.to_csv(rows)
            assert data[:3] == b"\xef\xbb\xbf"
            assert len(rows) == summary.total_segments == 1
            assert rows[0].shot_id == shot.id  # 引用真实 shot_id
            text = data[3:].decode("utf-8")
            assert "'=SUM(A1) 危险开头" in text  # 公式注入防护（以 = 开头加前导单引号）
    finally:
        eng.dispose()


# ============================ API 状态码 ============================


async def test_404_unknown_script_and_segment(client, session, match_settings):
    r = await client.get("/api/scripts/999999/match-status")
    assert r.status_code == 404
    r2 = await client.get("/api/scripts/999999/segments/1/candidates")
    assert r2.status_code == 404


async def test_match_request_rejects_unknown_field(client, session, match_settings):
    ids = await _seed(session, match_settings)
    sid, segs = await _make_script(session, [{"product_id": ids["prod_a"], "text": "x"}])
    r = await client.post(f"/api/scripts/{sid}/match", json={"evil": 1})
    assert r.status_code == 422  # extra=forbid
