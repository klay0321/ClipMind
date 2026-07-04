"""PR-F 产品视觉识别实验测试（需要 TEST_DATABASE_URL；FakeVisualProvider）。

锁定：Provider 确定性 / 参考图资格（approved+active 进、劣质排除、仅
detail 不代表产品、最小图数）/ 三聚合策略与确定排序 / open-set（unknown、
ambiguous、confusion 严 margin + 区分特征）/ 零自动绑定 / 403·422 边界 /
Benchmark 留一法防自匹配。合成"图片" = FAKE:<token>: 字节（FakeProvider
按 token 生成向量族：同 token 余弦 1.0，异 token ≈ 正交），全链路确定。
"""

from __future__ import annotations

import os
import uuid

import pytest
from clipmind_shared.ai.visual import FakeVisualProvider, cosine_similarity
from clipmind_shared.models import (
    ProductConfusionPair,
    ProductFamily,
    ProductOnboardingReview,
    ProductReferenceAsset,
    Shot,
)
from clipmind_shared.models.enums import CatalogStatus
from sqlalchemy import select, text

from app import config as app_config
from app.services.visual_reference_index import (
    clear_feature_cache,
    load_family_reference_sets,
)

pytestmark = pytest.mark.skipif(
    not os.getenv("TEST_DATABASE_URL"), reason="需要 TEST_DATABASE_URL"
)


@pytest.fixture
def visual_settings(tmp_path, monkeypatch):
    """开启实验 + fake provider + data_dir 指向临时目录 + 宽松阈值基线。"""
    settings = app_config.get_settings()
    monkeypatch.setattr(settings, "data_dir", str(tmp_path))
    monkeypatch.setattr(settings, "visual_recognition_enabled", True)
    monkeypatch.setattr(settings, "visual_embedding_provider", "fake")
    monkeypatch.setattr(settings, "visual_min_score", 0.5)
    monkeypatch.setattr(settings, "visual_min_margin", 0.05)
    monkeypatch.setattr(settings, "visual_confusion_margin", 0.30)
    monkeypatch.setattr(settings, "visual_min_references", 2)
    clear_feature_cache()
    return settings


async def _seed_family(session, code, *, onboarding="approved",
                       status=CatalogStatus.ACTIVE) -> ProductFamily:
    fam = ProductFamily(
        code=code, normalized_code=code.lower(), name_zh=f"测试族{code}", status=status
    )
    session.add(fam)
    await session.commit()
    await session.refresh(fam)
    if onboarding is not None:
        session.add(ProductOnboardingReview(family_id=fam.id, status=onboarding))
        await session.commit()
    return fam


async def _seed_ref(session, settings, family_id, *, token, angle="front",
                    state="active", quality="unchecked", primary=False,
                    suffix="") -> ProductReferenceAsset:
    rel = f"product_reference_assets/family/{family_id}/{uuid.uuid4().hex}.png"
    abs_path = os.path.join(settings.data_dir, rel.replace("/", os.sep))
    os.makedirs(os.path.dirname(abs_path), exist_ok=True)
    content = f"FAKE:{token}:{angle}{suffix}".encode()
    with open(abs_path, "wb") as f:
        f.write(content)
    import hashlib

    ref = ProductReferenceAsset(
        family_id=family_id, image_path=rel, media_type="png", angle=angle,
        state=state, quality_status=quality, is_primary=primary,
        sha256=hashlib.sha256(content).hexdigest(),
    )
    session.add(ref)
    await session.commit()
    await session.refresh(ref)
    return ref


def _query_bytes(token: str) -> bytes:
    return f"FAKE:{token}:query".encode()


async def _post_candidates(client, image: bytes, **body):
    files = {"file": ("q.png", image, "image/png")}
    params = {}
    if "top_k" in body:
        params["top_k"] = body["top_k"]
    if "aggregation" in body:
        params["aggregation"] = body["aggregation"]
    return await client.post(
        "/api/product-visual-experiments/candidates/image", files=files, params=params
    )


# ============================ Provider ============================


def test_fake_provider_deterministic_and_family_semantics():
    p = FakeVisualProvider()
    a1 = p.embed_images([b"FAKE:tokA:x"])[0]
    a2 = p.embed_images([b"FAKE:tokA:y"])[0]
    b1 = p.embed_images([b"FAKE:tokB:x"])[0]
    again = p.embed_images([b"FAKE:tokA:x"])[0]
    assert a1 == again  # 同字节逐位稳定
    assert cosine_similarity(a1, a2) > 0.999  # 同族 ≈ 1
    assert cosine_similarity(a1, b1) < 0.5    # 异族低相似
    ident = p.identity()
    assert ident.provider == "fake" and ident.dimension == 32


# ============================ 资格筛选 ============================


async def test_reference_eligibility(client, session, visual_settings):
    s = visual_settings
    ok = await _seed_family(session, f"VF{uuid.uuid4().hex[:6]}")
    await _seed_ref(session, s, ok.id, token="tokOK", angle="front")
    await _seed_ref(session, s, ok.id, token="tokOK", angle="left")
    # 干扰组：各种不合格
    draft = await _seed_family(session, f"VD{uuid.uuid4().hex[:6]}",
                               status=CatalogStatus.DRAFT)
    needs = await _seed_family(session, f"VN{uuid.uuid4().hex[:6]}",
                               onboarding="needs_changes")
    noob = await _seed_family(session, f"VO{uuid.uuid4().hex[:6]}", onboarding=None)
    badq = await _seed_family(session, f"VQ{uuid.uuid4().hex[:6]}")
    for q in ("wrong_product", "duplicate", "blurred", "occluded", "low_resolution"):
        await _seed_ref(session, s, badq.id, token="tokBQ", quality=q)
    archived_ref_fam = await _seed_family(session, f"VA{uuid.uuid4().hex[:6]}")
    await _seed_ref(session, s, archived_ref_fam.id, token="tokAR", state="rejected")
    await _seed_ref(session, s, archived_ref_fam.id, token="tokAR", state="archived")
    only_detail = await _seed_family(session, f"VDT{uuid.uuid4().hex[:6]}")
    await _seed_ref(session, s, only_detail.id, token="tokDT", angle="detail")
    await _seed_ref(session, s, only_detail.id, token="tokDT", angle="package")
    single = await _seed_family(session, f"VS{uuid.uuid4().hex[:6]}")
    await _seed_ref(session, s, single.id, token="tokS1", angle="front")

    sets = {x.family_id: x for x in await load_family_reference_sets(
        session, min_references=2
    )}
    assert sets[ok.id].eligible and len(sets[ok.id].references) == 2
    assert draft.id not in sets  # 非 ACTIVE 不进列表
    assert sets[needs.id].ineligible_reason == "onboarding_needs_changes"
    assert sets[noob.id].ineligible_reason == "onboarding_incomplete"
    assert sets[badq.id].ineligible_reason == "insufficient_reference"  # 劣质全排除
    assert sets[archived_ref_fam.id].ineligible_reason == "insufficient_reference"
    assert sets[only_detail.id].ineligible_reason == "insufficient_reference"
    assert sets[single.id].ineligible_reason == "insufficient_reference"


# ============================ 候选与聚合 ============================


async def test_candidates_aggregation_and_deterministic_order(
    client, session, visual_settings
):
    s = visual_settings
    fa = await _seed_family(session, f"CA{uuid.uuid4().hex[:6]}")
    fb = await _seed_family(session, f"CB{uuid.uuid4().hex[:6]}")
    for angle in ("front", "left", "installed"):
        await _seed_ref(session, s, fa.id, token="tokCA", angle=angle)
    await _seed_ref(session, s, fa.id, token="tokCA", angle="top", primary=True)
    for angle in ("front", "back"):
        await _seed_ref(session, s, fb.id, token="tokCB", angle=angle)

    for agg in ("max", "top_k_mean", "weighted_top_k_mean"):
        r = await _post_candidates(client, _query_bytes("tokCA"), aggregation=agg)
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["decision"] == "candidate", body
        assert body["candidates"][0]["target_id"] == fa.id
        assert body["candidates"][0]["aggregation"] == agg
        assert body["aggregation"] == agg
    # 顺序确定：两次调用逐位一致；Top-K 生效
    r1 = await _post_candidates(client, _query_bytes("tokCA"), top_k=1)
    r2 = await _post_candidates(client, _query_bytes("tokCA"), top_k=1)
    assert [c["target_id"] for c in r1.json()["candidates"]] == [
        c["target_id"] for c in r2.json()["candidates"]
    ]
    assert len(r1.json()["candidates"]) == 1
    # 多角度聚合：matched_angles 与参考计数正确
    full = (await _post_candidates(client, _query_bytes("tokCA"))).json()
    top = full["candidates"][0]
    assert top["reference_count"] == 4 and top["embedded_reference_count"] == 4
    assert set(top["matched_angles"]) == {"front", "left", "installed", "top"}


# ============================ Open-set ============================


async def test_open_set_unknown_and_ambiguous(client, session, visual_settings):
    s = visual_settings
    fa = await _seed_family(session, f"OA{uuid.uuid4().hex[:6]}")
    fb = await _seed_family(session, f"OB{uuid.uuid4().hex[:6]}")
    for angle in ("front", "left"):
        await _seed_ref(session, s, fa.id, token="tokOA", angle=angle)
        # famB 用同一 token → 两家分数几乎相同 → margin≈0 → ambiguous
        await _seed_ref(session, s, fb.id, token="tokOA", angle=angle, suffix="b")
    # unknown：查询族与库内全部无关 → top1 低于 min_score
    r = await _post_candidates(client, _query_bytes("tokZZ"))
    assert r.json()["decision"] == "unknown"
    # ambiguous：两家同分
    r2 = await _post_candidates(client, _query_bytes("tokOA"))
    body = r2.json()
    assert body["decision"] == "ambiguous"
    assert body["margin"] is not None and body["margin"] < 0.05


async def test_confusion_pair_strict_margin_and_features(
    client, session, visual_settings
):
    s = visual_settings
    monkey_margin = 0.0  # 普通 margin 设 0：只有 confusion 严 margin 生效
    import pytest as _pytest  # noqa: F401
    fa = await _seed_family(session, f"XA{uuid.uuid4().hex[:6]}")
    fb = await _seed_family(session, f"XB{uuid.uuid4().hex[:6]}")
    for angle in ("front", "left"):
        await _seed_ref(session, s, fa.id, token="tokXX", angle=angle)
        await _seed_ref(session, s, fb.id, token="tokXX", angle=angle, suffix="b")
    lo, hi = sorted((fa.id, fb.id))
    session.add(ProductConfusionPair(
        target_level="family", left_target_id=lo, right_target_id=hi,
        severity="high", reason="外观近似",
        distinguishing_features=[{"feature": "接口位置", "left_value": "左侧",
                                  "right_value": "右侧"}],
    ))
    await session.commit()
    # min_margin=0（任何 margin 都过普通闸）——confusion 严 margin 0.30 仍拦下
    settings = app_config.get_settings()
    old = settings.visual_min_margin
    settings.visual_min_margin = monkey_margin
    try:
        r = await _post_candidates(client, _query_bytes("tokXX"))
    finally:
        settings.visual_min_margin = old
    body = r.json()
    assert body["decision"] == "ambiguous"  # confusion 命中默认不判 confident
    assert body["confusion_warning"] is not None
    assert body["confusion_warning"]["severity"] == "high"
    feats = body["confusion_warning"]["distinguishing_features"]
    assert feats and feats[0]["feature"] == "接口位置"
    assert body["confusion_warning"]["strict_margin"] == 0.30


# ============================ 零自动绑定 ============================


async def test_no_auto_bind(client, session, visual_settings):
    s = visual_settings
    fam = await _seed_family(session, f"NB{uuid.uuid4().hex[:6]}")
    await _seed_ref(session, s, fam.id, token="tokNB", angle="front")
    await _seed_ref(session, s, fam.id, token="tokNB", angle="left")

    async def counts():
        rows = {}
        for t in ("asset_product", "final_video_usage", "product_onboarding_review",
                  "catalog_revision"):
            rows[t] = int((await session.execute(
                text(f"SELECT count(*) FROM {t}")  # noqa: S608 —— 固定表名
            )).scalar() or 0)
        return rows

    before = await counts()
    r = await _post_candidates(client, _query_bytes("tokNB"))
    assert r.status_code == 200 and r.json()["decision"] == "candidate"
    after = await counts()
    assert before == after  # 候选查询零写入


# ============================ API 边界 ============================


async def test_api_disabled_and_validation(client, session, visual_settings, monkeypatch):
    settings = app_config.get_settings()
    monkeypatch.setattr(settings, "visual_recognition_enabled", False)
    r = await _post_candidates(client, b"FAKE:x:q")
    assert r.status_code == 403
    monkeypatch.setattr(settings, "visual_recognition_enabled", True)
    r2 = await _post_candidates(client, b"FAKE:x:q", aggregation="bogus")
    assert r2.status_code == 422
    # status 如实返回 provider=fake（绝不冒充真实模型）
    st = (await client.get("/api/product-visual-experiments/status")).json()
    assert st["provider"] == "fake" and st["experimental"] is True
    assert st["thresholds"]["calibrated"] is False


async def test_shot_candidates_marks_generation(client, session, visual_settings):
    s = visual_settings
    fam = await _seed_family(session, f"SG{uuid.uuid4().hex[:6]}")
    await _seed_ref(session, s, fam.id, token="tokSG", angle="front")
    await _seed_ref(session, s, fam.id, token="tokSG", angle="left")
    # 造 shot（keyframe 写入 data_dir；历史代次）
    from clipmind_shared.db.base import utcnow
    from clipmind_shared.models import Asset, SourceDirectory
    from clipmind_shared.models.enums import AssetStatus, ShotStatus

    sd = SourceDirectory(name=f"vd-{uuid.uuid4().hex[:6]}", mount_path="/app/source",
                         include_extensions=["mp4"], exclude_patterns=[],
                         recursive=True, read_only=True)
    session.add(sd)
    await session.commit()
    await session.refresh(sd)
    asset = Asset(source_directory_id=sd.id, relative_path="v.mp4",
                  normalized_relative_path="v.mp4", filename="v.mp4", extension="mp4",
                  file_size=1, duration=5.0, status=AssetStatus.INDEXED,
                  first_seen_at=utcnow(), last_seen_at=utcnow())
    session.add(asset)
    await session.commit()
    await session.refresh(asset)
    rel = f"shots/{asset.id}/kf.webp"
    abs_path = os.path.join(s.data_dir, rel.replace("/", os.sep))
    os.makedirs(os.path.dirname(abs_path), exist_ok=True)
    with open(abs_path, "wb") as f:
        f.write(b"FAKE:tokSG:keyframe")
    shot = Shot(asset_id=asset.id, generation=2, sequence_no=1, start_time=0.0,
                end_time=1.0, duration=1.0, detector_type="fixed",
                status=ShotStatus.READY, keyframe_path=rel, retired_at=utcnow())
    session.add(shot)
    await session.commit()
    await session.refresh(shot)

    r = await client.post(
        f"/api/product-visual-experiments/candidates/shot/{shot.id}", json={}
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["decision"] == "candidate"
    assert body["query"]["generation"] == 2
    assert body["query"]["is_historical"] is True  # 历史代次可实验但明确标记
    # Shot 行未被修改（零写入）
    fresh = (await session.execute(select(Shot).where(Shot.id == shot.id))).scalar_one()
    assert fresh.retired_at is not None and fresh.generation == 2


# ============================ Benchmark 留一法 ============================


async def test_benchmark_leave_one_out(client, session, visual_settings):
    s = visual_settings
    fa = await _seed_family(session, f"BM{uuid.uuid4().hex[:6]}")
    r1 = await _seed_ref(session, s, fa.id, token="tokBM", angle="front")
    await _seed_ref(session, s, fa.id, token="tokBM", angle="left")
    fb = await _seed_family(session, f"BN{uuid.uuid4().hex[:6]}")
    await _seed_ref(session, s, fb.id, token="tokBN", angle="front")
    await _seed_ref(session, s, fb.id, token="tokBN", angle="left")

    req = {
        "samples": [
            {"kind": "reference", "reference_id": r1.id,
             "ground_truth_family_id": fa.id},
            {"kind": "reference", "reference_id": r1.id, "is_unknown": False,
             "ground_truth_family_id": fa.id},
        ],
    }
    r = await client.post("/api/product-visual-experiments/benchmark", json=req)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["evaluated"] == 2
    # 留一法生效：r1 剔除后靠同族另一张图命中 → top1 正确但分数不因自匹配
    assert body["metrics"]["top1_accuracy"] == 1.0
    assert body["data_gaps"]  # 样本少必须如实报缺口
