"""检索文档索引器测试（worker，需要 TEST_DATABASE_URL + pgvector）。

坐实：AI/人工有效结果来源、幂等跳过、内容/模型变更重嵌、degraded 仍可词法检索（不进向量）、
provider 恢复后可重嵌、rejected 排除、向量入库往返、未固定 revision fail-closed、
sweeper 过期识别（degraded/版本漂移/审核漂移）、旧 generation 级联退出检索。
"""

from __future__ import annotations

from clipmind_shared.ai import FakeEmbeddingProvider, NotConfiguredEmbeddingProvider
from clipmind_shared.ai.providers.openai_embedding import OpenAICompatibleEmbeddingProvider
from clipmind_shared.db.base import utcnow
from clipmind_shared.models import (
    AIShotAnalysis,
    Asset,
    Product,
    ProductAlias,
    Shot,
    ShotReviewState,
    ShotSearchDocument,
    SourceDirectory,
)
from clipmind_shared.models.enums import (
    AIShotAnalysisStatus,
    AssetStatus,
    ReviewStatus,
    SearchDocumentStatus,
    SearchEmbeddingStatus,
    ShotStatus,
)
from sqlalchemy import func, select, text

from clipmind_worker.search.indexer import rebuild_shot_document, shots_needing_index

PARSED = {
    "one_line": "桌面充电演示",
    "detailed": "充电器为手机充电",
    "scene": "桌面",
    "action": "充电",
    "shot_type": "产品特写",
}


def _seed_shot(session, *, parsed=PARSED, generation=1, seq=1):
    sd = SourceDirectory(
        name="d", mount_path="/app/source", include_extensions=["mp4"],
        exclude_patterns=[], recursive=True, read_only=True,
    )
    session.add(sd)
    session.commit()
    asset = Asset(
        source_directory_id=sd.id, relative_path="v.mp4", normalized_relative_path="v.mp4",
        filename="v.mp4", extension="mp4", file_size=1, status=AssetStatus.SHOT_SPLIT,
        first_seen_at=utcnow(), last_seen_at=utcnow(),
    )
    session.add(asset)
    session.commit()
    shot = Shot(
        asset_id=asset.id, generation=generation, sequence_no=seq, start_time=0.0, end_time=1.0,
        duration=1.0, detector_type="fixed", status=ShotStatus.READY,
    )
    session.add(shot)
    session.commit()
    ai = AIShotAnalysis(
        shot_id=shot.id, asset_id=asset.id, status=AIShotAnalysisStatus.COMPLETED,
        provider="fake", model="m", input_fingerprint="fp", schema_version=1,
        parsed_result=parsed, confidence=0.8,
    )
    session.add(ai)
    session.commit()
    return asset, shot, ai


def _add_shot(session, asset, *, generation, seq, parsed=PARSED):
    shot = Shot(
        asset_id=asset.id, generation=generation, sequence_no=seq, start_time=0.0, end_time=1.0,
        duration=1.0, detector_type="fixed", status=ShotStatus.READY,
    )
    session.add(shot)
    session.commit()
    ai = AIShotAnalysis(
        shot_id=shot.id, asset_id=asset.id, status=AIShotAnalysisStatus.COMPLETED,
        provider="fake", model="m", input_fingerprint="fp2", schema_version=1,
        parsed_result=parsed, confidence=0.8,
    )
    session.add(ai)
    session.commit()
    return shot, ai


def _doc(session, shot_id):
    return session.execute(
        select(ShotSearchDocument).where(ShotSearchDocument.shot_id == shot_id)
    ).scalar_one_or_none()


def _fake():
    return FakeEmbeddingProvider(dimension=384)


# ---------------- 来源 / 嵌入 ----------------

def test_ai_source_builds_and_embeds(session):
    _asset, shot, ai = _seed_shot(session)
    status = rebuild_shot_document(session, shot.id, _fake())
    session.commit()
    assert status == "completed"
    doc = _doc(session, shot.id)
    assert doc.effective_source == "ai"
    assert doc.source_ai_analysis_id == ai.id
    assert doc.is_searchable is True
    assert doc.document_status == SearchDocumentStatus.INDEXED
    assert doc.embedding_status == SearchEmbeddingStatus.COMPLETED
    assert doc.embedding_dimension == 384
    assert doc.embedding_version
    assert "桌面充电演示" in doc.search_document


def test_vector_roundtrips_through_db(session):
    _asset, shot, _ai = _seed_shot(session)
    rebuild_shot_document(session, shot.id, _fake())
    session.commit()
    session.expire_all()
    doc = _doc(session, shot.id)
    assert doc.embedding is not None
    assert len(list(doc.embedding)) == 384


def test_idempotent_skip_same_identity(session):
    _asset, shot, _ai = _seed_shot(session)
    p = _fake()
    assert rebuild_shot_document(session, shot.id, p) == "completed"
    session.commit()
    assert rebuild_shot_document(session, shot.id, p) == "skipped"
    session.commit()


def test_content_change_reembeds(session):
    _asset, shot, ai = _seed_shot(session)
    p = _fake()
    rebuild_shot_document(session, shot.id, p)
    session.commit()
    ai.parsed_result = dict(PARSED, scene="户外", one_line="户外使用")
    session.commit()
    assert rebuild_shot_document(session, shot.id, p) == "completed"
    session.commit()
    assert "户外使用" in _doc(session, shot.id).search_document


def test_force_reembed_overrides_skip(session):
    _asset, shot, _ai = _seed_shot(session)
    p = _fake()
    rebuild_shot_document(session, shot.id, p)
    session.commit()
    assert rebuild_shot_document(session, shot.id, p, force_reembed=True) == "completed"
    session.commit()


def test_human_confirmed_source_and_product_terms(session):
    _asset, shot, ai = _seed_shot(session)
    product = Product(name="PowerGo", normalized_name="powergo", brand="PG", model="P1", sku="SKU9")
    session.add(product)
    session.commit()
    session.add(ProductAlias(product_id=product.id, alias="power-go", normalized_alias="power go"))
    session.add(
        ShotReviewState(
            shot_id=shot.id, shot_generation=shot.generation, review_status=ReviewStatus.CONFIRMED,
            confirmed_result=dict(PARSED, one_line="人工确认描述"), confirmed_product_id=product.id,
            source_ai_analysis_id=ai.id, result_schema_version=1, lock_version=1,
        )
    )
    session.commit()
    assert rebuild_shot_document(session, shot.id, _fake()) == "completed"
    session.commit()
    doc = _doc(session, shot.id)
    assert doc.effective_source == "human"
    assert doc.source_review_state_id is not None
    assert "人工确认描述" in doc.search_document
    assert "SKU9" in doc.search_document


# ---------------- degraded 语义（§2）----------------

def test_degraded_searchable_lexical_not_vector(session):
    _asset, shot, _ai = _seed_shot(session)
    status = rebuild_shot_document(session, shot.id, NotConfiguredEmbeddingProvider(dimension=384))
    session.commit()
    assert status == "degraded"
    doc = _doc(session, shot.id)
    # degraded：文档已 indexed + 可搜索 + 有归一化文本（词法可命中），但无向量（不进向量召回）
    assert doc.document_status == SearchDocumentStatus.INDEXED
    assert doc.is_searchable is True
    assert doc.embedding_status == SearchEmbeddingStatus.DEGRADED
    assert doc.embedding is None
    assert doc.normalized_document
    # 词法路径（pg_trgm GIN 加速的 ILIKE 子串匹配）可命中该 degraded 文档（按 shot 限定，隔离无关）
    n_lexical = session.execute(
        text(
            "select count(*) from shot_search_document "
            "where shot_id = :sid and is_searchable and normalized_document ILIKE :q"
        ),
        {"sid": shot.id, "q": "%充电%"},
    ).scalar()
    assert n_lexical == 1
    # 向量路径要求 embedding 非空 + completed → 该 degraded 文档不参与
    n_vector = session.execute(
        text(
            "select count(*) from shot_search_document "
            "where shot_id = :sid and embedding_status='completed' and embedding is not null"
        ),
        {"sid": shot.id},
    ).scalar()
    assert n_vector == 0


def test_provider_recovery_reembeds_via_sweeper(session):
    _asset, shot, _ai = _seed_shot(session)
    rebuild_shot_document(session, shot.id, NotConfiguredEmbeddingProvider(dimension=384))
    session.commit()
    p = _fake()
    # sweeper 应把 degraded 文档识别为待重嵌
    need = shots_needing_index(session, current_embedding_version=p.identity().embedding_version)
    assert shot.id in need
    assert rebuild_shot_document(session, shot.id, p) == "completed"
    session.commit()
    assert _doc(session, shot.id).embedding_status == SearchEmbeddingStatus.COMPLETED


def test_unpinned_revision_fail_closed_degrades(session):
    _asset, shot, _ai = _seed_shot(session)
    provider = OpenAICompatibleEmbeddingProvider(
        base_url="http://embedder:8100", api_key="k", model="e5",
        dimension=384, model_revision="",  # 未固定 → fail-closed
    )
    status = rebuild_shot_document(session, shot.id, provider)
    session.commit()
    assert status == "degraded"
    doc = _doc(session, shot.id)
    assert doc.is_searchable is True            # 仍可词法/标签检索
    assert doc.embedding_status == SearchEmbeddingStatus.DEGRADED
    assert doc.embedding is None


def test_rejected_is_excluded(session):
    _asset, shot, ai = _seed_shot(session)
    session.add(
        ShotReviewState(
            shot_id=shot.id, shot_generation=shot.generation, review_status=ReviewStatus.REJECTED,
            source_ai_analysis_id=ai.id, lock_version=1,
        )
    )
    session.commit()
    assert rebuild_shot_document(session, shot.id, _fake()) == "excluded"
    session.commit()
    doc = _doc(session, shot.id)
    assert doc.is_searchable is False
    assert doc.document_status == SearchDocumentStatus.EXCLUDED
    assert doc.embedding is None


# ---------------- sweeper 过期识别（§8）----------------

def test_sweeper_finds_missing(session):
    _asset, shot, _ai = _seed_shot(session)
    assert shot.id in shots_needing_index(session)
    rebuild_shot_document(session, shot.id, _fake())
    session.commit()
    assert shot.id not in shots_needing_index(
        session, current_embedding_version=_fake().identity().embedding_version
    )


def test_sweeper_finds_embedding_version_drift(session):
    _asset, shot, _ai = _seed_shot(session)
    rebuild_shot_document(session, shot.id, _fake())
    session.commit()
    # 当前 provider 版本不同（模型/维度/revision 变更）→ 应被识别为待重嵌
    assert shot.id in shots_needing_index(session, current_embedding_version="some-other-version")
    # 同版本 → 不再需要
    assert shot.id not in shots_needing_index(
        session, current_embedding_version=_fake().identity().embedding_version
    )


def test_sweeper_finds_review_drift(session):
    _asset, shot, ai = _seed_shot(session)
    rebuild_shot_document(session, shot.id, _fake())  # ai 来源；review_status=unreviewed
    session.commit()
    # 模拟漏发：直接插入确认审核，未重建文档
    session.add(
        ShotReviewState(
            shot_id=shot.id, shot_generation=shot.generation, review_status=ReviewStatus.CONFIRMED,
            confirmed_result=PARSED, source_ai_analysis_id=ai.id, result_schema_version=1,
            lock_version=1,
        )
    )
    session.commit()
    assert shot.id in shots_needing_index(
        session, current_embedding_version=_fake().identity().embedding_version
    )


# ---------------- 人工审核内容漂移（§3）----------------

def _confirm(session, shot, ai, *, result, product_id=None, status=ReviewStatus.CONFIRMED, lock=1):
    rs = ShotReviewState(
        shot_id=shot.id, shot_generation=shot.generation, review_status=status,
        confirmed_result=result, confirmed_product_id=product_id, source_ai_analysis_id=ai.id,
        result_schema_version=1, lock_version=lock,
    )
    session.add(rs)
    session.commit()
    return rs


def test_sweeper_finds_review_lock_version_drift(session):
    _asset, shot, ai = _seed_shot(session)
    rs = _confirm(session, shot, ai, result=dict(PARSED, one_line="人工A"), lock=1)
    p = _fake()
    rebuild_shot_document(session, shot.id, p)
    session.commit()
    doc = _doc(session, shot.id)
    assert doc.effective_source == "human"
    assert doc.source_review_lock_version == 1
    ev = p.identity().embedding_version
    assert shot.id not in shots_needing_index(session, current_embedding_version=ev)
    # 同一审核行内容变更 + lock_version 自增，但审核钩子"丢失"（未重建）→ sweeper 必须命中
    rs.confirmed_result = dict(PARSED, one_line="人工B-改")
    rs.lock_version = 2
    session.commit()
    assert shot.id in shots_needing_index(session, current_embedding_version=ev)
    # 重建后文档反映新内容 + lock_version 更新 → 不再命中
    rebuild_shot_document(session, shot.id, p)
    session.commit()
    doc = _doc(session, shot.id)
    assert "人工B-改" in doc.search_document
    assert doc.source_review_lock_version == 2
    assert shot.id not in shots_needing_index(session, current_embedding_version=ev)


def test_confirmed_product_change_detected(session):
    _asset, shot, ai = _seed_shot(session)
    prod = Product(name="PowerGo", normalized_name="powergo", brand="PG", sku="SKU1")
    session.add(prod)
    session.commit()
    rs = _confirm(session, shot, ai, result=PARSED, lock=1)
    p = _fake()
    rebuild_shot_document(session, shot.id, p)
    session.commit()
    ev = p.identity().embedding_version
    # 绑定产品 + lock_version 自增（apply_review 行为）→ sweeper 命中
    rs.confirmed_product_id = prod.id
    rs.lock_version = 2
    session.commit()
    assert shot.id in shots_needing_index(session, current_embedding_version=ev)
    rebuild_shot_document(session, shot.id, p)
    session.commit()
    assert "SKU1" in _doc(session, shot.id).search_document


def test_confirmed_to_rejected_then_reopen(session):
    _asset, shot, ai = _seed_shot(session)
    rs = _confirm(session, shot, ai, result=PARSED, lock=1)
    p = _fake()
    rebuild_shot_document(session, shot.id, p)
    session.commit()
    assert _doc(session, shot.id).is_searchable is True
    # confirmed → rejected → excluded
    rs.review_status = ReviewStatus.REJECTED
    rs.confirmed_result = None
    rs.lock_version = 2
    session.commit()
    assert rebuild_shot_document(session, shot.id, p) == "excluded"
    session.commit()
    doc = _doc(session, shot.id)
    assert doc.is_searchable is False
    assert doc.document_status == SearchDocumentStatus.EXCLUDED
    # rejected → reopen(unreviewed) → 回退 AI、重新 searchable
    rs.review_status = ReviewStatus.UNREVIEWED
    rs.lock_version = 3
    session.commit()
    assert rebuild_shot_document(session, shot.id, p) == "completed"
    session.commit()
    doc = _doc(session, shot.id)
    assert doc.is_searchable is True
    assert doc.effective_source == "ai"


def test_stale_human_falls_back_to_ai(session):
    _asset, shot, ai = _seed_shot(session)
    rs = _confirm(session, shot, ai, result=dict(PARSED, one_line="人工确认"), lock=1)
    p = _fake()
    rebuild_shot_document(session, shot.id, p)
    session.commit()
    assert _doc(session, shot.id).effective_source == "human"
    # 标记 stale（如重拆镜头/输入变化）→ 当前检索切回最新 AI
    rs.stale_reason = "generation_changed"
    session.commit()
    rebuild_shot_document(session, shot.id, p)
    session.commit()
    doc = _doc(session, shot.id)
    assert doc.effective_source == "ai"
    assert doc.is_searchable is True


# ---------------- 旧 generation 退出检索（§7）----------------

def test_old_generation_cascade_exits_search(session):
    asset, shot1, _ai1 = _seed_shot(session, generation=1, seq=1)
    rebuild_shot_document(session, shot1.id, _fake())
    session.commit()
    assert _doc(session, shot1.id) is not None

    # 模拟重拆镜头：删除旧代次 Shot（FK CASCADE 连带删除其 AI/检索文档），新建新代次 Shot
    old_id = shot1.id
    session.delete(shot1)
    session.commit()
    assert _doc(session, old_id) is None  # 旧文档随旧 Shot 级联删除

    shot2, _ai2 = _add_shot(session, asset, generation=2, seq=1)
    rebuild_shot_document(session, shot2.id, _fake())
    session.commit()

    total = session.execute(
        select(func.count()).select_from(ShotSearchDocument)
        .where(ShotSearchDocument.asset_id == asset.id)
    ).scalar()
    assert total == 1  # 仅当前代次一条
    doc2 = _doc(session, shot2.id)
    assert doc2.is_searchable is True
    assert doc2.shot_generation == 2
