"""VIS-AUTO 测试（需要 TEST_DATABASE_URL；FakeProvider 确定性向量，不联网）。

锁定：嵌入持久化与内容缓存；同族参考图 → 自动候选；异族 → 不打扰人工
（unknown 不写行但记水位）；dismissed 不复活；参考集变化 → sweep 发现
水位落后；候选绝不写 product_media_link。
"""

from __future__ import annotations

import hashlib
import os
import struct
import uuid
import zlib

from clipmind_shared.db.base import utcnow
from clipmind_shared.models import (
    Asset,
    ProductFamily,
    ProductOnboardingReview,
    ProductReferenceAsset,
    SourceDirectory,
    VisualMediaEmbedding,
    VisualProductCandidate,
)
from clipmind_shared.models.enums import AssetStatus, CatalogStatus
from sqlalchemy import select

from clipmind_worker.config import WorkerSettings
from clipmind_worker.vision.indexer import (
    _load_confusion_pairs,
    build_visual_provider,
    load_family_ref_vectors,
    refresh_candidates,
    sweep_targets,
    upsert_embedding,
)


def _settings(data_dir: str, **over) -> WorkerSettings:
    base = dict(
        data_dir=data_dir, visual_embedding_provider="fake",
        visual_auto_candidates=True, visual_min_references=2,
    )
    base.update(over)
    return WorkerSettings(**base)


def _png(marker: str, salt: str = "") -> bytes:
    """合法 1×1 PNG + FAKE:<token>: 尾标（同 token → FakeProvider 同族向量）。"""

    def chunk(typ: bytes, data: bytes) -> bytes:
        c = struct.pack(">I", len(data)) + typ + data
        return c + struct.pack(">I", zlib.crc32(typ + data) & 0xFFFFFFFF)

    sig = b"\x89PNG\r\n\x1a\n"
    ihdr = chunk(b"IHDR", struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0))
    idat = chunk(b"IDAT", zlib.compress(b"\x00\x64\x64\x64"))
    iend = chunk(b"IEND", b"")
    return sig + ihdr + idat + iend + f"FAKE:{marker}:{salt}".encode()


def _seed_family(session, *, approved: bool = True) -> ProductFamily:
    code = f"VA{uuid.uuid4().hex[:6].upper()}"
    fam = ProductFamily(
        code=code, normalized_code=code.lower(), name_zh=f"视觉自动族{code}",
        status=CatalogStatus.ACTIVE,
    )
    session.add(fam)
    session.commit()
    if approved:
        session.add(ProductOnboardingReview(family_id=fam.id, status="approved"))
        session.commit()
    return fam


def _seed_ref(session, data_dir: str, family_id: int, *, marker: str,
              angle: str = "front", salt: str = "") -> ProductReferenceAsset:
    rel = f"product_reference_assets/family/{family_id}/{uuid.uuid4().hex}.png"
    abs_path = os.path.join(data_dir, *rel.split("/"))
    os.makedirs(os.path.dirname(abs_path), exist_ok=True)
    content = _png(marker, salt=salt or angle)
    with open(abs_path, "wb") as f:
        f.write(content)
    ref = ProductReferenceAsset(
        family_id=family_id, image_path=rel, media_type="png", angle=angle,
        state="active", quality_status="unchecked",
        sha256=hashlib.sha256(content).hexdigest(),
    )
    session.add(ref)
    session.commit()
    return ref


def _seed_image_asset(session, data_dir: str, *, marker: str) -> Asset:
    tag = uuid.uuid4().hex[:8]
    sd = SourceDirectory(
        name=f"va-{tag}", mount_path="/app/source", include_extensions=["jpg"],
        exclude_patterns=[], recursive=True, read_only=True,
    )
    session.add(sd)
    session.commit()
    asset = Asset(
        source_directory_id=sd.id, relative_path=f"{tag}.jpg",
        normalized_relative_path=f"{tag}.jpg", filename=f"{tag}.jpg", extension="jpg",
        file_size=10, media_kind="image", status=AssetStatus.INDEXED,
        first_seen_at=utcnow(),
        last_seen_at=utcnow(),
    )
    session.add(asset)
    session.commit()
    rel = f"assets/{asset.id}/poster.webp"
    abs_path = os.path.join(data_dir, *rel.split("/"))
    os.makedirs(os.path.dirname(abs_path), exist_ok=True)
    with open(abs_path, "wb") as f:
        f.write(_png(marker, salt="poster"))
    asset.poster_path = rel
    session.commit()
    return asset


def _index_refs_and_load(session, settings, provider, refs):
    for r in refs:
        emb, status = upsert_embedding(session, settings, provider, "reference", r.id)
        assert status in ("ok", "cached") and emb is not None
    session.commit()
    return load_family_ref_vectors(session, settings, provider)


def test_embedding_persist_and_content_cache(session, tmp_path):
    settings = _settings(str(tmp_path))
    provider = build_visual_provider(settings)
    asset = _seed_image_asset(session, str(tmp_path), marker="cachetok")
    emb, status = upsert_embedding(session, settings, provider, "asset", asset.id)
    assert status == "ok" and emb.status == "completed" and emb.dimension == 768
    session.commit()
    # 同内容重跑 → 命中缓存不重算
    emb2, status2 = upsert_embedding(session, settings, provider, "asset", asset.id)
    assert status2 == "cached" and emb2.id == emb.id


def test_matching_reference_creates_pending_candidate(session, tmp_path):
    settings = _settings(str(tmp_path))
    provider = build_visual_provider(settings)
    fam = _seed_family(session)
    refs = [
        _seed_ref(session, str(tmp_path), fam.id, marker="tokA", angle="front"),
        _seed_ref(session, str(tmp_path), fam.id, marker="tokA", angle="left"),
    ]
    families, revision = _index_refs_and_load(session, settings, provider, refs)
    assert [f.family_id for f in families] == [fam.id]

    asset = _seed_image_asset(session, str(tmp_path), marker="tokA")
    emb, _ = upsert_embedding(session, settings, provider, "asset", asset.id)
    result = refresh_candidates(
        session, settings, emb, families=families, revision=revision,
        confusion_pairs=_load_confusion_pairs(session),
    )
    session.commit()
    assert result["decision"] == "candidate" and result["written"] == 1
    row = session.execute(
        select(VisualProductCandidate).where(
            VisualProductCandidate.target_type == "asset",
            VisualProductCandidate.target_id == asset.id,
        )
    ).scalar_one()
    assert row.family_id == fam.id and row.status == "pending"
    assert row.score >= settings.visual_min_score
    assert emb.candidates_ref_revision == revision


def test_unrelated_image_writes_watermark_but_no_candidate(session, tmp_path):
    settings = _settings(str(tmp_path))
    provider = build_visual_provider(settings)
    fam = _seed_family(session)
    refs = [
        _seed_ref(session, str(tmp_path), fam.id, marker="tokB", angle="front"),
        _seed_ref(session, str(tmp_path), fam.id, marker="tokB", angle="left"),
    ]
    families, revision = _index_refs_and_load(session, settings, provider, refs)
    asset = _seed_image_asset(session, str(tmp_path), marker="totally-different")
    emb, _ = upsert_embedding(session, settings, provider, "asset", asset.id)
    result = refresh_candidates(
        session, settings, emb, families=families, revision=revision,
        confusion_pairs={},
    )
    session.commit()
    assert result["decision"] == "unknown" and result["written"] == 0
    count = session.execute(
        select(VisualProductCandidate).where(
            VisualProductCandidate.target_id == asset.id
        )
    ).scalars().all()
    assert count == []
    assert emb.candidates_ref_revision == revision  # 水位已记，sweep 不再重算


def test_dismissed_combination_not_resurrected(session, tmp_path):
    settings = _settings(str(tmp_path))
    provider = build_visual_provider(settings)
    fam = _seed_family(session)
    refs = [
        _seed_ref(session, str(tmp_path), fam.id, marker="tokC", angle="front"),
        _seed_ref(session, str(tmp_path), fam.id, marker="tokC", angle="left"),
    ]
    families, revision = _index_refs_and_load(session, settings, provider, refs)
    asset = _seed_image_asset(session, str(tmp_path), marker="tokC")
    emb, _ = upsert_embedding(session, settings, provider, "asset", asset.id)
    refresh_candidates(session, settings, emb, families=families, revision=revision,
                       confusion_pairs={})
    session.commit()
    row = session.execute(
        select(VisualProductCandidate).where(
            VisualProductCandidate.target_id == asset.id
        )
    ).scalar_one()
    row.status = "dismissed"
    session.commit()
    # 强制重算（水位清空模拟参考集变化）
    emb.candidates_ref_revision = None
    session.commit()
    result = refresh_candidates(session, settings, emb, families=families,
                                revision=revision, confusion_pairs={})
    session.commit()
    assert result["written"] == 0  # dismissed 组合不复活
    statuses = session.execute(
        select(VisualProductCandidate.status).where(
            VisualProductCandidate.target_id == asset.id
        )
    ).scalars().all()
    assert statuses == ["dismissed"]


def test_reference_change_marks_stale_in_sweep(session, tmp_path):
    settings = _settings(str(tmp_path))
    provider = build_visual_provider(settings)
    fam = _seed_family(session)
    refs = [
        _seed_ref(session, str(tmp_path), fam.id, marker="tokD", angle="front"),
        _seed_ref(session, str(tmp_path), fam.id, marker="tokD", angle="left"),
    ]
    families, revision = _index_refs_and_load(session, settings, provider, refs)
    asset = _seed_image_asset(session, str(tmp_path), marker="tokD")
    emb, _ = upsert_embedding(session, settings, provider, "asset", asset.id)
    refresh_candidates(session, settings, emb, families=families, revision=revision,
                       confusion_pairs={})
    session.commit()

    plan0 = sweep_targets(session, settings, provider)
    assert ("asset", asset.id) not in plan0["stale_candidates"]  # 水位新鲜

    # 新参考图 → 参考集摘要变化 → 该嵌入行候选水位落后
    _seed_ref(session, str(tmp_path), fam.id, marker="tokD", angle="top")
    plan1 = sweep_targets(session, settings, provider)
    assert ("asset", asset.id) in plan1["stale_candidates"]


def test_candidates_never_write_links(session, tmp_path):
    """候选生成绝不触碰 product_media_link（人工确认另走 API 通道）。"""
    from clipmind_shared.models import ProductMediaLink

    settings = _settings(str(tmp_path))
    provider = build_visual_provider(settings)
    fam = _seed_family(session)
    refs = [
        _seed_ref(session, str(tmp_path), fam.id, marker="tokE", angle="front"),
        _seed_ref(session, str(tmp_path), fam.id, marker="tokE", angle="left"),
    ]
    families, revision = _index_refs_and_load(session, settings, provider, refs)
    asset = _seed_image_asset(session, str(tmp_path), marker="tokE")
    emb, _ = upsert_embedding(session, settings, provider, "asset", asset.id)
    refresh_candidates(session, settings, emb, families=families, revision=revision,
                       confusion_pairs={})
    session.commit()
    links = session.execute(
        select(ProductMediaLink).where(ProductMediaLink.asset_id == asset.id)
    ).scalars().all()
    assert links == []
    emb_rows = session.execute(select(VisualMediaEmbedding)).scalars().all()
    assert all(e.target_type in ("asset", "reference") for e in emb_rows)


def test_reference_embedding_backfill_changes_revision(session, tmp_path):
    """竞态自愈：素材候选先于参考向量算完 → 参考向量补齐使 revision 变化，
    sweep 发现素材水位落后并重算（否则素材永远停在 insufficient 旧决策）。"""
    settings = _settings(str(tmp_path))
    provider = build_visual_provider(settings)
    fam = _seed_family(session)
    refs = [
        _seed_ref(session, str(tmp_path), fam.id, marker="tokF", angle="front"),
        _seed_ref(session, str(tmp_path), fam.id, marker="tokF", angle="left"),
    ]
    # 参考向量尚未算得时素材先完成候选决策（insufficient，只记水位）
    families0, revision0 = load_family_ref_vectors(session, settings, provider)
    asset = _seed_image_asset(session, str(tmp_path), marker="tokF")
    emb, _ = upsert_embedding(session, settings, provider, "asset", asset.id)
    result0 = refresh_candidates(session, settings, emb, families=families0,
                                 revision=revision0, confusion_pairs={})
    session.commit()
    assert result0["written"] == 0  # 参考向量缺席 → 无候选

    # 参考向量补齐 → revision 必须变化 → sweep 发现该素材行落后
    families1, revision1 = _index_refs_and_load(session, settings, provider, refs)
    assert revision1 != revision0
    plan = sweep_targets(session, settings, provider)
    assert ("asset", asset.id) in plan["stale_candidates"]

    # 重算后候选出现
    result1 = refresh_candidates(session, settings, emb, families=families1,
                                 revision=revision1, confusion_pairs={})
    session.commit()
    assert result1["decision"] == "candidate" and result1["written"] == 1
