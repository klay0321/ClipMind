async def test_create_valid(client):
    r = await client.post(
        "/api/source-directories",
        json={"name": "PowerGo", "mount_path": "/app/source/powergo"},
    )
    assert r.status_code == 201
    data = r.json()
    assert data["read_only"] is True
    assert data["mount_path"] == "/app/source/powergo"
    assert data["scan_status"] == "never_scanned"
    assert "mp4" in data["include_extensions"]


async def test_create_outside_root_rejected(client):
    r = await client.post(
        "/api/source-directories", json={"name": "x", "mount_path": "/etc"}
    )
    assert r.status_code == 422


async def test_create_path_traversal_rejected(client):
    r = await client.post(
        "/api/source-directories",
        json={"name": "x", "mount_path": "/app/source/../../etc"},
    )
    assert r.status_code == 422


async def test_get_and_list_and_404(client):
    created = await client.post(
        "/api/source-directories", json={"name": "a", "mount_path": "/app/source/a"}
    )
    sid = created.json()["id"]

    listed = await client.get("/api/source-directories")
    assert any(d["id"] == sid for d in listed.json())

    got = await client.get(f"/api/source-directories/{sid}")
    assert got.status_code == 200

    missing = await client.get("/api/source-directories/999999")
    assert missing.status_code == 404


async def test_scan_dispatch_is_db_source_of_truth_and_idempotent(client):
    created = await client.post(
        "/api/source-directories", json={"name": "a", "mount_path": "/app/source/a"}
    )
    sid = created.json()["id"]

    r1 = await client.post(f"/api/source-directories/{sid}/scan")
    assert r1.status_code == 202
    run1 = r1.json()
    assert run1["status"] == "queued"
    assert run1["celery_task_id"] == f"task-{run1['id']}"

    # 已有活动 run -> 幂等返回同一个
    r2 = await client.post(f"/api/source-directories/{sid}/scan")
    assert r2.status_code == 202
    assert r2.json()["id"] == run1["id"]

    status = await client.get(f"/api/source-directories/{sid}/status")
    body = status.json()
    assert body["scan_status"] == "queued"
    assert body["latest_run"]["id"] == run1["id"]
