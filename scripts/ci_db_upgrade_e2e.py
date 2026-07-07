#!/usr/bin/env python3
"""已有数据库升级路径端到端（0008 → head；含 0009-0020 各阶段表结构与数据保持断言）。

复现并验证"已有数据库升级"可靠性：用独立测试库 ``clipmind_upgrade_test``（绝不碰真实业务库）
migrate 至 0008 → 写入 Gate A 业务数据 → 运行**正式升级命令** ``scripts/db_upgrade.sh``
（内部 ``docker compose run --rm migrate``，不依赖 up -d 的 migrate 跳过行为）→ 自动到 head
（当前 0010_projects_collections）：0009 Gate B 表/列 + 0010 项目/集合表/列出现、旧数据不丢、
历史 script_project.project_id 保持 NULL（不回填）→ 再次升级幂等。

输出：
    SCRIPT_DB_UPGRADE_OK
    PROJECTS_DB_UPGRADE_OK
    SCRIPT_DB_UPGRADE_IDEMPOTENT_OK

用法（需 compose 栈的 postgres 在运行）：
    python scripts/ci_db_upgrade_e2e.py
"""

from __future__ import annotations

import os
import platform
import subprocess
import sys

TEST_DB = "clipmind_upgrade_test"


def _bash() -> str:
    """选择正确的 bash：Windows 用 Git Bash（避免 WSL bash 拦截无法访问 docker）；Linux/CI 用 bash。"""
    if platform.system() == "Windows":
        for p in (
            r"C:\Program Files\Git\bin\bash.exe",
            r"C:\Program Files (x86)\Git\bin\bash.exe",
        ):
            if os.path.exists(p):
                return p
    return "bash"
ASYNC_URL = f"postgresql+asyncpg://clipmind:clipmind@postgres:5432/{TEST_DB}"


def _run(cmd: list[str], **kw) -> subprocess.CompletedProcess[str]:
    # errors="replace"：docker/compose 在部分平台输出非 UTF-8 字节，宽松解码避免崩溃
    return subprocess.run(
        cmd, capture_output=True, text=True, encoding="utf-8", errors="replace", **kw
    )


def psql(db: str, sql: str, *, single=True) -> str:
    cmd = ["docker", "compose", "exec", "-T", "postgres", "psql", "-U", "clipmind", "-d", db]
    cmd += (["-tAc", sql] if single else ["-c", sql])
    out = _run(cmd, timeout=60)
    if out.returncode != 0:
        print(f"psql 失败: {out.stderr.strip()}", file=sys.stderr)
    return out.stdout.strip()


def compose_migrate(database_url: str, *extra_args: str) -> subprocess.CompletedProcess[str]:
    cmd = ["docker", "compose", "run", "--rm", "-e", f"DATABASE_URL={database_url}", "migrate"]
    cmd += list(extra_args)
    return _run(cmd, timeout=300)


def db_upgrade_script(database_url: str) -> subprocess.CompletedProcess[str]:
    env = {**os.environ, "DB_UPGRADE_DATABASE_URL": database_url}
    return _run([_bash(), "scripts/db_upgrade.sh"], env=env, timeout=300)


def main() -> None:
    # 0. 重建独立测试库（CREATE DATABASE 不能在事务中，单独执行）
    psql("postgres", f"DROP DATABASE IF EXISTS {TEST_DB}")
    psql("postgres", f"CREATE DATABASE {TEST_DB}")

    # 1. 升级到 0008（模拟"已有 Gate A 数据库"）
    r = compose_migrate(ASYNC_URL, "alembic", "upgrade", "0008_script_matching")
    assert r.returncode == 0, f"upgrade 0008 失败: {r.stderr}"
    rev = psql(TEST_DB, "select version_num from alembic_version")
    assert rev == "0008_script_matching", f"应停在 0008，实际 {rev}"
    no_export = psql(TEST_DB, "select to_regclass('public.script_export')")
    assert no_export in ("", "\\N"), f"0008 不应有 script_export，实际 {no_export!r}"
    print(f"  baseline at {rev}; script_export absent")

    # 2. 写入 Gate A 业务数据（升级须保留）
    psql(
        TEST_DB,
        "insert into script_project(name, raw_script, source_format, status, parse_status, "
        "result_schema_version, created_at, updated_at) "
        "values('upgrade-marker','x','paste','parsed','ok',1, now(), now())",
    )
    pid = psql(TEST_DB, "select id from script_project where name='upgrade-marker'")
    psql(
        TEST_DB,
        "insert into script_segment(script_project_id, order_index, segment_text, "
        "allow_similar_scene, allow_similar_action, current_generation, lock_version, "
        "candidates_stale, created_at, updated_at) "
        f"values({pid}, 0, 'marker-seg', true, true, 1, 0, false, now(), now())",
    )
    seg_before = psql(TEST_DB, f"select count(*) from script_segment where script_project_id={pid}")
    print(f"  seeded Gate A data: project={pid} segments={seg_before}")

    # 3. 正式升级命令（db_upgrade.sh → docker compose run --rm migrate）
    up = db_upgrade_script(ASYNC_URL)
    assert up.returncode == 0, "db_upgrade.sh 非零退出"
    assert up.stdout and "SCRIPT_DB_UPGRADE_OK" in up.stdout, "db_upgrade.sh 未输出 OK 标志"
    print("  db_upgrade.sh ran: SCRIPT_DB_UPGRADE_OK emitted by official command")

    # 4. 自动到 head（0020）：… + 0019 产品素材关系 + 0020 操作审计
    rev2 = psql(TEST_DB, "select version_num from alembic_version")
    assert rev2 == "0022_visual_auto", f"应到 head 0022，实际 {rev2}"
    # 0009 Gate B 仍在
    has_export = psql(TEST_DB, "select to_regclass('public.script_export')")
    assert has_export == "script_export", "应有 script_export 表（0009）"
    has_col = psql(
        TEST_DB,
        "select count(*) from information_schema.columns where table_name='script_segment' "
        "and column_name='selected_shot_id'",
    )
    assert has_col == "1", "script_segment 应有 selected_shot_id 列（0009）"
    seg_after = psql(TEST_DB, f"select count(*) from script_segment where script_project_id={pid}")
    assert seg_after == seg_before, f"升级后业务数据丢失：{seg_before} -> {seg_after}"
    print(f"  upgraded to {rev2}; script_export+selected_shot_id present; data preserved "
          f"(segments={seg_after})")
    print("SCRIPT_DB_UPGRADE_OK")

    # 4b. 0010 项目/集合 表/列出现；历史 script_project.project_id 保持 NULL（不回填）
    for tbl in ("project", "project_asset", "project_shot", "project_product",
                "collection", "collection_shot"):
        assert psql(TEST_DB, f"select to_regclass('public.{tbl}')") == tbl, f"应有 {tbl} 表（0010）"
    has_pid = psql(
        TEST_DB,
        "select count(*) from information_schema.columns where table_name='script_project' "
        "and column_name='project_id'",
    )
    assert has_pid == "1", "script_project 应有 project_id 列（0010）"
    hist_null = psql(
        TEST_DB,
        f"select count(*) from script_project where id={pid} and project_id is null",
    )
    assert hist_null == "1", "历史 script_project.project_id 应保持 NULL（不回填）"
    proj_rows = psql(TEST_DB, "select count(*) from project")
    assert proj_rows == "0", "升级不应创建任何 project 行"
    print("  0010 project/collection tables + script_project.project_id present; "
          "historical project_id NULL; no project rows created")
    print("PROJECTS_DB_UPGRADE_OK")

    # 4c. 0011 导出中心列：export/script_export.project_id + export_format 列宽 16 + download_log
    for tbl, col in (("export", "project_id"), ("script_export", "project_id")):
        cnt = psql(
            TEST_DB,
            f"select count(*) from information_schema.columns where table_name='{tbl}' "
            f"and column_name='{col}'",
        )
        assert cnt == "1", f"{tbl}.{col} 应存在（0011）"
    fmt_len = psql(
        TEST_DB,
        "select character_maximum_length from information_schema.columns "
        "where table_name='script_export' and column_name='export_format'",
    )
    assert fmt_len == "16", f"script_export.export_format 列宽应为 16（0011），实际 {fmt_len}"
    assert psql(TEST_DB, "select to_regclass('public.download_log')") == "download_log", \
        "应有 download_log 表（0011）"

    # 4d. 0012 库表：saved_search / favorite / dynamic_collection / bundle_export
    for tbl in ("saved_search", "favorite", "dynamic_collection", "bundle_export"):
        assert psql(TEST_DB, f"select to_regclass('public.{tbl}')") == tbl, f"应有 {tbl} 表（0012）"
    # 历史业务数据仍未丢
    seg_06b = psql(TEST_DB, f"select count(*) from script_segment where script_project_id={pid}")
    assert seg_06b == seg_before, "0011/0012 升级后业务数据丢失"
    print("  0011 export/script_export.project_id + export_format(16) + download_log; "
          "0012 saved_search/favorite/dynamic_collection/bundle_export present; data intact")
    print("EXPORT_CENTER_DB_UPGRADE_OK")

    # 4e. 0013 通用产品目录表出现；既有扁平 product 及 script_segment 业务数据不丢
    for tbl in ("product_category", "product_family", "product_variant", "product_sku",
                "product_catalog_alias"):
        assert psql(TEST_DB, f"select to_regclass('public.{tbl}')") == tbl, f"应有 {tbl} 表（0013）"
    seg_a1 = psql(TEST_DB, f"select count(*) from script_segment where script_project_id={pid}")
    assert seg_a1 == seg_before, "0013 升级后业务数据丢失"
    print("  0013 product_category/family/variant/sku/product_catalog_alias present; data intact")
    print("CATALOG_DB_UPGRADE_OK")

    # 4f. 0014 动态属性 + 参考图表出现；既有业务数据不丢
    for tbl in ("product_attribute_definition", "product_attribute_value",
                "product_reference_asset"):
        assert psql(TEST_DB, f"select to_regclass('public.{tbl}')") == tbl, f"应有 {tbl} 表（0014）"
    seg_a2 = psql(TEST_DB, f"select count(*) from script_segment where script_project_id={pid}")
    assert seg_a2 == seg_before, "0014 升级后业务数据丢失"
    print("  0014 product_attribute_definition/value/reference_asset present; data intact")
    print("ATTR_REF_DB_UPGRADE_OK")

    # 4g. 0015 入驻治理表 + revision 序列出现；既有业务数据不丢
    for tbl in ("product_readiness_policy", "product_onboarding_review",
                "product_confusion_pair", "catalog_revision"):
        assert psql(TEST_DB, f"select to_regclass('public.{tbl}')") == tbl, f"应有 {tbl} 表（0015）"
    seq = psql(TEST_DB,
               "select count(*) from pg_sequences where sequencename='catalog_revision_seq'")
    assert seq == "1", "应有 catalog_revision_seq 序列（0015）"
    seg_a2b = psql(TEST_DB, f"select count(*) from script_segment where script_project_id={pid}")
    assert seg_a2b == seg_before, "0015 升级后业务数据丢失"
    print("  0015 readiness/onboarding/confusion/revision tables + sequence present; data intact")
    print("GOVERNANCE_DB_UPGRADE_OK")

    # 4h. 0016 最终成片/使用血缘四表出现；既有业务数据不丢
    for tbl in ("final_video", "final_video_usage",
                "final_video_usage_occurrence", "final_video_usage_event"):
        assert psql(TEST_DB, f"select to_regclass('public.{tbl}')") == tbl, f"应有 {tbl} 表（0016）"
    seg_prb = psql(TEST_DB, f"select count(*) from script_segment where script_project_id={pid}")
    assert seg_prb == seg_before, "0016 升级后业务数据丢失"
    print("  0016 final_video/usage/occurrence/event tables present; data intact")
    print("LINEAGE_DB_UPGRADE_OK")

    # 4i. 0017 稳定身份：asset_location/fingerprint_job 表 + 兼容回填（每 Asset 一条
    # primary 位置）+ shot.retired_at / scan_run.reconciliation 列；既有业务数据不丢
    for tbl in ("asset_location", "fingerprint_job"):
        assert psql(TEST_DB, f"select to_regclass('public.{tbl}')") == tbl, f"应有 {tbl} 表（0017）"
    asset_cnt = psql(TEST_DB, "select count(*) from asset")
    loc_cnt = psql(TEST_DB, "select count(*) from asset_location where is_primary")
    assert asset_cnt == loc_cnt, f"0017 兼容回填不一致: asset={asset_cnt} primary_loc={loc_cnt}"
    for col, tbl in (("retired_at", "shot"), ("reconciliation", "scan_run")):
        has = psql(
            TEST_DB,
            "select count(*) from information_schema.columns "
            f"where table_name='{tbl}' and column_name='{col}'",
        )
        assert has == "1", f"{tbl} 应有 {col} 列（0017）"
    seg_prc = psql(TEST_DB, f"select count(*) from script_segment where script_project_id={pid}")
    assert seg_prc == seg_before, "0017 升级后业务数据丢失"
    print("  0017 asset_location/fingerprint_job present; per-asset primary backfilled; data intact")
    print("IDENTITY_DB_UPGRADE_OK")

    # 4j. 0018 历史使用证据四表出现；不预置任何规则/证据行；既有业务数据不丢
    for tbl in ("legacy_usage_rule", "legacy_usage_import_run",
                "legacy_usage_evidence", "legacy_usage_evidence_event"):
        assert psql(TEST_DB, f"select to_regclass('public.{tbl}')") == tbl, f"应有 {tbl} 表（0018）"
    rule_rows = psql(TEST_DB, "select count(*) from legacy_usage_rule")
    assert rule_rows == "0", "0018 升级不得写死任何规则行（真实规则须经 API 创建）"
    seg_prcb = psql(TEST_DB, f"select count(*) from script_segment where script_project_id={pid}")
    assert seg_prcb == seg_before, "0018 升级后业务数据丢失"
    print("  0018 legacy evidence tables present; zero seeded rules; data intact")

    # 4k. 0019 产品素材关系：新表存在且零预置行；asset.media_kind 回填 video；业务数据不丢
    assert psql(TEST_DB, "select to_regclass('public.product_media_link')") == "product_media_link",         "应有 product_media_link 表（0019）"
    link_rows = psql(TEST_DB, "select count(*) from product_media_link")
    assert link_rows == "0", "0019 升级不得预置任何产品素材关系（人工事实须经 API 创建）"
    kinds = psql(TEST_DB, "select count(*) from asset where media_kind is distinct from 'video'")
    assert kinds == "0", "0019 升级须把既有 asset 全部回填 media_kind=video"
    seg_pm = psql(TEST_DB, "select count(*) from script_segment")
    assert seg_pm == seg_before, "0019 升级后业务数据丢失"
    print("  0019 product_media_link present; media_kind backfilled; data intact")

    # 4l. 0020 操作审计表出现且零预置事件行；业务数据不丢
    assert psql(TEST_DB, "select to_regclass('public.product_media_operation')") == "product_media_operation",         "应有 product_media_operation 表（0020）"
    op_rows = psql(TEST_DB, "select count(*) from product_media_operation")
    assert op_rows == "0", "0020 升级不得预置任何操作事件"
    seg_ops = psql(TEST_DB, "select count(*) from script_segment")
    assert seg_ops == seg_before, "0020 升级后业务数据丢失"
    print("  0020 product_media_operation present; zero seeded events; data intact")

    # 4m. 0021 素材级搜索两表出现且零预置行；业务数据不丢
    assert psql(TEST_DB, "select to_regclass('public.asset_image_analysis')") == "asset_image_analysis", \
        "应有 asset_image_analysis 表（0021）"
    assert psql(TEST_DB, "select to_regclass('public.asset_search_document')") == "asset_search_document", \
        "应有 asset_search_document 表（0021）"
    aia_rows = psql(TEST_DB, "select count(*) from asset_image_analysis")
    asd_rows = psql(TEST_DB, "select count(*) from asset_search_document")
    assert aia_rows == "0" and asd_rows == "0", "0021 升级不得预置任何分析/文档行"
    seg_p2a = psql(TEST_DB, "select count(*) from script_segment")
    assert seg_p2a == seg_before, "0021 升级后业务数据丢失"
    print("  0021 asset_image_analysis/asset_search_document present; zero seeded; data intact")

    # 4n. 0022 视觉两表出现且零预置行
    assert psql(TEST_DB, "select to_regclass('public.visual_media_embedding')") == "visual_media_embedding",         "应有 visual_media_embedding 表（0022）"
    assert psql(TEST_DB, "select to_regclass('public.visual_product_candidate')") == "visual_product_candidate",         "应有 visual_product_candidate 表（0022）"
    vme_rows = psql(TEST_DB, "select count(*) from visual_media_embedding")
    vpc_rows = psql(TEST_DB, "select count(*) from visual_product_candidate")
    assert vme_rows == "0" and vpc_rows == "0", "0022 升级不得预置任何嵌入/候选行"
    print("  0022 visual_media_embedding/visual_product_candidate present; zero seeded")
    print("LEGACY_DB_UPGRADE_OK")

    # 5. 再次升级幂等（仍 head 0018，无错误，数据不变）
    up2 = db_upgrade_script(ASYNC_URL)
    assert up2.returncode == 0, f"幂等升级失败: {up2.stderr}"
    rev3 = psql(TEST_DB, "select version_num from alembic_version")
    seg_final = psql(TEST_DB, f"select count(*) from script_segment where script_project_id={pid}")
    assert rev3 == "0022_visual_auto" and seg_final == seg_before, "幂等升级破坏状态"
    print(f"  idempotent re-run: still {rev3}, data intact (segments={seg_final})")
    print("SCRIPT_DB_UPGRADE_IDEMPOTENT_OK")

    # 6. 清理测试库（绝不碰真实业务库）
    psql("postgres", f"DROP DATABASE IF EXISTS {TEST_DB}")


if __name__ == "__main__":
    main()
