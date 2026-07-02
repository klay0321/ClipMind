"""根级 pytest 夹具：统一管理测试数据库 schema。

- 未设置 TEST_DATABASE_URL 时所有 DB 夹具为空操作（纯逻辑测试仍可运行）。
- 设置后：session 级建表一次，function 级每个用例前清空数据。
TEST_DATABASE_URL 形如 postgresql+asyncpg://clipmind:clipmind@localhost:5432/clipmind_test
"""

from __future__ import annotations

import os

import pytest

TEST_DATABASE_URL = os.getenv("TEST_DATABASE_URL")


def sync_test_url() -> str | None:
    if not TEST_DATABASE_URL:
        return None
    return TEST_DATABASE_URL.replace("+asyncpg", "+psycopg")


def _alembic_head() -> str | None:
    """迁移脚本 head revision（与 app.services.migration_check.expected_head 同源，但本文件解耦）。"""
    from pathlib import Path

    from alembic.config import Config
    from alembic.script import ScriptDirectory

    api_dir = Path(__file__).resolve().parent / "apps" / "api"
    cfg = Config(str(api_dir / "alembic.ini"))
    cfg.set_main_option("script_location", str(api_dir / "migrations"))
    return ScriptDirectory.from_config(cfg).get_current_head()


@pytest.fixture(scope="session", autouse=True)
def _schema():
    if not TEST_DATABASE_URL:
        yield
        return
    from sqlalchemy import create_engine, text

    from clipmind_shared.models import Base

    engine = create_engine(sync_test_url(), future=True)
    # PR-04：检索文档表含 vector 列与 pg_trgm GIN 索引；create_all 前必须先建扩展
    # （测试库镜像须为 pgvector/pgvector:pg16）。
    with engine.begin() as conn:
        conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
        conn.execute(text("CREATE EXTENSION IF NOT EXISTS pg_trgm"))
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    # 0015：catalog_revision.revision_number 取号自独立序列（由迁移创建的 standalone 对象，
    # 不在 metadata 内）——create_all 后补建，保持「create_all ≡ 迁移到 head」的等价性。
    with engine.begin() as conn:
        conn.execute(text("CREATE SEQUENCE IF NOT EXISTS catalog_revision_seq"))
    # create_all 建出的 schema 等价于迁移到 head：标记 alembic_version=head，
    # 使迁移就绪检查（/health/ready 的 migration_ok）在测试库下为真。
    head = _alembic_head()
    with engine.begin() as conn:
        conn.execute(
            text("CREATE TABLE IF NOT EXISTS alembic_version (version_num VARCHAR(32) NOT NULL)")
        )
        conn.execute(text("DELETE FROM alembic_version"))
        if head:
            conn.execute(
                text("INSERT INTO alembic_version (version_num) VALUES (:v)"), {"v": head}
            )
    engine.dispose()
    yield


@pytest.fixture(autouse=True)
def _truncate():
    if not TEST_DATABASE_URL:
        yield
        return
    from sqlalchemy import create_engine, text

    engine = create_engine(sync_test_url(), future=True)
    with engine.begin() as conn:
        conn.execute(
            text(
                # 0015：治理/目录表显式入清单——product_confusion_pair/catalog_revision
                # 无 FK 不会被 CASCADE 级联，若不显式清空会残留旧行并撞上
                # RESTART IDENTITY 复用的 family/variant/sku id（跨测试假冲突）。
                "TRUNCATE catalog_revision, product_confusion_pair, "
                "product_onboarding_review, product_readiness_policy, "
                "product_reference_asset, product_attribute_value, "
                "product_attribute_definition, product_catalog_alias, "
                "product_sku, product_variant, product_family, product_category, "
                "download_log, bundle_export, favorite, saved_search, "
                "dynamic_collection, collection_shot, collection, "
                "project_product, project_shot, project_asset, project, "
                "script_export, script_shot_candidate, script_segment, script_project, "
                "shot_search_document, review_event, shot_review_state, shot_tag, tag, "
                "asset_product, product_image, product_alias, product, "
                "ai_call_log, ai_shot_analysis, ai_analysis_run, "
                "export, shot, media_processing_run, asset, scan_run, "
                "source_directory RESTART IDENTITY CASCADE"
            )
        )
    engine.dispose()
    yield
