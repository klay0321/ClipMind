#!/usr/bin/env python3
"""PR-06B 导出中心 / 多格式 / Bundle / 保存搜索 / 收藏 / 动态集合 端到端（docker-e2e 用）。

前置：同一 compose 栈已由 ci_pr02/ai/search E2E 播种了可检索 READY 镜头（合成视频，Fake provider）。
验证真实 API + DB + export-worker + media-worker，不使用真实 MiMo/E5/视频：
- 多格式脚本导出 csv/xlsx/json/markdown/printable，下载校验内容（XLSX=PK、JSON 可解析、MD 表头、HTML 自包含）。
- 多镜头 Bundle ZIP：打包→下载→校验 zip 含 clips/ + manifest.json + edit-list。
- 导出中心聚合 clip/script/bundle；删除安全（删 completed 记录 + 文件，源镜头仍在）；retry 仅 failed。
- 保存搜索保存/重跑（去分页）；收藏四类去重；动态集合实时 re-run。
- check-persist：重启后导出中心/保存搜索/收藏/动态集合仍在。

仅打印计数/状态标志，不输出脚本全文/密钥/Endpoint。
用法：python scripts/ci_pr06b_e2e.py --mode full | --mode check-persist
"""

from __future__ import annotations

import argparse
import io
import json
import os
import subprocess
import time
import urllib.error
import urllib.request
import zipfile

API = os.environ.get("API_BASE", "http://localhost:8000")
_PSQL = ["docker", "compose", "exec", "-T", "postgres", "psql", "-U", "clipmind",
         "-d", "clipmind", "-tAc"]

SCRIPT_NAME = "pr06b-e2e-script"
SAVED_NAME = "pr06b-e2e-saved"
DYN_NAME = "pr06b-e2e-dynamic"
PROJECT_NAME = "pr06b-e2e-project"
SCRIPT = (
    "开场画面：展示产品整体外观，时长不超过3秒。\n\n"
    "使用演示：手持操作，画面清晰。\n\n"
    "卖点强调：突出便携与轻巧。\n\n"
    "结尾引导：点击下方了解更多。"
)
FORMATS = ("csv", "xlsx", "json", "markdown", "printable")


def q(sql: str) -> str:
    out = subprocess.run([*_PSQL, sql], capture_output=True, text=True, timeout=30, check=False)
    return out.stdout.strip() if out.returncode == 0 else ""


def jreq(method: str, path: str, body=None, expect=(200, 201, 202, 204)):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(
        f"{API}{path}", data=data, method=method, headers={"Content-Type": "application/json"}
    )
    try:
        with urllib.request.urlopen(req, timeout=120) as r:  # noqa: S310
            code, raw = r.status, r.read()
    except urllib.error.HTTPError as e:
        code, raw = e.code, e.read()
    if code not in expect:
        raise SystemExit(f"{method} {path} -> {code}: {raw[:300]!r}")
    return (json.loads(raw) if raw and code != 204 else {}), code


def download(path: str) -> bytes:
    with urllib.request.urlopen(f"{API}{path}", timeout=120) as r:  # noqa: S310
        return r.read()


def ready_shot_ids(n: int) -> list[int]:
    out = q(f"select id from shot where status='ready' order by id limit {n}")
    return [int(x) for x in out.split() if x.strip()]


def poll(kind: str, eid: int, deadline_s: int = 120) -> dict:
    deadline = time.time() + deadline_s
    while time.time() < deadline:
        item, _ = jreq("GET", f"/api/export-center/{kind}/{eid}")
        if item["status"] in ("completed", "failed"):
            return item
        time.sleep(2)
    raise SystemExit(f"export {kind}/{eid} 未在超时内完成")


def find_id(path: str, name: str) -> int | None:
    page, _ = jreq("GET", path)
    for it in page.get("items", []):
        if it.get("name") == name:
            return it["id"]
    return None


def setup_script() -> int:
    sid = find_id("/api/scripts?page=1&page_size=100", SCRIPT_NAME)
    if sid is None:
        p, _ = jreq("POST", "/api/scripts", {"name": SCRIPT_NAME, "raw_script": SCRIPT})
        sid = p["id"]
    detail, _ = jreq("POST", f"/api/scripts/{sid}/parse?force=true", {"parser": "fake"})
    assert detail["parse_status"] == "ok" and len(detail["segments"]) >= 2
    return sid


def run_multi_format(sid: int) -> None:
    for fmt in FORMATS:
        exp, _ = jreq("POST", f"/api/scripts/{sid}/exports?format={fmt}")
        eid = exp["id"]
        item = poll("script", eid)
        assert item["status"] == "completed", f"{fmt} 导出失败: {item.get('error_message')}"
        data = download(f"/api/scripts/{sid}/exports/{eid}/download")
        if fmt == "csv":
            assert data[:3] == b"\xef\xbb\xbf"
        elif fmt == "xlsx":
            assert data[:2] == b"PK"
            zipfile.ZipFile(io.BytesIO(data))  # 可解压即合法
        elif fmt == "json":
            obj = json.loads(data)
            assert "segments" in obj and "metadata" in obj
        elif fmt == "markdown":
            assert "段落序号".encode() in data
        elif fmt == "printable":
            text = data.decode("utf-8")
            assert text.startswith("<!DOCTYPE html>") and "http://" not in text
    print("MULTI_FORMAT_EXPORT_E2E_OK")


def run_bundle(shot_ids: list[int]) -> int:
    acc, _ = jreq("POST", "/api/exports/bundle", {"shot_ids": shot_ids, "mode": "reencode"})
    bid = acc["export_id"]
    item = poll("bundle", bid)
    assert item["status"] == "completed", f"bundle 失败: {item.get('error_message')}"
    data = download(f"/api/exports/bundle/{bid}/download")
    names = zipfile.ZipFile(io.BytesIO(data)).namelist()
    assert "manifest.json" in names and any(n.startswith("clips/") for n in names)
    assert any(n in ("edit-list.csv", "edit-list.json") for n in names)
    print("BUNDLE_EXPORT_E2E_OK")
    return bid


def run_clip(shot_id: int) -> int:
    acc, _ = jreq("POST", f"/api/shots/{shot_id}/export", {"mode": "reencode"})
    eid = acc["export_id"]
    item = poll("clip", eid)
    assert item["status"] == "completed", f"clip 失败: {item.get('error_message')}"
    return eid


def run_export_center_and_delete_safety(clip_id: int) -> None:
    page, _ = jreq("GET", "/api/export-center?page=1&page_size=100")
    kinds = {it["kind"] for it in page["items"]}
    assert {"clip", "script", "bundle"} <= kinds, f"导出中心缺类型: {kinds}"
    print("EXPORT_CENTER_E2E_OK")

    # retry 仅 failed：completed clip retry → 409
    _, code = jreq("POST", f"/api/export-center/clip/{clip_id}/retry", expect=(409,))
    assert code == 409
    # 删除 completed clip → 204；记录消失；源镜头仍在
    shot_before = q("select count(*) from shot where status='ready'")
    _, code = jreq("DELETE", f"/api/export-center/clip/{clip_id}", expect=(204,))
    assert code == 204
    _, code = jreq("GET", f"/api/export-center/clip/{clip_id}", expect=(404,))
    assert code == 404
    shot_after = q("select count(*) from shot where status='ready'")
    assert shot_before == shot_after, "删除导出误伤镜头"
    print("EXPORT_DELETE_SAFETY_E2E_OK")


def run_saved_search() -> None:
    sid = find_id("/api/saved-searches?page=1&page_size=100", SAVED_NAME)
    if sid is None:
        obj, _ = jreq("POST", "/api/saved-searches", {
            "name": SAVED_NAME, "search_kind": "shot_search",
            "query": {"query": "产品 演示", "page": 3, "page_size": 50}})
        sid = obj["id"]
        assert "page" not in obj["query"], "保存搜索应去掉分页"
    res, _ = jreq("POST", f"/api/saved-searches/{sid}/run?page=1&page_size=10")
    assert "items" in res
    print("SAVED_SEARCH_E2E_OK")


def run_favorite(shot_id: int) -> None:
    f1, _ = jreq("POST", "/api/favorites", {"target_type": "shot", "shot_id": shot_id})
    fid = f1["id"]
    f2, _ = jreq("POST", "/api/favorites", {"target_type": "shot", "shot_id": shot_id})
    assert f2["id"] == fid, "重复收藏应幂等"
    jreq("POST", "/api/favorites", {
        "target_type": "search_result", "shot_id": shot_id, "context": {"score": 0.9}})
    page, _ = jreq("GET", "/api/favorites?target_type=shot&page=1&page_size=50")
    assert any(it["id"] == fid for it in page["items"])
    _, code = jreq("DELETE", f"/api/favorites/{fid}", expect=(204,))
    assert code == 204
    assert q(f"select count(*) from shot where id={shot_id}") == "1", "删收藏误伤镜头"
    print("FAVORITE_E2E_OK")


def run_dynamic_collection() -> None:
    pid = find_id("/api/projects?page=1&page_size=100", PROJECT_NAME)
    if pid is None:
        p, _ = jreq("POST", "/api/projects", {"name": PROJECT_NAME})
        pid = p["id"]
    did = find_id(f"/api/projects/{pid}/dynamic-collections?page=1&page_size=100", DYN_NAME)
    if did is None:
        obj, _ = jreq("POST", f"/api/projects/{pid}/dynamic-collections", {
            "name": DYN_NAME, "search_kind": "shot_search",
            "query": {"query": "产品", "page": 2}})
        did = obj["id"]
        assert "page" not in obj["query"]
    res, _ = jreq("GET", f"/api/dynamic-collections/{did}/shots?page=1&page_size=10")
    assert "items" in res
    print("DYNAMIC_COLLECTION_E2E_OK")


def run_full() -> None:
    shots = ready_shot_ids(3)
    assert len(shots) >= 1, "需要至少 1 个 READY 镜头（应由前序 E2E 播种）"
    sid = setup_script()
    run_multi_format(sid)
    run_bundle(shots[:min(2, len(shots))])
    clip_id = run_clip(shots[0])
    run_saved_search()
    run_favorite(shots[0])
    run_dynamic_collection()
    run_export_center_and_delete_safety(clip_id)
    print("PR06B_E2E_OK")


def run_check_persist() -> None:
    # 重启后聚合与库对象仍在
    page, _ = jreq("GET", "/api/export-center?page=1&page_size=100")
    assert page["total"] >= 1, "重启后导出中心为空"
    assert find_id("/api/saved-searches?page=1&page_size=100", SAVED_NAME) is not None
    pid = find_id("/api/projects?page=1&page_size=100", PROJECT_NAME)
    assert pid is not None
    assert find_id(f"/api/projects/{pid}/dynamic-collections?page=1&page_size=100", DYN_NAME) is not None
    assert int(q("select count(*) from favorite") or "0") >= 1
    print("PR06B_PERSIST_OK")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", choices=["full", "check-persist"], default="full")
    args = ap.parse_args()
    if args.mode == "full":
        run_full()
    else:
        run_check_persist()
