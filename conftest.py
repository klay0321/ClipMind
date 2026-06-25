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


@pytest.fixture(scope="session", autouse=True)
def _schema():
    if not TEST_DATABASE_URL:
        yield
        return
    from sqlalchemy import create_engine

    from clipmind_shared.models import Base

    engine = create_engine(sync_test_url(), future=True)
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
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
                "TRUNCATE review_event, shot_review_state, shot_tag, tag, "
                "asset_product, product_image, product_alias, product, "
                "ai_call_log, ai_shot_analysis, ai_analysis_run, "
                "export, shot, media_processing_run, asset, scan_run, "
                "source_directory RESTART IDENTITY CASCADE"
            )
        )
    engine.dispose()
    yield
