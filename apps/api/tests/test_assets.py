from clipmind_shared.models import Asset, SourceDirectory
from clipmind_shared.models.enums import AssetStatus


async def test_list_empty(client):
    r = await client.get("/api/assets")
    assert r.status_code == 200
    assert r.json()["total"] == 0


async def test_get_404(client):
    r = await client.get("/api/assets/999999")
    assert r.status_code == 404


async def test_rescan_404(client):
    r = await client.post("/api/assets/999999/rescan")
    assert r.status_code == 404


async def test_list_filters_and_rescan(client, session):
    sd = SourceDirectory(
        name="t",
        mount_path="/app/source",
        include_extensions=["mp4"],
        exclude_patterns=[],
    )
    session.add(sd)
    await session.commit()
    await session.refresh(sd)

    session.add_all(
        [
            Asset(
                source_directory_id=sd.id,
                relative_path="a.mp4",
                normalized_relative_path="a.mp4",
                filename="alpha.mp4",
                extension="mp4",
                file_size=1,
                status=AssetStatus.INDEXED,
            ),
            Asset(
                source_directory_id=sd.id,
                relative_path="b.mp4",
                normalized_relative_path="b.mp4",
                filename="beta.mp4",
                extension="mp4",
                file_size=2,
                status=AssetStatus.ERROR,
                error_message="ffprobe_failed",
            ),
        ]
    )
    await session.commit()

    assert (await client.get("/api/assets")).json()["total"] == 2
    assert (await client.get("/api/assets?status=error")).json()["total"] == 1
    assert (await client.get("/api/assets?q=alpha")).json()["total"] == 1

    first_id = (await client.get("/api/assets")).json()["items"][0]["id"]
    rr = await client.post(f"/api/assets/{first_id}/rescan")
    assert rr.status_code == 202
    assert rr.json()["celery_task_id"] == f"rtask-{first_id}"
