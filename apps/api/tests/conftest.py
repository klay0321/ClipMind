from __future__ import annotations

import os

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

TEST_DATABASE_URL = os.getenv("TEST_DATABASE_URL")


@pytest_asyncio.fixture
async def engine():
    if not TEST_DATABASE_URL:
        pytest.skip("需要 TEST_DATABASE_URL")
    eng = create_async_engine(TEST_DATABASE_URL, future=True)
    try:
        yield eng
    finally:
        await eng.dispose()


@pytest_asyncio.fixture
async def session(engine):
    Session = async_sessionmaker(engine, expire_on_commit=False)
    async with Session() as s:
        yield s


@pytest_asyncio.fixture
async def client(engine, monkeypatch):
    Session = async_sessionmaker(engine, expire_on_commit=False)
    from app.db import get_db
    from app.main import app

    async def override_get_db():
        async with Session() as s:
            yield s

    app.dependency_overrides[get_db] = override_get_db
    # 不真正入队，返回确定性的 task id
    monkeypatch.setattr("app.services.scan_dispatch.enqueue_scan", lambda rid: f"task-{rid}")
    monkeypatch.setattr(
        "app.services.scan_dispatch.enqueue_rescan_asset", lambda aid: f"rtask-{aid}"
    )
    monkeypatch.setattr(
        "app.services.scan_dispatch.enqueue_generate_poster", lambda aid: f"ptask-{aid}"
    )
    monkeypatch.setattr(
        "app.services.shot_dispatch.enqueue_analyze_shots", lambda rid: f"mtask-{rid}"
    )
    monkeypatch.setattr(
        "app.services.shot_dispatch.enqueue_export_clip", lambda eid: f"etask-{eid}"
    )

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac

    app.dependency_overrides.clear()
