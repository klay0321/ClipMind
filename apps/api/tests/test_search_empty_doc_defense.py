"""PR-05 Gate B：历史空检索文档防御 + 描述匹配显式结构化软信号 回归测试。

- 空 normalized_document（含 completed 嵌入、is_searchable=true）不得进入向量召回污染排序；
  仅有标签/产品的退化文档（normalized_document 非空）仍正常参与。
- DescriptionMatchRequest 的显式 scenes/actions/negative_terms 精确注入软通道，不依赖文本解析。
"""

from __future__ import annotations

import pytest_asyncio
from clipmind_shared.db.base import utcnow
from clipmind_shared.models import (
    Asset,
    Shot,
    ShotSearchDocument,
    ShotTag,
    SourceDirectory,
    Tag,
)
from clipmind_shared.models.enums import (
    AssetStatus,
    ProductStatus,
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
async def s_settings():
    s = Settings(
        embedding_provider="fake", embedding_model="fake-embed-1",
        embedding_require_pinned_revision=False, search_query_parser="fake",
        search_candidate_pool=200,
    )
    app.dependency_overrides[get_settings] = lambda: s
    yield s
    app.dependency_overrides.pop(get_settings, None)


async def _seed(session, settings, *, empty_doc: str):
    provider = get_query_embedding_provider(settings)
    version = provider.identity().embedding_version
    sd = SourceDirectory(
        name="d", mount_path="/app/source", include_extensions=["mp4"],
        exclude_patterns=[], recursive=True, read_only=True,
    )
    session.add(sd)
    await session.flush()
    asset = Asset(
        source_directory_id=sd.id, relative_path="x.mp4", normalized_relative_path="x.mp4",
        filename="x.mp4", extension="mp4", file_size=1, status=AssetStatus.SHOT_SPLIT,
        width=1080, height=1920, duration=60.0, orientation="portrait",
        first_seen_at=utcnow(), last_seen_at=utcnow(),
    )
    session.add(asset)
    await session.flush()

    seq = [0]

    def mk_shot():
        seq[0] += 1
        shot = Shot(
            asset_id=asset.id, generation=1, sequence_no=seq[0], start_time=0.0,
            end_time=5.0, duration=5.0, detector_type="fixed", status=ShotStatus.READY,
            keyframe_path="k.webp", thumbnail_path="t.webp", proxy_path="p.mp4",
        )
        session.add(shot)
        return shot

    def add_doc(shot, text, norm):
        vec = provider.embed_documents([text or " "])[0]
        session.add(ShotSearchDocument(
            shot_id=shot.id, shot_generation=1, asset_id=asset.id,
            effective_source="ai", review_status=None,
            search_document=text, normalized_document=norm,
            search_document_hash=f"h{shot.id}", document_template_version=1,
            embedding=vec, embedding_provider=provider.identity().provider,
            embedding_model=provider.identity().model,
            embedding_model_revision=provider.identity().model_revision,
            embedding_dimension=384, embedding_version=version, normalization_version="l2-v1",
            document_status=SearchDocumentStatus.INDEXED,
            embedding_status=SearchEmbeddingStatus.COMPLETED, is_searchable=True,
            retry_count=0, indexed_at=utcnow(),
        ))

    real = mk_shot()
    empty = mk_shot()
    # 退化文档：仅有标签，文本极少但 normalized_document 非空（应仍可向量召回）
    degraded = mk_shot()
    await session.flush()

    add_doc(real, "户外跑步 运动 阳光", normalize_name("户外跑步 运动 阳光"))
    add_doc(empty, "", empty_doc)  # 空文档（normalized_document 为空/空白）
    t = Tag(tag_type=TagType.SCENE, tag_name="户外", normalized_name=normalize_name("户外"),
            status=ProductStatus.ACTIVE)
    session.add(t)
    await session.flush()
    session.add(ShotTag(shot_id=degraded.id, tag_id=t.id, source=TagSource.AI, active=True))
    add_doc(degraded, "户外", normalize_name("户外"))

    await session.commit()
    return {"real": real.id, "empty": empty.id, "degraded": degraded.id}


async def test_empty_normalized_document_excluded_from_vector(client, session, s_settings):
    ids = await _seed(session, s_settings, empty_doc="")
    resp = await client.post(
        "/api/search/shots", json={"query": "户外跑步", "search_mode": "semantic"}
    )
    assert resp.status_code == 200, resp.text
    items = resp.json()["items"]
    found = {it["shot_id"] for it in items}
    # 空文档不进语义召回；真实文档命中
    assert ids["empty"] not in found
    assert ids["real"] in found


async def test_whitespace_only_document_excluded_from_vector(client, session, s_settings):
    ids = await _seed(session, s_settings, empty_doc="   ")
    resp = await client.post(
        "/api/search/shots", json={"query": "户外跑步", "search_mode": "semantic"}
    )
    found = {it["shot_id"] for it in resp.json()["items"]}
    assert ids["empty"] not in found  # 纯空白同样被防御


async def test_degraded_doc_with_tags_still_recalled(client, session, s_settings):
    """仅有标签、文本少但 normalized_document 非空的退化文档不被误排除。"""
    ids = await _seed(session, s_settings, empty_doc="")
    resp = await client.post(
        "/api/match/description",
        json={"target_description": "户外", "scenes": ["户外"], "allow_similar_scene": True},
    )
    assert resp.status_code == 200, resp.text
    found = {it["shot_id"] for it in resp.json()["items"]}
    assert ids["degraded"] in found  # 显式 scenes 软信号命中标签召回


async def test_description_match_explicit_negative_term(client, session, s_settings):
    """显式 negative_terms 作为词法硬排除（含该词的镜头被剔除）。"""
    ids = await _seed(session, s_settings, empty_doc="")
    resp = await client.post(
        "/api/match/description",
        json={"target_description": "户外", "negative_terms": ["跑步"]},
    )
    assert resp.status_code == 200, resp.text
    found = {it["shot_id"] for it in resp.json()["items"]}
    assert ids["real"] not in found  # "户外跑步" 含否定词被排除
