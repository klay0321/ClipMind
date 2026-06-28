async def test_live_always_ok(client):
    r = await client.get("/health/live")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


async def test_migration_check_ok_at_head(engine):
    """迁移就绪检查：测试库已标记到 head → ok。"""
    from app.services.migration_check import check_migration, expected_head

    state = await check_migration(engine)
    assert state.ok is True, state.detail
    assert state.head == expected_head()
    assert state.current == state.head


async def test_migration_check_detects_behind(engine, session):
    """DB revision 落后 head → ok=False，明确 detail（部署门禁可据此识别需升级）。"""
    from sqlalchemy import text

    from app.services.migration_check import check_migration, expected_head

    head = expected_head()
    await session.execute(text("UPDATE alembic_version SET version_num='0001_initial'"))
    await session.commit()
    try:
        state = await check_migration(engine)
        assert state.ok is False
        assert state.current == "0001_initial"
        assert state.head == head
        assert "落后" in state.detail
    finally:
        await session.execute(
            text("UPDATE alembic_version SET version_num=:v"), {"v": head}
        )
        await session.commit()
