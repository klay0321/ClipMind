"""P2a 素材级检索文档索引器测试（需要 TEST_DATABASE_URL；FakeEmbedding，不联网）。

锁定：图片文档来自已完成的图片分析、视频文档为镜头有效结果聚合、
绑定产品名进入文档、无内容 excluded、幂等 skip。
"""

from __future__ import annotations

import uuid

from clipmind_shared.ai import get_embedding_provider
from clipmind_shared.db.base import utcnow
from clipmind_shared.models import (
    AIShotAnalysis,
    Asset,
    AssetImageAnalysis,
    AssetSearchDocument,
    ProductFamily,
    ProductMediaLink,
    Shot,
    SourceDirectory,
)
from clipmind_shared.models.enums import (
    AIShotAnalysisStatus,
    AssetStatus,
    CatalogStatus,
    ShotStatus,
)
from sqlalchemy import select

from clipmind_worker.search.asset_indexer import rebuild_asset_level_document


def _provider():
    return get_embedding_provider("fake", dimension=384)


def _seed_asset(session, *, kind="image", status=AssetStatus.INDEXED) -> Asset:
    tag = uuid.uuid4().hex[:8]
    sd = SourceDirectory(
        name=f"ai-{tag}", mount_path="/app/source", include_extensions=["mp4", "png"],
        exclude_patterns=[], recursive=True, read_only=True,
    )
    session.add(sd)
    session.commit()
    a = Asset(
        source_directory_id=sd.id, relative_path=f"{tag}.png",
        normalized_relative_path=f"{tag}.png", filename=f"{tag}.png",
        extension="png", media_kind=kind, file_size=1, status=status,
        first_seen_at=utcnow(), last_seen_at=utcnow(),
    )
    session.add(a)
    session.commit()
    session.refresh(a)
    return a


def _doc(session, asset_id) -> AssetSearchDocument | None:
    return session.execute(
        select(AssetSearchDocument).where(AssetSearchDocument.asset_id == asset_id)
    ).scalar_one_or_none()


def test_image_document_from_completed_analysis(session):
    asset = _seed_asset(session, kind="image")
    session.add(AssetImageAnalysis(
        asset_id=asset.id, status=AIShotAnalysisStatus.COMPLETED,
        parsed_result={"one_line": "一张银色车载香薰的产品图", "scene": "白色背景棚拍",
                       "search_keywords": ["车载香薰", "银色"]},
    ))
    session.commit()

    status = rebuild_asset_level_document(session, asset.id, _provider())
    session.commit()
    assert status == "completed"
    doc = _doc(session, asset.id)
    assert doc is not None and doc.is_searchable and doc.media_kind == "image"
    assert doc.effective_source == "ai"
    assert "车载香薰" in (doc.search_document or "")
    assert doc.embedding is not None

    # 幂等：内容未变 → skipped
    assert rebuild_asset_level_document(session, asset.id, _provider()) == "skipped"


def test_image_without_analysis_excluded(session):
    asset = _seed_asset(session, kind="image")
    status = rebuild_asset_level_document(session, asset.id, _provider())
    session.commit()
    assert status == "excluded"
    doc = _doc(session, asset.id)
    assert doc is not None and doc.is_searchable is False


def test_video_document_aggregates_shot_results(session):
    asset = _seed_asset(session, kind="video", status=AssetStatus.SHOT_SPLIT)
    for i, line in enumerate(("汽车内手持展示氛围灯", "夜晚车内灯光变换特写"), start=1):
        shot = Shot(
            asset_id=asset.id, generation=1, sequence_no=i, start_time=float(i),
            end_time=float(i) + 1.0, duration=1.0, detector_type="fixed",
            status=ShotStatus.READY,
        )
        session.add(shot)
        session.commit()
        session.add(AIShotAnalysis(
            shot_id=shot.id, asset_id=asset.id, status=AIShotAnalysisStatus.COMPLETED,
            parsed_result={"one_line": line, "product": "车载氛围灯",
                           "search_keywords": ["氛围灯"]},
        ))
        session.commit()

    status = rebuild_asset_level_document(session, asset.id, _provider())
    session.commit()
    assert status == "completed"
    doc = _doc(session, asset.id)
    assert doc is not None and doc.is_searchable and doc.media_kind == "video"
    assert doc.effective_source == "aggregate"
    text = doc.search_document or ""
    assert "汽车内手持展示氛围灯" in text and "夜晚车内灯光变换特写" in text
    assert "车载氛围灯" in text


def test_bound_product_names_enter_document(session):
    asset = _seed_asset(session, kind="image")
    tag = uuid.uuid4().hex[:6]
    fam = ProductFamily(code=f"ASD{tag}", normalized_code=f"asd{tag}",
                        name_zh=f"测试产品乙{tag}", status=CatalogStatus.ACTIVE)
    session.add(fam)
    session.commit()
    session.add(ProductMediaLink(
        asset_id=asset.id, family_id=fam.id, role="related", origin="manual",
    ))
    session.add(AssetImageAnalysis(
        asset_id=asset.id, status=AIShotAnalysisStatus.COMPLETED,
        parsed_result={"one_line": "产品白底图"},
    ))
    session.commit()

    assert rebuild_asset_level_document(session, asset.id, _provider()) == "completed"
    session.commit()
    doc = _doc(session, asset.id)
    assert f"测试产品乙{tag}" in (doc.search_document or "")


def test_video_without_results_excluded(session):
    asset = _seed_asset(session, kind="video", status=AssetStatus.SHOT_SPLIT)
    assert rebuild_asset_level_document(session, asset.id, _provider()) == "excluded"
