"""PR-B 最终成片 / 使用血缘 API 测试（需要 TEST_DATABASE_URL）。

锁定 docs/FINAL_VIDEO_USAGE.md 的正式使用次数语义：
- 只有 confirmed 计数；proposed/suspected/rejected/revoked 不计数；
- UNIQUE(final_video_id, source_shot_id)：同片同镜头只算 1 次，多次出现记 occurrence；
- 不同成片分别计数；撤销立即重算；归档成片历史 confirmed 继续计数；
- propose-from-project 幂等且绝不覆盖人工状态；事件 append-only 与状态同事务。
"""

from __future__ import annotations

import asyncio
import os

import pytest
from clipmind_shared.db.base import utcnow
from clipmind_shared.models import (
    Asset,
    FinalVideoUsageEvent,
    Project,
    ScriptProject,
    ScriptSegment,
    Shot,
    SourceDirectory,
)
from clipmind_shared.models.enums import AssetStatus, ShotStatus
from sqlalchemy import delete, select

pytestmark = pytest.mark.skipif(
    not os.getenv("TEST_DATABASE_URL"), reason="需要 TEST_DATABASE_URL"
)


# ============================ 数据工厂 ============================


async def _seed_asset(session, *, filename="src.mp4", duration=10.0) -> Asset:
    sd = SourceDirectory(
        name=f"d-{filename}",
        mount_path="/app/source",
        include_extensions=["mp4"],
        exclude_patterns=[],
        recursive=True,
        read_only=True,
    )
    session.add(sd)
    await session.commit()
    await session.refresh(sd)
    asset = Asset(
        source_directory_id=sd.id,
        relative_path=filename,
        normalized_relative_path=filename,
        filename=filename,
        extension="mp4",
        file_size=1,
        duration=duration,
        status=AssetStatus.INDEXED,
        first_seen_at=utcnow(),
        last_seen_at=utcnow(),
    )
    session.add(asset)
    await session.commit()
    await session.refresh(asset)
    return asset


async def _seed_shot(session, asset, *, seq=1, start=0.0, end=2.0) -> Shot:
    shot = Shot(
        asset_id=asset.id,
        generation=1,
        sequence_no=seq,
        start_time=start,
        end_time=end,
        duration=end - start,
        detector_type="fixed",
        status=ShotStatus.READY,
        keyframe_path=f"k/{asset.id}-{seq}.jpg",
        proxy_path=f"p/{asset.id}-{seq}.mp4",
    )
    session.add(shot)
    await session.commit()
    await session.refresh(shot)
    return shot


async def _create_fv(client, asset_id, *, title="成片A", **extra) -> dict:
    r = await client.post(
        "/api/final-videos", json={"asset_id": asset_id, "title": title, **extra}
    )
    assert r.status_code == 201, r.text
    return r.json()


async def _add_usage(client, fv_id, shot_id, **extra) -> dict:
    r = await client.post(
        f"/api/final-videos/{fv_id}/usages",
        json={"source_shot_id": shot_id, **extra},
    )
    assert r.status_code == 201, r.text
    return r.json()


async def _confirm(client, usage_id, expect=200) -> dict:
    r = await client.post(f"/api/final-video-usages/{usage_id}/confirm")
    assert r.status_code == expect, r.text
    return r.json()


async def _shot_summary(client, shot_id) -> dict:
    r = await client.get(f"/api/shots/{shot_id}/usage-summary")
    assert r.status_code == 200, r.text
    return r.json()


# ============================ FinalVideo CRUD ============================


async def test_final_video_crud_and_asset_reference(client, session):
    asset = await _seed_asset(session, filename="final1.mp4", duration=30.0)
    # 不存在的 Asset → 404
    r = await client.post("/api/final-videos", json={"asset_id": 999999, "title": "x"})
    assert r.status_code == 404
    fv = await _create_fv(client, asset.id, title="发布版", version_label="v1")
    assert fv["asset_id"] == asset.id
    assert fv["status"] == "draft"
    assert fv["asset_filename"] == "final1.mp4"
    assert fv["asset_duration"] == 30.0
    # 同一 Asset 只能有一个活动成片 → 409
    r = await client.post("/api/final-videos", json={"asset_id": asset.id, "title": "b"})
    assert r.status_code == 409
    # PATCH
    r = await client.patch(
        f"/api/final-videos/{fv['id']}",
        json={"title": "发布版v2", "status": "ready", "description": "备注"},
    )
    assert r.status_code == 200
    assert r.json()["title"] == "发布版v2"
    assert r.json()["status"] == "ready"
    # PATCH 不允许 archived
    r = await client.patch(f"/api/final-videos/{fv['id']}", json={"status": "archived"})
    assert r.status_code == 422
    # 列表 / 详情
    r = await client.get("/api/final-videos")
    assert r.status_code == 200
    assert r.json()["total"] == 1
    r = await client.get(f"/api/final-videos/{fv['id']}")
    assert r.status_code == 200


async def test_final_video_archive_restore(client, session):
    asset = await _seed_asset(session, filename="final2.mp4")
    fv = await _create_fv(client, asset.id)
    r = await client.post(f"/api/final-videos/{fv['id']}/archive")
    assert r.status_code == 200
    assert r.json()["status"] == "archived"
    assert r.json()["archived_at"] is not None
    # 归档后默认列表不显示
    r = await client.get("/api/final-videos")
    assert r.json()["total"] == 0
    r = await client.get("/api/final-videos?include_archived=true")
    assert r.json()["total"] == 1
    # 归档后同 Asset 可建新的活动成片（部分唯一索引只约束未归档）
    fv2 = await _create_fv(client, asset.id, title="重制版")
    # 此时恢复旧成片 → 与新活动成片冲突 409
    r = await client.post(f"/api/final-videos/{fv['id']}/restore")
    assert r.status_code == 409
    # 归档新成片后恢复旧成片成功
    await client.post(f"/api/final-videos/{fv2['id']}/archive")
    r = await client.post(f"/api/final-videos/{fv['id']}/restore")
    assert r.status_code == 200
    assert r.json()["status"] == "draft"


# ============================ Usage 唯一关系 / 手工添加 ============================


async def test_manual_usage_proposed_and_unique(client, session):
    src = await _seed_asset(session, filename="s1.mp4")
    shot = await _seed_shot(session, src)
    final_asset = await _seed_asset(session, filename="f1.mp4")
    fv = await _create_fv(client, final_asset.id)

    usage = await _add_usage(client, fv["id"], shot.id)
    assert usage["status"] == "proposed"
    assert usage["evidence_method"] == "manual"
    assert usage["source_asset_id"] == src.id
    assert usage["shot"]["id"] == shot.id
    # 同片同镜头唯一 → 409
    r = await client.post(
        f"/api/final-videos/{fv['id']}/usages", json={"source_shot_id": shot.id}
    )
    assert r.status_code == 409
    # 手工添加不允许伪造其他 evidence_method → 422
    r = await client.post(
        f"/api/final-videos/{fv['id']}/usages",
        json={"source_shot_id": shot.id, "evidence_method": "visual_match"},
    )
    assert r.status_code == 422
    # 不存在的镜头 → 404
    r = await client.post(
        f"/api/final-videos/{fv['id']}/usages", json={"source_shot_id": 999999}
    )
    assert r.status_code == 404


async def test_self_reference_guard(client, session):
    final_asset = await _seed_asset(session, filename="f2.mp4")
    own_shot = await _seed_shot(session, final_asset)
    fv = await _create_fv(client, final_asset.id)
    r = await client.post(
        f"/api/final-videos/{fv['id']}/usages", json={"source_shot_id": own_shot.id}
    )
    assert r.status_code == 409


async def test_usage_requires_usable_shot(client, session):
    src = await _seed_asset(session, filename="s3.mp4")
    shot = await _seed_shot(session, src)
    shot.status = ShotStatus.FAILED
    await session.commit()
    final_asset = await _seed_asset(session, filename="f3.mp4")
    fv = await _create_fv(client, final_asset.id)
    r = await client.post(
        f"/api/final-videos/{fv['id']}/usages", json={"source_shot_id": shot.id}
    )
    assert r.status_code == 409
    # 源素材缺失同样拒绝
    shot.status = ShotStatus.READY
    src2 = await session.get(Asset, src.id)
    src2.status = AssetStatus.SOURCE_MISSING
    await session.commit()
    r = await client.post(
        f"/api/final-videos/{fv['id']}/usages", json={"source_shot_id": shot.id}
    )
    assert r.status_code == 409


# ============================ 状态机 / 使用次数语义 ============================


async def test_confirm_counts_and_noncounting_statuses(client, session):
    src = await _seed_asset(session, filename="s4.mp4")
    s1 = await _seed_shot(session, src, seq=1)
    s2 = await _seed_shot(session, src, seq=2)
    s3 = await _seed_shot(session, src, seq=3)
    final_asset = await _seed_asset(session, filename="f4.mp4")
    fv = await _create_fv(client, final_asset.id)

    u1 = await _add_usage(client, fv["id"], s1.id)
    u2 = await _add_usage(client, fv["id"], s2.id)
    u3 = await _add_usage(client, fv["id"], s3.id)

    # proposed 不计数
    assert (await _shot_summary(client, s1.id))["confirmed_usage_count"] == 0
    assert (await _shot_summary(client, s1.id))["proposed_count"] == 1

    # 确认 → 计数 1
    confirmed = await _confirm(client, u1["id"])
    assert confirmed["status"] == "confirmed"
    summary = await _shot_summary(client, s1.id)
    assert summary["confirmed_usage_count"] == 1
    assert summary["last_used_at"] is not None
    assert summary["final_videos"][0]["final_video_id"] == fv["id"]

    # rejected 不计数
    r = await client.post(f"/api/final-video-usages/{u2['id']}/reject")
    assert r.status_code == 200
    assert (await _shot_summary(client, s2.id))["confirmed_usage_count"] == 0

    # rejected 直接确认 → 409（须先恢复 proposed）
    await _confirm(client, u2["id"], expect=409)
    r = await client.post(f"/api/final-video-usages/{u2['id']}/restore-proposal")
    assert r.status_code == 200
    assert r.json()["status"] == "proposed"
    await _confirm(client, u2["id"])
    assert (await _shot_summary(client, s2.id))["confirmed_usage_count"] == 1

    # revoke → 立即不计数
    r = await client.post(f"/api/final-video-usages/{u2['id']}/revoke")
    assert r.status_code == 200
    assert (await _shot_summary(client, s2.id))["confirmed_usage_count"] == 0
    # revoked 直接确认 → 409
    await _confirm(client, u2["id"], expect=409)

    # 重复确认 → 409
    await _confirm(client, u1["id"], expect=409)
    # 未确认引用不能 revoke → 409
    r = await client.post(f"/api/final-video-usages/{u3['id']}/revoke")
    assert r.status_code == 409


async def test_distinct_final_video_counting(client, session):
    """同一 Shot 被不同成片确认 → 分别计数；撤销一条恢复为 1。"""
    src = await _seed_asset(session, filename="s5.mp4")
    shot = await _seed_shot(session, src)
    fa1 = await _seed_asset(session, filename="f5a.mp4")
    fa2 = await _seed_asset(session, filename="f5b.mp4")
    fv1 = await _create_fv(client, fa1.id, title="片1")
    fv2 = await _create_fv(client, fa2.id, title="片2")

    u1 = await _add_usage(client, fv1["id"], shot.id)
    u2 = await _add_usage(client, fv2["id"], shot.id)
    await _confirm(client, u1["id"])
    await _confirm(client, u2["id"])
    summary = await _shot_summary(client, shot.id)
    assert summary["confirmed_usage_count"] == 2
    assert len(summary["final_videos"]) == 2

    # 撤销其中一条 → 次数恢复 1
    await client.post(f"/api/final-video-usages/{u2['id']}/revoke")
    assert (await _shot_summary(client, shot.id))["confirmed_usage_count"] == 1


async def test_multiple_occurrences_count_once(client, session):
    src = await _seed_asset(session, filename="s6.mp4")
    shot = await _seed_shot(session, src, start=1.0, end=4.0)
    final_asset = await _seed_asset(session, filename="f6.mp4", duration=60.0)
    fv = await _create_fv(client, final_asset.id)
    u = await _add_usage(client, fv["id"], shot.id)
    await _confirm(client, u["id"])

    # 两个 occurrence
    r1 = await client.post(
        f"/api/final-video-usages/{u['id']}/occurrences",
        json={
            "source_start_ms": 1000,
            "source_end_ms": 2000,
            "final_start_ms": 0,
            "final_end_ms": 1000,
        },
    )
    assert r1.status_code == 201, r1.text
    assert r1.json()["occurrence_index"] == 0
    r2 = await client.post(
        f"/api/final-video-usages/{u['id']}/occurrences",
        json={
            "source_start_ms": 2500,
            "source_end_ms": 4000,
            "final_start_ms": 5000,
            "final_end_ms": 6500,
        },
    )
    assert r2.status_code == 201
    assert r2.json()["occurrence_index"] == 1

    # 两个 occurrence 仍只计 1 次
    assert (await _shot_summary(client, shot.id))["confirmed_usage_count"] == 1
    r = await client.get(f"/api/final-video-usages/{u['id']}/occurrences")
    assert len(r.json()["items"]) == 2

    # PATCH occurrence
    occ_id = r2.json()["id"]
    r = await client.patch(
        f"/api/final-video-usage-occurrences/{occ_id}", json={"final_end_ms": 7000}
    )
    assert r.status_code == 200
    assert r.json()["final_end_ms"] == 7000
    # DELETE occurrence
    r = await client.delete(f"/api/final-video-usage-occurrences/{occ_id}")
    assert r.status_code == 204
    r = await client.get(f"/api/final-video-usages/{u['id']}/occurrences")
    assert len(r.json()["items"]) == 1


async def test_occurrence_time_validation(client, session):
    src = await _seed_asset(session, filename="s7.mp4")
    shot = await _seed_shot(session, src, start=1.0, end=3.0)  # 1000–3000ms
    final_asset = await _seed_asset(session, filename="f7.mp4", duration=10.0)  # ≤10000ms
    fv = await _create_fv(client, final_asset.id)
    u = await _add_usage(client, fv["id"], shot.id)

    base = {"final_start_ms": 0, "final_end_ms": 1000}
    # end <= start → 422
    r = await client.post(
        f"/api/final-video-usages/{u['id']}/occurrences",
        json={"source_start_ms": 2000, "source_end_ms": 2000, **base},
    )
    assert r.status_code == 422
    # 越过 Shot 左边界 → 422
    r = await client.post(
        f"/api/final-video-usages/{u['id']}/occurrences",
        json={"source_start_ms": 500, "source_end_ms": 2000, **base},
    )
    assert r.status_code == 422
    # 越过 Shot 右边界 → 422
    r = await client.post(
        f"/api/final-video-usages/{u['id']}/occurrences",
        json={"source_start_ms": 1000, "source_end_ms": 3500, **base},
    )
    assert r.status_code == 422
    # final 越过成片时长 → 422
    r = await client.post(
        f"/api/final-video-usages/{u['id']}/occurrences",
        json={
            "source_start_ms": 1000,
            "source_end_ms": 2000,
            "final_start_ms": 9500,
            "final_end_ms": 10500,
        },
    )
    assert r.status_code == 422
    # 合法边界（含边界取整容差）
    r = await client.post(
        f"/api/final-video-usages/{u['id']}/occurrences",
        json={"source_start_ms": 1000, "source_end_ms": 3000, **base},
    )
    assert r.status_code == 201
    # 负数由 schema 拦截 → 422
    r = await client.post(
        f"/api/final-video-usages/{u['id']}/occurrences",
        json={"source_start_ms": -1, "source_end_ms": 2000, **base},
    )
    assert r.status_code == 422


# ============================ 归档守卫 ============================


async def test_archived_final_video_guards(client, session):
    src = await _seed_asset(session, filename="s8.mp4")
    s1 = await _seed_shot(session, src, seq=1)
    s2 = await _seed_shot(session, src, seq=2)
    final_asset = await _seed_asset(session, filename="f8.mp4")
    fv = await _create_fv(client, final_asset.id)
    u1 = await _add_usage(client, fv["id"], s1.id)
    u2 = await _add_usage(client, fv["id"], s2.id)
    await _confirm(client, u1["id"])

    r = await client.post(f"/api/final-videos/{fv['id']}/archive")
    assert r.status_code == 200

    # 归档成片：不允许新增 usage / 确认 proposed
    r = await client.post(
        f"/api/final-videos/{fv['id']}/usages", json={"source_shot_id": s2.id}
    )
    assert r.status_code == 409
    await _confirm(client, u2["id"], expect=409)
    # 历史 confirmed 继续计数
    assert (await _shot_summary(client, s1.id))["confirmed_usage_count"] == 1
    # 明确撤销才减少（归档成片允许撤销）
    r = await client.post(f"/api/final-video-usages/{u1['id']}/revoke")
    assert r.status_code == 200
    assert (await _shot_summary(client, s1.id))["confirmed_usage_count"] == 0


# ============================ propose-from-project ============================


async def _seed_project_with_script(session, *, locked_shot=None, selected_shot=None):
    proj = Project(name="项目P", lock_version=1)
    session.add(proj)
    await session.commit()
    await session.refresh(proj)
    sp = ScriptProject(name="脚本S", project_id=proj.id, raw_script="正文")
    session.add(sp)
    await session.commit()
    await session.refresh(sp)
    seg = ScriptSegment(
        script_project_id=sp.id,
        order_index=0,
        segment_text="段落1",
        locked_shot_id=locked_shot.id if locked_shot is not None else None,
        selected_shot_id=selected_shot.id if selected_shot is not None else None,
    )
    session.add(seg)
    await session.commit()
    await session.refresh(seg)
    return proj, sp, seg


async def test_propose_from_project_idempotent(client, session):
    src = await _seed_asset(session, filename="s9.mp4")
    locked = await _seed_shot(session, src, seq=1)
    selected = await _seed_shot(session, src, seq=2)
    proj, sp, seg = await _seed_project_with_script(
        session, locked_shot=locked, selected_shot=selected
    )
    final_asset = await _seed_asset(session, filename="f9.mp4")
    fv = await _create_fv(client, final_asset.id, project_id=proj.id)

    r = await client.post(f"/api/final-videos/{fv['id']}/propose-from-project")
    assert r.status_code == 200, r.text
    out = r.json()
    assert out["created"] == 2
    assert out["segments_scanned"] == 1

    # 生成的是 proposed + clipmind_project，且可追溯到 segment
    r = await client.get(f"/api/final-videos/{fv['id']}/usages")
    items = r.json()["items"]
    assert len(items) == 2
    for it in items:
        assert it["status"] == "proposed"
        assert it["evidence_method"] == "clipmind_project"
        assert it["evidence_refs"]["segments"][0]["segment_id"] == seg.id
    # proposed 不计数
    assert (await _shot_summary(client, locked.id))["confirmed_usage_count"] == 0

    # 幂等重跑：全部 existing，不新建
    r = await client.post(f"/api/final-videos/{fv['id']}/propose-from-project")
    assert r.json()["created"] == 0
    assert r.json()["existing"] == 2


async def test_proposal_never_overrides_human_status(client, session):
    src = await _seed_asset(session, filename="s10.mp4")
    locked = await _seed_shot(session, src, seq=1)
    proj, sp, seg = await _seed_project_with_script(session, locked_shot=locked)
    final_asset = await _seed_asset(session, filename="f10.mp4")
    fv = await _create_fv(client, final_asset.id, project_id=proj.id)

    await client.post(f"/api/final-videos/{fv['id']}/propose-from-project")
    r = await client.get(f"/api/final-videos/{fv['id']}/usages")
    uid = r.json()["items"][0]["id"]
    await _confirm(client, uid)

    # 重跑 proposal：confirmed 不被覆盖
    r = await client.post(f"/api/final-videos/{fv['id']}/propose-from-project")
    assert r.json()["created"] == 0
    assert r.json()["existing"] == 1
    r = await client.get(f"/api/final-video-usages/{uid}")
    assert r.json()["status"] == "confirmed"

    # rejected 同样不被覆盖
    await client.post(f"/api/final-video-usages/{uid}/revoke")
    r = await client.post(f"/api/final-videos/{fv['id']}/propose-from-project")
    assert r.json()["existing"] == 1
    r = await client.get(f"/api/final-video-usages/{uid}")
    assert r.json()["status"] == "revoked"


async def test_propose_requires_binding_and_skips_unavailable(client, session):
    src = await _seed_asset(session, filename="s11.mp4")
    bad_shot = await _seed_shot(session, src, seq=1)
    bad_shot.status = ShotStatus.FAILED
    await session.commit()
    proj, sp, seg = await _seed_project_with_script(session, locked_shot=bad_shot)
    final_asset = await _seed_asset(session, filename="f11.mp4")

    # 未绑定项目/脚本 → 409
    fv0 = await _create_fv(client, final_asset.id)
    r = await client.post(f"/api/final-videos/{fv0['id']}/propose-from-project")
    assert r.status_code == 409
    # 绑定后：不可用镜头 skip，不误生成
    r = await client.patch(f"/api/final-videos/{fv0['id']}", json={"project_id": proj.id})
    assert r.status_code == 200
    r = await client.post(f"/api/final-videos/{fv0['id']}/propose-from-project")
    assert r.status_code == 200
    assert r.json()["created"] == 0
    assert r.json()["skipped_unavailable"] == 1


# ============================ 并发唯一性 ============================


async def test_concurrent_usage_creation_no_duplicates(client, session):
    src = await _seed_asset(session, filename="s12.mp4")
    shot = await _seed_shot(session, src)
    final_asset = await _seed_asset(session, filename="f12.mp4")
    fv = await _create_fv(client, final_asset.id)

    async def _try():
        return await client.post(
            f"/api/final-videos/{fv['id']}/usages", json={"source_shot_id": shot.id}
        )

    r1, r2 = await asyncio.gather(_try(), _try())
    codes = sorted([r1.status_code, r2.status_code])
    assert codes == [201, 409]
    r = await client.get(f"/api/final-videos/{fv['id']}/usages")
    assert r.json()["total"] == 1


# ============================ 事件审计 ============================


async def test_events_append_only_and_transactional(client, session):
    src = await _seed_asset(session, filename="s13.mp4")
    shot = await _seed_shot(session, src, start=0.0, end=2.0)
    final_asset = await _seed_asset(session, filename="f13.mp4", duration=30.0)
    fv = await _create_fv(client, final_asset.id)
    u = await _add_usage(client, fv["id"], shot.id)
    await _confirm(client, u["id"])
    await client.post(
        f"/api/final-video-usages/{u['id']}/occurrences",
        json={
            "source_start_ms": 0,
            "source_end_ms": 1000,
            "final_start_ms": 0,
            "final_end_ms": 1000,
        },
    )
    await client.post(f"/api/final-video-usages/{u['id']}/revoke", json={"note": "错了"})

    r = await client.get(f"/api/final-video-usages/{u['id']}/events")
    actions = [e["action"] for e in r.json()["items"]]
    assert actions == ["manual_add", "confirm", "occurrence_add", "revoke"]
    revoke_ev = r.json()["items"][-1]
    assert revoke_ev["before_status"] == "confirmed"
    assert revoke_ev["after_status"] == "revoked"
    assert revoke_ev["note"] == "错了"

    # 失败动作不产生事件（事务一致）：revoked 再确认 → 409
    await _confirm(client, u["id"], expect=409)
    r = await client.get(f"/api/final-video-usages/{u['id']}/events")
    assert len(r.json()["items"]) == 4
    # 无事件更新/删除接口（路由不存在）
    r = await client.delete(f"/api/final-video-usages/{u['id']}/events")
    assert r.status_code == 405


# ============================ 统计 ============================


async def test_asset_usage_summary_and_batch_counts(client, session):
    src = await _seed_asset(session, filename="s14.mp4")
    s1 = await _seed_shot(session, src, seq=1)
    s2 = await _seed_shot(session, src, seq=2)
    s3 = await _seed_shot(session, src, seq=3)
    fa1 = await _seed_asset(session, filename="f14a.mp4")
    fa2 = await _seed_asset(session, filename="f14b.mp4")
    fv1 = await _create_fv(client, fa1.id, title="片1")
    fv2 = await _create_fv(client, fa2.id, title="片2")

    u11 = await _add_usage(client, fv1["id"], s1.id)
    u21 = await _add_usage(client, fv2["id"], s1.id)
    u12 = await _add_usage(client, fv1["id"], s2.id)
    await _confirm(client, u11["id"])
    await _confirm(client, u21["id"])
    await _confirm(client, u12["id"])

    r = await client.get(f"/api/assets/{src.id}/usage-summary")
    assert r.status_code == 200
    out = r.json()
    assert out["total_shots"] == 3
    assert out["used_shot_count"] == 2
    assert out["never_used_shot_count"] == 1
    assert out["distinct_final_video_count"] == 2
    assert out["usage_distribution"] == {"0": 1, "1": 1, "2": 1}
    assert out["last_used_at"] is not None

    # 批量计数（徽标）
    r = await client.get(
        f"/api/shot-usage-summaries?shot_ids={s1.id},{s2.id},{s3.id}"
    )
    items = {it["shot_id"]: it for it in r.json()["items"]}
    assert items[s1.id]["confirmed_usage_count"] == 2
    assert items[s2.id]["confirmed_usage_count"] == 1
    assert items[s3.id]["confirmed_usage_count"] == 0

    # lineage 全景
    r = await client.get(f"/api/final-videos/{fv1['id']}/lineage")
    assert r.status_code == 200
    lineage = r.json()
    assert lineage["final_video"]["id"] == fv1["id"]
    assert len(lineage["usages"]) == 2


# ============================ 删除/血缘保护 ============================


async def test_project_delete_does_not_touch_usage(client, session):
    """模拟未来 Project 删除：SET NULL 解绑，血缘与计数不受影响。"""
    src = await _seed_asset(session, filename="s15.mp4")
    shot = await _seed_shot(session, src)
    proj, sp, seg = await _seed_project_with_script(session, locked_shot=shot)
    final_asset = await _seed_asset(session, filename="f15.mp4")
    fv = await _create_fv(client, final_asset.id, project_id=proj.id)
    await client.post(f"/api/final-videos/{fv['id']}/propose-from-project")
    r = await client.get(f"/api/final-videos/{fv['id']}/usages")
    uid = r.json()["items"][0]["id"]
    await _confirm(client, uid)

    # 直接删 Project 行（当前无删除 API；验证 FK 行为）
    await session.execute(delete(Project).where(Project.id == proj.id))
    await session.commit()

    r = await client.get(f"/api/final-videos/{fv['id']}")
    assert r.json()["project_id"] is None
    assert (await _shot_summary(client, shot.id))["confirmed_usage_count"] == 1


async def test_reanalysis_allowed_when_lineage_exists(client, session):
    """PR-C：代次保留后有血缘素材也可安全重新分析（PR-B 的 409 守卫已解除）。"""
    src = await _seed_asset(session, filename="s16.mp4")
    shot = await _seed_shot(session, src)
    final_asset = await _seed_asset(session, filename="f16.mp4")
    fv = await _create_fv(client, final_asset.id)
    await _add_usage(client, fv["id"], shot.id)

    # 有血缘引用也允许重新分析（202；旧 Shot 将保留为 retired，血缘不断）
    r = await client.post(f"/api/assets/{src.id}/analyze-shots")
    assert r.status_code == 202, r.text
    # 无血缘素材同样正常
    other = await _seed_asset(session, filename="s16b.mp4")
    r = await client.post(f"/api/assets/{other.id}/analyze-shots")
    assert r.status_code == 202


async def test_usage_patch_meta(client, session):
    src = await _seed_asset(session, filename="s17.mp4")
    shot = await _seed_shot(session, src)
    final_asset = await _seed_asset(session, filename="f17.mp4")
    fv = await _create_fv(client, final_asset.id)
    u = await _add_usage(client, fv["id"], shot.id)
    r = await client.patch(
        f"/api/final-video-usages/{u['id']}",
        json={"review_note": "第 3 段用了", "confidence": 0.8},
    )
    assert r.status_code == 200
    assert r.json()["review_note"] == "第 3 段用了"
    assert r.json()["confidence"] == 0.8
    # confirmed 后 confidence 不可改
    await _confirm(client, u["id"])
    r = await client.patch(f"/api/final-video-usages/{u['id']}", json={"confidence": 1.0})
    assert r.status_code == 409
    # confidence 越界由 schema 拦截
    r = await client.patch(f"/api/final-video-usages/{u['id']}", json={"review_note": "ok"})
    assert r.status_code == 200


async def test_events_written_in_same_transaction(client, session):
    """事件与状态同事务：DB 中 usage 状态与事件序列始终一致。"""
    src = await _seed_asset(session, filename="s18.mp4")
    shot = await _seed_shot(session, src)
    final_asset = await _seed_asset(session, filename="f18.mp4")
    fv = await _create_fv(client, final_asset.id)
    u = await _add_usage(client, fv["id"], shot.id)
    await _confirm(client, u["id"])
    rows = (
        await session.scalars(
            select(FinalVideoUsageEvent).where(FinalVideoUsageEvent.usage_id == u["id"])
        )
    ).all()
    assert [e.action for e in rows] == ["manual_add", "confirm"]
    assert rows[-1].after_status == "confirmed"
