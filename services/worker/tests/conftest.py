from __future__ import annotations

import os

import pytest

TEST_DATABASE_URL = os.getenv("TEST_DATABASE_URL")


@pytest.fixture
def session():
    """同步会话，连接到测试数据库（schema 由根 conftest 建表）。"""
    if not TEST_DATABASE_URL:
        pytest.skip("需要 TEST_DATABASE_URL")
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    sync_url = TEST_DATABASE_URL.replace("+asyncpg", "+psycopg")
    engine = create_engine(sync_url, future=True)
    Session = sessionmaker(bind=engine, expire_on_commit=False)
    s = Session()
    try:
        yield s
    finally:
        s.close()
        engine.dispose()
