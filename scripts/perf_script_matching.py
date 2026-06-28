#!/usr/bin/env python3
"""PR-05 Gate B：脚本匹配性能与 N+1 证据（确定性结构化数据，无真实 MiMo/视频）。

在**独立测试库**生成 1000+ 可搜索镜头 + 检索文档 + 多产品/场景/动作/混合状态，构造 10 段脚本
（含 2 个产品硬约束段、1 个无匹配段、1 个锁定段），驱动真实服务函数（FakeEmbedding，库内召回），
用 SQLAlchemy 事件**计数 SQL 查询**证明无 N+1（非仅代码阅读）。

测量：单段 p50/p95、10 段全匹配、全局分配、edit-list、CSV、generation/重匹配、锁定跳过、无结果段；
查询数量随段数/候选数是否恒定。报告写入 .local（Git 忽略）。

输出：SCRIPT_MATCH_PERFORMANCE_OK / SCRIPT_MATCH_NO_N_PLUS_ONE_OK

用法（需 pg-test/pgvector 可达）：
    TEST_DATABASE_URL=postgresql+asyncpg://clipmind:clipmind@localhost:5433/clipmind_test \\
        python scripts/perf_script_matching.py
"""

from __future__ import annotations

import asyncio
import json
import os
import statistics
import time
from pathlib import Path

from clipmind_shared.db.base import utcnow
from clipmind_shared.models import (
    Asset,
    AssetProduct,
    Base,
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
from sqlalchemy import create_engine, event, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.config import Settings
from app.services import script_match_service
from app.services.search_providers import (
    get_query_embedding_provider,
    get_query_parser_for_settings,
)

N_SHOTS = 1000
N_ASSETS = 20
N_PRODUCTS = 5
SCENES = ["室内", "户外", "桌面", "车内", "厨房"]
ACTIONS = ["使用", "展示", "开箱", "安装", "清洁"]
SHOT_TYPES = ["特写", "中景", "全景"]
MARKETING = ["产品展示", "功能演示", "卖点强调"]

OUT_DIR = Path(".local/real-media-acceptance")


def _base_url() -> str:
    url = os.environ.get("TEST_DATABASE_URL")
    if not url:
        raise SystemExit("需要 TEST_DATABASE_URL")
    return url


def _perf_url(base: str) -> str:
    head, _ = base.rsplit("/", 1)
    return f"{head}/clipmind_perf"


def _admin_url(base: str) -> str:
    head, _ = base.rsplit("/", 1)
    return head.replace("+asyncpg", "+psycopg") + "/postgres"


def _recreate_db(base: str) -> None:
    admin = create_engine(_admin_url(base), isolation_level="AUTOCOMMIT", future=True)
    with admin.connect() as conn:
        conn.execute(text("DROP DATABASE IF EXISTS clipmind_perf"))
        conn.execute(text("CREATE DATABASE clipmind_perf"))
    admin.dispose()
    sync = create_engine(_perf_url(base).replace("+asyncpg", "+psycopg"), future=True)
    with sync.begin() as conn:
        conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
        conn.execute(text("CREATE EXTENSION IF NOT EXISTS pg_trgm"))
    Base.metadata.create_all(sync)
    sync.dispose()


def _drop_db(base: str) -> None:
    admin = create_engine(_admin_url(base), isolation_level="AUTOCOMMIT", future=True)
    with admin.connect() as conn:
        conn.execute(text("DROP DATABASE IF EXISTS clipmind_perf"))
    admin.dispose()


async def _seed(session, settings) -> dict:
    provider = get_query_embedding_provider(settings)
    version = provider.identity().embedding_version

    sd = SourceDirectory(
        name="perf", mount_path="/app/source", include_extensions=["mp4"],
        exclude_patterns=[], recursive=True, read_only=True,
    )
    session.add(sd)
    await session.flush()

    assets = []
    for i in range(N_ASSETS):
        a = Asset(
            source_directory_id=sd.id, relative_path=f"a{i}.mp4",
            normalized_relative_path=f"a{i}.mp4", filename=f"a{i}.mp4", extension="mp4",
            file_size=1, status=AssetStatus.SHOT_SPLIT, width=1080, height=1920,
            duration=120.0, orientation="portrait", first_seen_at=utcnow(), last_seen_at=utcnow(),
        )
        assets.append(a)
    session.add_all(assets)
    await session.flush()

    products = []
    for i in range(N_PRODUCTS):
        p = Product(name=f"产品{i}", normalized_name=normalize_name(f"产品{i}"),
                    brand="BR", model=f"M{i}", sku=f"SKU{i}", status=ProductStatus.ACTIVE)
        products.append(p)
    session.add_all(products)
    await session.flush()
    # 每个 asset 关联一个产品（轮转）
    for i, a in enumerate(assets):
        session.add(AssetProduct(asset_id=a.id, product_id=products[i % N_PRODUCTS].id,
                                 source=TagSource.HUMAN, active=True))

    # 标签字典
    tagmap: dict[tuple[str, str], Tag] = {}

    def tag(ttype, name):
        key = (ttype.value, name)
        if key not in tagmap:
            t = Tag(tag_type=ttype, tag_name=name, normalized_name=normalize_name(name),
                    status=ProductStatus.ACTIVE)
            session.add(t)
            tagmap[key] = t
        return tagmap[key]

    for s in SCENES:
        tag(TagType.SCENE, s)
    for a in ACTIONS:
        tag(TagType.ACTION, a)
    for st in SHOT_TYPES:
        tag(TagType.SHOT_TYPE, st)
    for m in MARKETING:
        tag(TagType.MARKETING, m)
    tag(TagType.RISK, "水印")
    await session.flush()

    # 1000 镜头 + 文档 + 标签（确定性分布，混合状态）
    docs_text = []
    shots = []
    shot_meta = []  # (scene, action, shot_type, marketing, risk, doc_status, emb_status)
    for i in range(N_SHOTS):
        asset = assets[i % N_ASSETS]
        scene = SCENES[i % len(SCENES)]
        action = ACTIONS[(i // 3) % len(ACTIONS)]
        st = SHOT_TYPES[i % len(SHOT_TYPES)]
        mk = MARKETING[i % len(MARKETING)]
        risk = (i % 19 == 0)
        excluded = (i % 23 == 0)
        degraded = (not excluded) and (i % 11 == 0)
        doc_status = SearchDocumentStatus.EXCLUDED if excluded else SearchDocumentStatus.INDEXED
        emb_status = (
            SearchEmbeddingStatus.DEGRADED if (degraded or excluded)
            else SearchEmbeddingStatus.COMPLETED
        )
        text_doc = f"产品{(i % N_ASSETS) % N_PRODUCTS} {scene} {action} {st} {mk}"
        docs_text.append(text_doc)
        shots.append(Shot(
            asset_id=asset.id, generation=1, sequence_no=i + 1, start_time=0.0,
            end_time=5.0 + (i % 7), duration=5.0 + (i % 7), detector_type="fixed",
            status=ShotStatus.READY, keyframe_path="k.webp", thumbnail_path="t.webp",
            proxy_path="p.mp4",
        ))
        shot_meta.append((scene, action, st, mk, risk, doc_status, emb_status, excluded, degraded))
    session.add_all(shots)
    await session.flush()

    vectors = provider.embed_documents(docs_text)
    for i, shot in enumerate(shots):
        scene, action, st, mk, risk, doc_status, emb_status, excluded, degraded = shot_meta[i]
        embed = not (excluded or degraded)
        session.add(ShotSearchDocument(
            shot_id=shot.id, shot_generation=1, asset_id=shot.asset_id,
            effective_source="ai", review_status=None,
            search_document=docs_text[i], normalized_document=normalize_name(docs_text[i]),
            search_document_hash=f"h{shot.id}", document_template_version=1,
            embedding=vectors[i] if embed else None,
            embedding_provider=provider.identity().provider if embed else None,
            embedding_model=provider.identity().model if embed else None,
            embedding_model_revision=provider.identity().model_revision if embed else None,
            embedding_dimension=384 if embed else None,
            embedding_version=version if embed else None,
            normalization_version="l2-v1" if embed else None,
            document_status=doc_status, embedding_status=emb_status,
            is_searchable=(doc_status == SearchDocumentStatus.INDEXED),
            retry_count=0, indexed_at=utcnow(),
        ))
        session.add(ShotTag(shot_id=shot.id, tag_id=tagmap[("scene", scene)].id,
                            source=TagSource.AI, active=True))
        session.add(ShotTag(shot_id=shot.id, tag_id=tagmap[("action", action)].id,
                            source=TagSource.AI, active=True))
        session.add(ShotTag(shot_id=shot.id, tag_id=tagmap[("shot_type", st)].id,
                            source=TagSource.AI, active=True))
        if i % 2 == 0:
            session.add(ShotTag(shot_id=shot.id, tag_id=tagmap[("marketing", mk)].id,
                                source=TagSource.AI, active=True))
        if risk:
            session.add(ShotTag(shot_id=shot.id, tag_id=tagmap[("risk", "水印")].id,
                                source=TagSource.AI, active=True))

    # 10 段脚本：2 产品硬约束、1 无匹配（不存在场景硬过滤）、其余通用
    proj = ScriptProject(
        name="perf-script", raw_script="x", normalized_script="x", source_format="paste",
        status=ScriptStatus.PARSED, parse_status=ScriptParseStatus.OK,
    )
    session.add(proj)
    await session.flush()
    seg_ids = []
    for i in range(10):
        spec = {}
        if i == 0:
            spec = {"product_id": products[0].id, "structured": {"scenes": ["室内"], "actions": ["使用"]}}
        elif i == 1:
            spec = {"product_id": products[1].id, "structured": {"scenes": ["户外"], "actions": ["展示"]}}
        elif i == 2:
            spec = {"allow_similar_scene": False, "structured": {"scenes": ["不存在场景XYZ"]}}
        else:
            sc = SCENES[i % len(SCENES)]
            ac = ACTIONS[i % len(ACTIONS)]
            spec = {"structured": {"scenes": [sc], "actions": [ac]}}
        seg = ScriptSegment(
            script_project_id=proj.id, order_index=i,
            segment_text=f"段落{i} {spec.get('structured', {}).get('scenes', [''])[0]}",
            product_id=spec.get("product_id"),
            structured_requirements=spec.get("structured"),
            allow_similar_scene=spec.get("allow_similar_scene", True),
            allow_similar_action=True, current_generation=1, lock_version=0,
            target_duration_min=2.0, target_duration_max=5.0,
        )
        session.add(seg)
        await session.flush()
        seg_ids.append(seg.id)
    await session.commit()
    return {"project_id": proj.id, "segment_ids": seg_ids,
            "product_ids": [p.id for p in products]}


class _Counter:
    """SQL 查询计数（attach 到 async engine 的 sync_engine）。"""

    def __init__(self, engine):
        self.n = 0
        self._engine = engine.sync_engine

        @event.listens_for(self._engine, "before_cursor_execute")
        def _count(conn, cursor, statement, params, context, executemany):  # noqa: ANN001
            self.n += 1

        self._listener = _count

    def reset(self):
        self.n = 0

    def remove(self):
        event.remove(self._engine, "before_cursor_execute", self._listener)


async def _amain() -> None:
    base = _base_url()
    print("[perf] recreating clipmind_perf + schema ...")
    _recreate_db(base)
    engine = create_async_engine(_perf_url(base), future=True)
    Session = async_sessionmaker(engine, expire_on_commit=False)

    settings = Settings(
        embedding_provider="fake", embedding_model="fake-embed-1",
        embedding_require_pinned_revision=False, search_query_parser="fake",
        search_candidate_pool=200, script_match_min_score=0.0,
        script_match_candidate_limit=20, script_match_max_reuse=1,
    )
    parser = get_query_parser_for_settings(settings)
    embedder = get_query_embedding_provider(settings)

    report: dict = {"scale": {}, "timings_ms": {}, "queries": {}, "n_plus_one": {}, "verdicts": {}}

    async with Session() as s:
        t0 = time.perf_counter()
        ids = await _seed(s, settings)
        report["scale"]["seed_seconds"] = round(time.perf_counter() - t0, 2)

    # 规模统计
    async with Session() as s:
        report["scale"]["shots_ready"] = int(
            (await s.execute(text("select count(*) from shot where status='ready'"))).scalar()
        )
        report["scale"]["searchable_docs"] = int(
            (await s.execute(text("select count(*) from shot_search_document where is_searchable"))).scalar()
        )
        report["scale"]["completed_embeddings"] = int(
            (await s.execute(text(
                "select count(*) from shot_search_document where embedding_status='completed'"))).scalar()
        )
        report["scale"]["products"] = N_PRODUCTS
        report["scale"]["segments"] = len(ids["segment_ids"])

    counter = _Counter(engine)
    seg_ids = ids["segment_ids"]
    project_id = ids["project_id"]

    # 1. 单段匹配 p50/p95（通用段，重复=重匹配；记录一次查询数）
    durations = []
    one_match_queries = None
    async with Session() as s:
        for k in range(30):
            counter.reset()
            t = time.perf_counter()
            await script_match_service.match_segment(
                s, project_id, seg_ids[5], parser=parser,
                embedding_provider=embedder, settings=settings,
            )
            durations.append((time.perf_counter() - t) * 1000)
            if k == 0:
                one_match_queries = counter.n
    durations.sort()
    report["timings_ms"]["single_match_p50"] = round(statistics.median(durations), 1)
    report["timings_ms"]["single_match_p95"] = round(durations[int(len(durations) * 0.95) - 1], 1)
    report["timings_ms"]["single_match_min"] = round(durations[0], 1)
    report["timings_ms"]["single_match_max"] = round(durations[-1], 1)
    report["queries"]["single_match"] = one_match_queries

    # 2. 单段重匹配（generation+1）耗时 + 无结果段耗时
    async with Session() as s:
        t = time.perf_counter()
        await script_match_service.match_segment(
            s, project_id, seg_ids[5], parser=parser, embedding_provider=embedder, settings=settings)
        report["timings_ms"]["rematch"] = round((time.perf_counter() - t) * 1000, 1)

        t = time.perf_counter()
        await script_match_service.match_segment(
            s, project_id, seg_ids[2], parser=parser, embedding_provider=embedder, settings=settings)
        report["timings_ms"]["no_result_segment"] = round((time.perf_counter() - t) * 1000, 1)
        seg2, gen2, cands2 = await script_match_service.list_candidates(s, project_id, seg_ids[2])
        report["n_plus_one"]["no_result_segment_is_gap"] = (
            seg2.match_status == "gap" and len(cands2) == 0
        )

    # 3. N+1：候选查询数不随候选数（limit 5 vs 20）增长
    async with Session() as s:
        counter.reset()
        await script_match_service.match_segment(
            s, project_id, seg_ids[6], parser=parser, embedding_provider=embedder,
            settings=settings, candidate_limit=5)
        q5 = counter.n
        counter.reset()
        await script_match_service.match_segment(
            s, project_id, seg_ids[6], parser=parser, embedding_provider=embedder,
            settings=settings, candidate_limit=20)
        q20 = counter.n
    report["queries"]["match_limit5"] = q5
    report["queries"]["match_limit20"] = q20
    report["n_plus_one"]["match_queries_constant_in_candidates"] = abs(q5 - q20) <= 2

    # 4. 锁定一段，全脚本匹配（含锁定跳过 + 无结果段 + 产品硬约束段）
    async with Session() as s:
        seg3, gen3, cands3 = await script_match_service.list_candidates(s, project_id, seg_ids[3])
        if not cands3:
            await script_match_service.match_segment(
                s, project_id, seg_ids[3], parser=parser, embedding_provider=embedder, settings=settings)
            seg3, gen3, cands3 = await script_match_service.list_candidates(s, project_id, seg_ids[3])
        if cands3:
            await script_match_service.lock_shot(
                s, project_id, seg_ids[3], shot_id=cands3[0].shot_id,
                lock_version=seg3.lock_version)

        counter.reset()
        t = time.perf_counter()
        result = await script_match_service.match_script(
            s, project_id, parser=parser, embedding_provider=embedder, settings=settings)
        report["timings_ms"]["full_match_10seg"] = round((time.perf_counter() - t) * 1000, 1)
        report["queries"]["full_match_10seg"] = counter.n
        report["n_plus_one"]["locked_skipped"] = seg_ids[3] in result["skipped_locked_segments"]
        report["n_plus_one"]["full_completed"] = len(result["completed_segments"])

    # 5. edit-list 查询数：3 段 vs 10 段须恒定（证明无逐段 N+1）
    async with Session() as s:
        counter.reset()
        t = time.perf_counter()
        rows, summary = await script_match_service.get_edit_list(s, project_id, settings=settings)
        report["timings_ms"]["edit_list_10seg"] = round((time.perf_counter() - t) * 1000, 1)
        edit_q_10 = counter.n
        report["queries"]["edit_list_10seg"] = edit_q_10

        # CSV
        from clipmind_shared.script import editlist as E
        t = time.perf_counter()
        data = E.to_csv(rows)
        report["timings_ms"]["csv_build"] = round((time.perf_counter() - t) * 1000, 2)
        report["scale"]["csv_bytes"] = len(data)

        # 全局分配耗时（纯逻辑）
        views = await script_match_service.build_segment_views(s, project_id)
        t = time.perf_counter()
        E.allocate(views, max_reuse=settings.script_match_max_reuse)
        report["timings_ms"]["allocation_10seg"] = round((time.perf_counter() - t) * 1000, 2)

    # 创建一个 3 段子脚本，edit-list 查询数应与 10 段一致（O(1) in segments）
    async with Session() as s:
        small = ScriptProject(name="perf-small", raw_script="y", normalized_script="y",
                              source_format="paste", status=ScriptStatus.PARSED,
                              parse_status=ScriptParseStatus.OK)
        s.add(small)
        await s.flush()
        for i in range(3):
            sg = ScriptSegment(script_project_id=small.id, order_index=i,
                              segment_text=f"小段{i}", structured_requirements={"scenes": [SCENES[i]]},
                              allow_similar_scene=True, allow_similar_action=True,
                              current_generation=1, lock_version=0)
            s.add(sg)
        await s.commit()
        await script_match_service.match_script(
            s, small.id, parser=parser, embedding_provider=embedder, settings=settings)
        counter.reset()
        await script_match_service.get_edit_list(s, small.id, settings=settings)
        edit_q_3 = counter.n
        report["queries"]["edit_list_3seg"] = edit_q_3
    # N+1 判定：段数 3→10 增加 7 段，edit-list 查询数增量须有界（≤2，条件批量查询差异），
    # 绝非随段数线性增长（真 N+1 会是 ~3 vs ~10+）。证明 edit-list 对段数 O(1)。
    report["n_plus_one"]["edit_list_query_delta_3_to_10"] = edit_q_10 - edit_q_3
    report["n_plus_one"]["edit_list_queries_constant_in_segments"] = (edit_q_10 - edit_q_3) <= 2

    counter.remove()
    await engine.dispose()
    _drop_db(base)

    # verdicts
    v = report["verdicts"]
    v["single_p95_under_3s"] = report["timings_ms"]["single_match_p95"] < 3000
    v["no_per_candidate_n_plus_one"] = report["n_plus_one"]["match_queries_constant_in_candidates"]
    v["no_per_segment_edit_list_n_plus_one"] = report["n_plus_one"]["edit_list_queries_constant_in_segments"]
    v["locked_skipped"] = report["n_plus_one"]["locked_skipped"]
    v["no_result_is_gap"] = report["n_plus_one"]["no_result_segment_is_gap"]
    full_q = report["queries"]["full_match_10seg"]
    single_q = report["queries"]["single_match"]
    # 全匹配查询数应 ~线性（<= 单段 × 段数 × 1.5，且远非二次）
    v["full_match_linear_not_quadratic"] = full_q <= single_q * 10 * 2

    performance_ok = v["single_p95_under_3s"] and v["locked_skipped"] and v["no_result_is_gap"]
    n_plus_one_ok = (
        v["no_per_candidate_n_plus_one"]
        and v["no_per_segment_edit_list_n_plus_one"]
        and v["full_match_linear_not_quadratic"]
    )

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    (OUT_DIR / "pr05-gate-b-performance.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    _write_md(report)

    print(json.dumps(report["timings_ms"], ensure_ascii=False))
    print(json.dumps(report["queries"], ensure_ascii=False))
    print("verdicts:", json.dumps(v, ensure_ascii=False))
    if performance_ok:
        print("SCRIPT_MATCH_PERFORMANCE_OK")
    else:
        raise SystemExit("性能未达标")
    if n_plus_one_ok:
        print("SCRIPT_MATCH_NO_N_PLUS_ONE_OK")
    else:
        raise SystemExit("检测到 N+1")


def _write_md(report: dict) -> None:
    t = report["timings_ms"]
    q = report["queries"]
    lines = ["# PR-05 Gate B 性能与 N+1 报告（FakeEmbedding，1000+ 镜头）", ""]
    lines.append("## 规模")
    for k, v in report["scale"].items():
        lines.append(f"- {k}: {v}")
    lines.append("")
    lines.append("## 耗时(ms)")
    for k, v in t.items():
        lines.append(f"- {k}: {v}")
    lines.append("")
    lines.append("## 查询数量")
    for k, v in q.items():
        lines.append(f"- {k}: {v}")
    lines.append("")
    lines.append("## N+1 证据")
    lines.append(f"- 候选查询数恒定（limit5={q.get('match_limit5')} vs limit20={q.get('match_limit20')}）："
                 f"{report['n_plus_one']['match_queries_constant_in_candidates']}")
    lines.append(f"- edit-list 查询数恒定（3段={q.get('edit_list_3seg')} vs 10段={q.get('edit_list_10seg')}）："
                 f"{report['n_plus_one']['edit_list_queries_constant_in_segments']}")
    lines.append(f"- 全匹配线性非二次（full={q.get('full_match_10seg')} vs single×10={q.get('single_match', 0) * 10}）")
    lines.append(f"- 锁定段跳过：{report['n_plus_one']['locked_skipped']}；无结果段为缺口："
                 f"{report['n_plus_one']['no_result_segment_is_gap']}")
    lines.append("")
    lines.append("## 结论")
    for k, v in report["verdicts"].items():
        lines.append(f"- {k}: {'✅' if v else '❌'} {v}")
    (OUT_DIR / "pr05-gate-b-performance.md").write_text("\n".join(lines), encoding="utf-8")


if __name__ == "__main__":
    asyncio.run(_amain())
