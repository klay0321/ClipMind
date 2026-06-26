"""Gate B 搜索/匹配 API 测试（需要 TEST_DATABASE_URL + pgvector/pg_trgm）。

覆盖：hybrid/lexical/structured/semantic 模式、degraded 文档仍可词法命中但不进向量、
精确 SKU、场景/动作结构化、风险排除、画幅/时长过滤、审核状态、include_excluded、
稳定分页、页大小上限、非法枚举、规则解释、描述匹配、建议、索引状态、重建端点。
"""

from __future__ import annotations

import pytest_asyncio
from clipmind_shared.db.base import utcnow
from clipmind_shared.models import (
    Asset,
    AssetProduct,
    Product,
    Shot,
    ShotReviewState,
    ShotSearchDocument,
    ShotTag,
    SourceDirectory,
    Tag,
)
from clipmind_shared.models.ai_analysis import AIShotAnalysis
from clipmind_shared.models.enums import (
    AIShotAnalysisStatus,
    AssetStatus,
    ProductStatus,
    ReviewStatus,
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
async def search_settings():
    s = Settings(
        embedding_provider="fake",
        embedding_model="fake-embed-1",
        embedding_require_pinned_revision=False,
        search_query_parser="fake",
        search_candidate_pool=200,
    )
    app.dependency_overrides[get_settings] = lambda: s
    yield s
    app.dependency_overrides.pop(get_settings, None)


async def _seed(session, settings):
    """构造多镜头检索语料：含 AI/人工来源、产品、风险、degraded、excluded、双画幅。"""
    provider = get_query_embedding_provider(settings)
    version = provider.identity().embedding_version

    sd = SourceDirectory(
        name="d", mount_path="/app/source", include_extensions=["mp4"],
        exclude_patterns=[], recursive=True, read_only=True,
    )
    session.add(sd)
    await session.flush()

    asset_land = Asset(
        source_directory_id=sd.id, relative_path="land.mp4", normalized_relative_path="land.mp4",
        filename="land.mp4", extension="mp4", file_size=1, status=AssetStatus.SHOT_SPLIT,
        width=1920, height=1080, duration=60.0, orientation="landscape",
        first_seen_at=utcnow(), last_seen_at=utcnow(),
    )
    asset_port = Asset(
        source_directory_id=sd.id, relative_path="port.mp4", normalized_relative_path="port.mp4",
        filename="port.mp4", extension="mp4", file_size=1, status=AssetStatus.SHOT_SPLIT,
        width=1080, height=1920, duration=30.0, orientation="portrait",
        first_seen_at=utcnow(), last_seen_at=utcnow(),
    )
    session.add_all([asset_land, asset_port])
    await session.flush()

    product = Product(
        name="PowerGo", normalized_name=normalize_name("PowerGo"),
        brand="PG", model="P1", sku="SKU9", status=ProductStatus.ACTIVE,
    )
    session.add(product)
    await session.flush()
    # 素材级产品关联（asset_land → PowerGo）
    session.add(AssetProduct(
        asset_id=asset_land.id, product_id=product.id, source=TagSource.HUMAN, active=True,
    ))

    # 标签字典
    tags: dict[tuple[str, str], Tag] = {}

    def tag(ttype: TagType, name: str) -> Tag:
        key = (ttype.value, name)
        if key not in tags:
            t = Tag(tag_type=ttype, tag_name=name, normalized_name=normalize_name(name),
                    status=ProductStatus.ACTIVE)
            session.add(t)
            tags[key] = t
        return tags[key]

    t_desk = tag(TagType.SCENE, "桌面")
    t_out = tag(TagType.SCENE, "户外")
    t_indoor = tag(TagType.SCENE, "室内")
    t_charge = tag(TagType.ACTION, "充电")
    t_unbox = tag(TagType.ACTION, "开箱")
    t_use = tag(TagType.ACTION, "使用")
    t_watermark = tag(TagType.RISK, "水印")
    await session.flush()

    seq = [0]

    def mk_shot(asset, dur, parsed, *, status=ShotStatus.READY):
        seq[0] += 1
        shot = Shot(
            asset_id=asset.id, generation=1, sequence_no=seq[0], start_time=0.0,
            end_time=dur, duration=dur, detector_type="fixed", status=status,
            keyframe_path="k.webp", thumbnail_path="t.webp", proxy_path="p.mp4",
        )
        session.add(shot)
        return shot

    def add_ai(shot, asset, parsed):
        session.add(AIShotAnalysis(
            shot_id=shot.id, asset_id=asset.id, status=AIShotAnalysisStatus.COMPLETED,
            provider="fake", model="m", input_fingerprint=f"fp{shot.id}", schema_version=1,
            parsed_result=parsed, confidence=0.8,
        ))

    def add_doc(shot, asset, text, *, embed=True, doc_status=SearchDocumentStatus.INDEXED,
                emb_status=SearchEmbeddingStatus.COMPLETED, searchable=True):
        vec = provider.embed_documents([text])[0] if embed else None
        session.add(ShotSearchDocument(
            shot_id=shot.id, shot_generation=shot.generation, asset_id=asset.id,
            effective_source="ai", review_status=None,
            search_document=text, normalized_document=normalize_name(text),
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

    def add_shot_tag(shot, t, source=TagSource.AI):
        session.add(ShotTag(shot_id=shot.id, tag_id=t.id, source=source, active=True))

    # shot1：桌面充电 PowerGo，AI 来源，有向量
    s1 = mk_shot(asset_land, 5.0, {})
    await session.flush()
    add_ai(s1, asset_land, {"one_line": "桌面充电演示", "scene": "桌面", "action": "充电"})
    add_shot_tag(s1, t_desk)
    add_shot_tag(s1, t_charge)
    add_doc(s1, asset_land, "桌面充电演示 充电器 PowerGo")

    # shot2：户外开箱，含水印风险，有向量
    s2 = mk_shot(asset_land, 20.0, {})
    await session.flush()
    add_ai(s2, asset_land, {"one_line": "户外开箱", "scene": "户外", "action": "开箱"})
    add_shot_tag(s2, t_out)
    add_shot_tag(s2, t_unbox)
    add_shot_tag(s2, t_watermark)
    add_doc(s2, asset_land, "户外开箱演示 水印")

    # shot3：室内使用，人工确认（human 来源），竖屏，有向量
    s3 = mk_shot(asset_port, 8.0, {})
    await session.flush()
    add_ai(s3, asset_port, {"one_line": "室内使用", "scene": "室内", "action": "使用"})
    session.add(ShotReviewState(
        shot_id=s3.id, shot_generation=1, review_status=ReviewStatus.CONFIRMED,
        confirmed_result={"one_line": "室内使用确认", "scene": "室内", "action": "使用"},
        result_schema_version=1, lock_version=1,
    ))
    add_shot_tag(s3, t_indoor, source=TagSource.HUMAN)
    add_shot_tag(s3, t_use, source=TagSource.HUMAN)
    add_doc(s3, asset_port, "室内使用确认 竖屏")

    # shot4：被驳回 → excluded（无向量，is_searchable False）
    s4 = mk_shot(asset_land, 3.0, {})
    await session.flush()
    add_ai(s4, asset_land, {"one_line": "被驳回内容"})
    session.add(ShotReviewState(
        shot_id=s4.id, shot_generation=1, review_status=ReviewStatus.REJECTED, lock_version=1,
    ))
    add_doc(s4, asset_land, "被驳回内容",
            embed=False, doc_status=SearchDocumentStatus.EXCLUDED,
            emb_status=SearchEmbeddingStatus.PENDING, searchable=False)

    # shot5：degraded（is_searchable True，但无向量）
    s5 = mk_shot(asset_land, 12.0, {})
    await session.flush()
    add_ai(s5, asset_land, {"one_line": "桌面降级", "scene": "桌面"})
    add_shot_tag(s5, t_desk)
    add_doc(s5, asset_land, "桌面降级文档",
            embed=False, emb_status=SearchEmbeddingStatus.DEGRADED, searchable=True)

    await session.commit()
    return {
        "asset_land": asset_land.id, "asset_port": asset_port.id, "product": product.id,
        "s1": s1.id, "s2": s2.id, "s3": s3.id, "s4": s4.id, "s5": s5.id,
        "version": version,
    }


# ---------------------- 测试 ----------------------


async def test_hybrid_search_basic(client, session, search_settings):
    ids = await _seed(session, search_settings)
    resp = await client.post(
        "/api/search/shots", json={"query": "桌面充电", "search_mode": "hybrid"}
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    found = {it["shot_id"] for it in body["items"]}
    assert ids["s1"] in found
    assert ids["s4"] not in found  # rejected 默认排除
    assert body["parser_provider"] == "fake"
    assert body["search_mode_used"] == "hybrid"
    assert body["embedding_status"] == "ok"
    s1 = next(it for it in body["items"] if it["shot_id"] == ids["s1"])
    assert s1["score"] > 0
    assert s1["semantic_score"] is not None  # 进入向量召回
    # 规则/Fake 解析器不从自由文本抽取受控场景词 → 命中理由来自向量召回
    assert "语义相似（向量召回）" in s1["matched_reasons"]


async def test_lexical_mode(client, session, search_settings):
    ids = await _seed(session, search_settings)
    resp = await client.post("/api/search/shots", json={"query": "开箱", "search_mode": "lexical"})
    body = resp.json()
    found = {it["shot_id"] for it in body["items"]}
    assert ids["s2"] in found
    # lexical 模式：semantic_score 应为 None（未跑向量）
    s2 = next(it for it in body["items"] if it["shot_id"] == ids["s2"])
    assert s2["semantic_score"] is None
    assert s2["lexical_score"] is not None


async def test_degraded_doc_lexical_hit_not_vector(client, session, search_settings):
    ids = await _seed(session, search_settings)
    resp = await client.post(
        "/api/search/shots", json={"query": "桌面降级", "search_mode": "hybrid"}
    )
    body = resp.json()
    s5 = next((it for it in body["items"] if it["shot_id"] == ids["s5"]), None)
    assert s5 is not None  # degraded 文档仍可词法命中
    assert s5["embedding_degraded"] is True
    assert s5["semantic_score"] is None
    # degraded 绝不出现“语义相似”理由，且不匹配项标注降级
    assert "语义相似（向量召回）" not in s5["matched_reasons"]
    assert any("降级" in u for u in s5["unmatched_requirements"])


async def test_exact_sku(client, session, search_settings):
    ids = await _seed(session, search_settings)
    resp = await client.post(
        "/api/search/shots", json={"query": "充电", "skus": ["SKU9"], "search_mode": "hybrid"}
    )
    body = resp.json()
    s1 = next(it for it in body["items"] if it["shot_id"] == ids["s1"])
    assert s1["product"] is not None
    assert s1["product"]["sku"] == "SKU9"
    assert s1["product_score"] == 1.0  # 精确 SKU 高权重
    assert any("产品精确匹配" in r for r in s1["matched_reasons"])


async def test_structured_scene_filter(client, session, search_settings):
    ids = await _seed(session, search_settings)
    resp = await client.post(
        "/api/search/shots", json={"scenes": ["桌面"], "search_mode": "structured"}
    )
    body = resp.json()
    found = {it["shot_id"] for it in body["items"]}
    assert ids["s1"] in found and ids["s5"] in found
    assert ids["s2"] not in found  # 户外不含桌面标签


async def test_risk_exclusion(client, session, search_settings):
    ids = await _seed(session, search_settings)
    resp = await client.post(
        "/api/search/shots",
        json={"query": "开箱", "exclude_risks": ["水印"], "search_mode": "hybrid"},
    )
    body = resp.json()
    found = {it["shot_id"] for it in body["items"]}
    assert ids["s2"] not in found  # 含水印风险被硬过滤


async def test_aspect_ratio_filter(client, session, search_settings):
    ids = await _seed(session, search_settings)
    resp = await client.post(
        "/api/search/shots",
        json={"aspect_ratios": ["9:16"], "search_mode": "structured", "scenes": ["室内"]},
    )
    body = resp.json()
    found = {it["shot_id"] for it in body["items"]}
    assert ids["s3"] in found  # 竖屏室内
    # 横屏镜头不应入选
    assert ids["s1"] not in found


async def test_duration_filter(client, session, search_settings):
    ids = await _seed(session, search_settings)
    resp = await client.post(
        "/api/search/shots", json={"query": "桌面", "duration_max": 6, "search_mode": "hybrid"}
    )
    body = resp.json()
    found = {it["shot_id"] for it in body["items"]}
    assert ids["s1"] in found  # 5s ≤ 6
    assert ids["s5"] not in found  # 12s > 6


async def test_confirmed_only_and_review_status(client, session, search_settings):
    ids = await _seed(session, search_settings)
    resp = await client.post(
        "/api/search/shots", json={"query": "使用", "confirmed_only": True, "search_mode": "hybrid"}
    )
    body = resp.json()
    found = {it["shot_id"] for it in body["items"]}
    assert ids["s3"] in found
    s3 = next(it for it in body["items"] if it["shot_id"] == ids["s3"])
    assert s3["review_status"] == "confirmed"
    assert any("已人工确认" in r for r in s3["matched_reasons"])


async def test_include_excluded(client, session, search_settings):
    ids = await _seed(session, search_settings)
    resp = await client.post(
        "/api/search/shots",
        json={"query": "被驳回", "include_excluded": True, "search_mode": "lexical"},
    )
    body = resp.json()
    found = {it["shot_id"] for it in body["items"]}
    assert ids["s4"] in found  # 显式包含被排除项


async def test_stable_pagination(client, session, search_settings):
    await _seed(session, search_settings)
    base = {"search_mode": "structured", "scenes": ["桌面", "户外", "室内"], "page_size": 2}
    p1 = (await client.post("/api/search/shots", json={**base, "page": 1})).json()
    p2 = (await client.post("/api/search/shots", json={**base, "page": 2})).json()
    ids1 = [it["shot_id"] for it in p1["items"]]
    ids2 = [it["shot_id"] for it in p2["items"]]
    assert set(ids1).isdisjoint(set(ids2))  # 无重复
    assert p1["total"] == p2["total"]


async def test_page_size_cap_422(client, session, search_settings):
    resp = await client.post("/api/search/shots", json={"query": "x", "page_size": 1000})
    assert resp.status_code == 422


async def test_invalid_aspect_enum_422(client, session, search_settings):
    resp = await client.post("/api/search/shots", json={"query": "x", "aspect_ratios": ["999:1"]})
    assert resp.status_code == 422


async def test_no_results(client, session, search_settings):
    await _seed(session, search_settings)
    resp = await client.post(
        "/api/search/shots", json={"query": "不存在的内容zzzzz", "search_mode": "lexical"}
    )
    body = resp.json()
    assert body["total"] == 0
    assert body["items"] == []


async def test_description_match(client, session, search_settings):
    ids = await _seed(session, search_settings)
    resp = await client.post(
        "/api/match/description",
        json={"target_description": "桌面充电演示", "exclude_risks": ["水印"]},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["target_requirements"] is not None
    found = {it["shot_id"] for it in body["items"]}
    assert ids["s1"] in found
    s1 = next(it for it in body["items"] if it["shot_id"] == ids["s1"])
    assert s1["recommendation_level"] in ("high", "medium", "low")
    assert "requires_human_confirmation" in s1


async def test_suggestions(client, session, search_settings):
    await _seed(session, search_settings)
    resp = await client.get("/api/search/suggestions", params={"q": "桌"})
    assert resp.status_code == 200
    body = resp.json()
    vals = {it["value"] for it in body["items"]}
    assert "桌面" in vals


async def test_index_status(client, session, search_settings):
    ids = await _seed(session, search_settings)
    resp = await client.get("/api/search/index/status")
    assert resp.status_code == 200
    body = resp.json()
    assert body["total_shots"] == 5
    assert body["indexed_documents"] == 4   # s1,s2,s3,s5
    assert body["excluded_documents"] == 1  # s4
    assert body["completed_embeddings"] == 3
    assert body["degraded_embeddings"] == 1
    assert body["embedding_version_matched"] == 3
    assert body["current_embedding_version"] == ids["version"]
    assert body["provider_healthy"] is True


async def test_rebuild_endpoint(client, session, search_settings, monkeypatch):
    ids = await _seed(session, search_settings)
    monkeypatch.setattr(
        "app.services.search_index_service.enqueue_rebuild_shot_search_doc",
        lambda sid, force=False: f"task-{sid}-{force}",
    )
    resp = await client.post(f"/api/search/index/rebuild/shot/{ids['s1']}")
    assert resp.status_code == 200
    body = resp.json()
    assert body["accepted"] is True
    assert body["scope"] == "shot"
    assert body["celery_task_id"] is not None


async def test_backfill_endpoint(client, session, search_settings, monkeypatch):
    await _seed(session, search_settings)
    monkeypatch.setattr(
        "app.services.search_index_service.enqueue_backfill_search_docs",
        lambda only_failed=False, force=False, limit=1000: "bf-task",
    )
    resp = await client.post("/api/search/index/backfill", params={"only_failed": True})
    assert resp.status_code == 200
    body = resp.json()
    assert body["accepted"] is True
    assert body["only_failed"] is True


# ============================ Gate B.1 补充 ============================


async def test_negative_terms_hard_exclusion(client, session, search_settings):
    """否定关键词真实作用于召回（词法硬排除），非仅出现在 parsed_query。"""
    ids = await _seed(session, search_settings)
    # 基线：'充电' 命中 s1
    base = (await client.post(
        "/api/search/shots", json={"query": "充电", "search_mode": "lexical"}
    )).json()
    assert ids["s1"] in {it["shot_id"] for it in base["items"]}
    # 否定 'PowerGo'（仅出现在 s1 文档；非风险词）→ s1 被排除
    neg = (await client.post(
        "/api/search/shots", json={"query": "充电 不要 PowerGo", "search_mode": "lexical"}
    )).json()
    assert "PowerGo" in neg["parsed_query"]["negative_terms"] or \
        "powergo" in [t.lower() for t in neg["parsed_query"]["negative_terms"]]
    assert ids["s1"] not in {it["shot_id"] for it in neg["items"]}


async def test_required_excluded_risk_conflict_422(client, session, search_settings):
    await _seed(session, search_settings)
    resp = await client.post(
        "/api/search/shots",
        json={"query": "x", "include_risks": ["水印"], "exclude_risks": ["水印"]},
    )
    assert resp.status_code == 422
    assert "水印" in resp.text


async def test_sort_latest(client, session, search_settings):
    ids = await _seed(session, search_settings)
    body = (await client.post(
        "/api/search/shots",
        json={"search_mode": "structured", "scenes": ["桌面"], "sort": "latest"},
    )).json()
    order = [it["shot_id"] for it in body["items"]]
    # s5 比 s1 后创建 → latest 在前
    assert order.index(ids["s5"]) < order.index(ids["s1"])


async def test_sort_duration(client, session, search_settings):
    ids = await _seed(session, search_settings)
    body = (await client.post(
        "/api/search/shots",
        json={"search_mode": "structured", "scenes": ["桌面"], "sort": "duration"},
    )).json()
    order = [it["shot_id"] for it in body["items"]]
    # s1=5s < s5=12s → duration 升序
    assert order.index(ids["s1"]) < order.index(ids["s5"])


async def test_sort_quality_stable(client, session, search_settings):
    await _seed(session, search_settings)
    req = {"search_mode": "structured", "scenes": ["桌面"], "sort": "quality"}
    a = (await client.post("/api/search/shots", json=req)).json()
    b = (await client.post("/api/search/shots", json=req)).json()
    assert [it["shot_id"] for it in a["items"]] == [it["shot_id"] for it in b["items"]]


async def test_lexical_mode_does_not_use_embedding(client, session, search_settings):
    await _seed(session, search_settings)
    body = (await client.post(
        "/api/search/shots", json={"query": "充电", "search_mode": "lexical"}
    )).json()
    assert body["embedding_status"] == "unavailable"  # 未触碰向量通道
    body2 = (await client.post(
        "/api/search/shots", json={"scenes": ["桌面"], "search_mode": "structured"}
    )).json()
    assert body2["embedding_status"] == "unavailable"


async def test_explicit_scene_is_hard_filter_in_hybrid(client, session, search_settings):
    """显式 request.scenes 在 hybrid 模式下作硬过滤（不被语义/词法越过）。"""
    ids = await _seed(session, search_settings)
    body = (await client.post(
        "/api/search/shots",
        json={"query": "充电", "scenes": ["户外"], "search_mode": "hybrid"},
    )).json()
    # s1 文本/语义匹配充电，但场景是桌面而非户外 → 被硬过滤
    assert ids["s1"] not in {it["shot_id"] for it in body["items"]}


async def test_explicit_product_id_hard_filter_not_overridden(client, session, search_settings):
    ids = await _seed(session, search_settings)
    body = (await client.post(
        "/api/search/shots",
        json={"query": "室内", "product_ids": [ids["product"]], "search_mode": "hybrid"},
    )).json()
    found = {it["shot_id"] for it in body["items"]}
    # s3(室内,port 资产) 不关联 PowerGo → 即便语义命中也被 product_id 硬过滤排除
    assert ids["s3"] not in found


# ---- 产品优先级 ----


async def _seed_products(session, settings):
    """3 个独立资产隔离产品关联，品牌区分，避免素材级关联跨 shot 串扰。"""
    sd = SourceDirectory(
        name="d", mount_path="/app/source", include_extensions=["mp4"],
        exclude_patterns=[], recursive=True, read_only=True,
    )
    session.add(sd)
    await session.flush()

    def mk_asset(rel):
        a = Asset(
            source_directory_id=sd.id, relative_path=rel, normalized_relative_path=rel,
            filename=rel, extension="mp4", file_size=1, status=AssetStatus.SHOT_SPLIT,
            first_seen_at=utcnow(), last_seen_at=utcnow(),
        )
        session.add(a)
        return a

    a_sku, a_model, a_brand = mk_asset("sku.mp4"), mk_asset("model.mp4"), mk_asset("brand.mp4")
    await session.flush()
    # 品牌区分，避免 brands=[ACME] 串到 sku/model 产品
    p_sku = Product(name="Alpha", normalized_name="alpha", brand="BRA", model="MA",
                    sku="SKUEXACT", status=ProductStatus.ACTIVE)
    p_model = Product(name="Beta", normalized_name="beta", brand="BRB", model="MODELZ",
                      sku="SKB", status=ProductStatus.ACTIVE)
    p_brand = Product(name="Gamma", normalized_name="gamma", brand="ACME", model="MC",
                      sku="SKC", status=ProductStatus.ACTIVE)
    session.add_all([p_sku, p_model, p_brand])
    await session.flush()

    seq = [0]

    def mk(asset, text):
        seq[0] += 1
        shot = Shot(asset_id=asset.id, generation=1, sequence_no=seq[0], start_time=0.0,
                    end_time=2.0, duration=2.0, detector_type="fixed", status=ShotStatus.READY,
                    proxy_path="p.mp4")
        session.add(shot)
        return shot

    s_sku = mk(a_sku, "alpha 产品镜头")
    s_model = mk(a_model, "beta 产品镜头")
    s_brand_conf = mk(a_brand, "gamma 品牌镜头 确认")
    s_brand_asset = mk(a_brand, "gamma 品牌镜头 素材")
    await session.flush()
    for shot, asset, text in (
        (s_sku, a_sku, "alpha 产品镜头"), (s_model, a_model, "beta 产品镜头"),
        (s_brand_conf, a_brand, "gamma 确认"), (s_brand_asset, a_brand, "gamma 素材"),
    ):
        session.add(ShotSearchDocument(
            shot_id=shot.id, shot_generation=1, asset_id=asset.id, effective_source="ai",
            search_document=text, normalized_document=normalize_name(text),
            search_document_hash=f"h{shot.id}", document_template_version=1,
            document_status=SearchDocumentStatus.INDEXED,
            embedding_status=SearchEmbeddingStatus.DEGRADED, is_searchable=True,
            retry_count=0, indexed_at=utcnow(),
        ))
    # 素材级关联：每个产品绑到各自资产
    def ap(asset, product):
        return AssetProduct(
            asset_id=asset.id, product_id=product.id, source=TagSource.HUMAN, active=True,
        )

    session.add_all([ap(a_sku, p_sku), ap(a_model, p_model), ap(a_brand, p_brand)])
    # shot 级人工确认：s_brand_conf → p_brand（应优先于仅素材级的 s_brand_asset）
    session.add(ShotReviewState(
        shot_id=s_brand_conf.id, shot_generation=1, review_status=ReviewStatus.CONFIRMED,
        confirmed_result={"one_line": "确认"}, confirmed_product_id=p_brand.id,
        result_schema_version=1, lock_version=1,
    ))
    await session.commit()
    return {"s_sku": s_sku.id, "s_model": s_model.id, "s_brand_conf": s_brand_conf.id,
            "s_brand_asset": s_brand_asset.id, "p_sku": p_sku.id, "p_model": p_model.id}


async def test_product_priority_sku_over_model(client, session, search_settings):
    ids = await _seed_products(session, search_settings)
    body = (await client.post(
        "/api/search/shots",
        json={"skus": ["SKUEXACT"], "models": ["MODELZ"], "search_mode": "structured"},
    )).json()
    by = {it["shot_id"]: it for it in body["items"]}
    assert by[ids["s_sku"]]["product_score"] == 1.0          # SKU 精确最高
    assert by[ids["s_model"]]["product_score"] < 1.0          # 型号次之
    assert by[ids["s_model"]]["product_score"] >= 0.9
    # SKU 精确排在型号之前
    order = [it["shot_id"] for it in body["items"]]
    assert order.index(ids["s_sku"]) < order.index(ids["s_model"])


async def test_product_confirmed_over_asset(client, session, search_settings):
    ids = await _seed_products(session, search_settings)
    # 按品牌召回（kind=brand=0.65，未到 1.0 上限，可体现 confirmed +0.05 加成）
    body = (await client.post(
        "/api/search/shots", json={"brands": ["ACME"], "search_mode": "structured"},
    )).json()
    by = {it["shot_id"]: it for it in body["items"]}
    # s_brand_conf 经 confirmed_product 关联 → 高于仅素材级关联
    assert by[ids["s_brand_conf"]]["product_score"] > by[ids["s_brand_asset"]]["product_score"]


# ---- 300+ 文档：total / filtered_total / truncated / 稳定分页 ----


async def _seed_bulk(session, settings, n: int):
    sd = SourceDirectory(
        name="d", mount_path="/app/source", include_extensions=["mp4"],
        exclude_patterns=[], recursive=True, read_only=True,
    )
    session.add(sd)
    await session.flush()
    asset = Asset(
        source_directory_id=sd.id, relative_path="b.mp4", normalized_relative_path="b.mp4",
        filename="b.mp4", extension="mp4", file_size=1, status=AssetStatus.SHOT_SPLIT,
        first_seen_at=utcnow(), last_seen_at=utcnow(),
    )
    session.add(asset)
    await session.flush()
    tag = Tag(tag_type=TagType.SCENE, tag_name="桌面", normalized_name="桌面",
              status=ProductStatus.ACTIVE)
    session.add(tag)
    await session.flush()
    shots = []
    for i in range(1, n + 1):
        shots.append(Shot(asset_id=asset.id, generation=1, sequence_no=i, start_time=0.0,
                          end_time=1.0, duration=1.0, detector_type="fixed",
                          status=ShotStatus.READY, proxy_path="p.mp4"))
    session.add_all(shots)
    await session.flush()
    docs, links = [], []
    for sh in shots:
        docs.append(ShotSearchDocument(
            shot_id=sh.id, shot_generation=1, asset_id=asset.id, effective_source="ai",
            search_document="桌面镜头", normalized_document="桌面镜头",
            search_document_hash=f"h{sh.id}", document_template_version=1,
            document_status=SearchDocumentStatus.INDEXED,
            embedding_status=SearchEmbeddingStatus.DEGRADED, is_searchable=True,
            retry_count=0, indexed_at=utcnow(),
        ))
        links.append(ShotTag(shot_id=sh.id, tag_id=tag.id, source=TagSource.AI, active=True))
    session.add_all(docs)
    session.add_all(links)
    await session.commit()
    return asset.id


async def test_total_filtered_truncated_over_pool(client, session, search_settings):
    await _seed_bulk(session, search_settings, 300)
    body = (await client.post(
        "/api/search/shots",
        json={"scenes": ["桌面"], "search_mode": "structured", "page": 1, "page_size": 10},
    )).json()
    assert body["filtered_total"] == 300          # 满足硬过滤的精确总数（不被候选池截断）
    assert body["total"] <= 200                    # 融合候选池有界
    assert body["truncated"] is True               # 明确标记截断
    assert len(body["items"]) == 10


async def test_bulk_pagination_no_dup(client, session, search_settings):
    await _seed_bulk(session, search_settings, 300)
    seen = set()
    for page in range(1, 6):
        body = (await client.post(
            "/api/search/shots",
            json={"scenes": ["桌面"], "search_mode": "structured", "page": page, "page_size": 20},
        )).json()
        ids = [it["shot_id"] for it in body["items"]]
        assert not (set(ids) & seen)               # 跨页无重复
        seen.update(ids)
    assert len(seen) == 100                          # 5 页 × 20，全序稳定切片


# ---- 描述匹配补充 ----


async def test_description_match_minimum_score_and_fields(client, session, search_settings):
    ids = await _seed(session, search_settings)
    resp = await client.post(
        "/api/match/description",
        json={"target_description": "桌面充电演示", "minimum_score": 0.05, "limit": 10},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["minimum_score"] == 0.05            # 回显阈值
    assert "filtered_total" in body and "truncated" in body
    for it in body["items"]:
        assert it["score"] >= 0.05                  # minimum_score 过滤生效
        assert "unmatched_requirements" in it       # 与父类一致命名
        assert "unmatched_requirements_detail" not in it
        assert it["recommendation_level"] in ("high", "medium", "low", "not_recommended")
    assert ids["s1"] in {it["shot_id"] for it in body["items"]}


async def test_description_match_no_results(client, session, search_settings):
    await _seed(session, search_settings)
    resp = await client.post(
        "/api/match/description",
        json={"target_description": "zzz无此内容", "minimum_score": 0.99},
    )
    body = resp.json()
    assert body["items"] == []


# ---- 安全：写操作不得经 GET ----


async def test_rebuild_not_via_get(client, session, search_settings):
    resp = await client.get("/api/search/index/rebuild/shot/1")
    assert resp.status_code == 405  # method not allowed
