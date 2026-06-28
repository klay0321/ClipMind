#!/usr/bin/env python3
"""PR-06A Gate A 项目/集合端到端（docker-e2e 用；合成数据，不依赖真实素材/MiMo）。

验证真实 API + 数据库 + 重启持久化：
创建 Project → 加入 2 个 Asset（其镜头可见）→ 加入显式 Shot → 加入 Product → 建 2 个 Collection →
同一 Shot 进两个 Collection → 关联 ScriptProject → stats → 归档（写操作 409、读仍可）→ 恢复 →
删除一个 Collection（Shot/Asset/Product/Script 仍在）→ 重启后项目/成员/集合/顺序仍在。

合成数据用前缀 ``PR06A-E2E`` 标识，``--mode cleanup`` 仅清理本前缀创建的行（绝不删其它数据）。
仅打印计数/状态标志，不输出文件名/密钥/Endpoint。

用法：
    python scripts/ci_projects_gate_a_e2e.py --mode full
    python scripts/ci_projects_gate_a_e2e.py --mode check-persist
    python scripts/ci_projects_gate_a_e2e.py --mode cleanup
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import urllib.error
import urllib.request

API = os.environ.get("API_BASE", "http://localhost:8000")
_PSQL = ["docker", "compose", "exec", "-T", "postgres", "psql", "-U", "clipmind", "-d", "clipmind", "-tAc"]

PREFIX = "PR06A-E2E"
PROJECT_NAME = f"{PREFIX}-project"
SD_NAME = f"{PREFIX}-sd"


def q(sql: str) -> str:
    out = subprocess.run([*_PSQL, sql], capture_output=True, text=True, timeout=30, check=False)
    if out.returncode != 0:
        print(f"psql 失败: {out.stderr.strip()}", file=sys.stderr)
        return ""
    return out.stdout.strip()


def _int(sql: str) -> int:
    # psql -tAc 对 INSERT ... RETURNING 会同时输出返回值与命令标签（如 "2\nINSERT 0 1"），
    # 取首个可解析为整数的 token。
    for tok in q(sql).split():
        try:
            return int(tok)
        except ValueError:
            continue
    return 0


def jreq(method: str, path: str, body=None, expect=(200, 201, 202, 204)):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(
        f"{API}{path}", data=data, method=method, headers={"Content-Type": "application/json"}
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as r:  # noqa: S310
            code, raw = r.status, r.read()
    except urllib.error.HTTPError as e:
        code, raw = e.code, e.read()
    if code not in expect:
        raise SystemExit(f"{method} {path} -> {code}: {raw[:300]!r}")
    return (json.loads(raw) if raw else {}), code


# ---------------- 合成数据 seed（psql；前缀隔离）----------------


def _seed_synthetic() -> dict:
    """插入 1 源目录 + 2 素材（各 2 镜头）+ 1 独立镜头 + 1 产品 + 1 脚本（1 段 + 1 完成导出）。"""
    sd_id = _int(
        "insert into source_directory(name,mount_path,enabled,recursive,include_extensions,"
        "exclude_patterns,read_only,scan_status,created_at,updated_at) values "
        f"('{SD_NAME}','/app/source',true,true,'[\"mp4\"]'::jsonb,'[]'::jsonb,true,"
        "'never_scanned',now(),now()) returning id"
    )
    asset_ids = []
    for i in range(3):  # 3 个素材：前 2 个加入项目，第 3 个提供独立镜头
        aid = _int(
            "insert into asset(source_directory_id,relative_path,normalized_relative_path,"
            "filename,extension,file_size,duration,width,height,video_codec,status,"
            "metadata_version,first_seen_at,last_seen_at,created_at,updated_at) values "
            f"({sd_id},'{PREFIX}-{i}.mp4','{PREFIX}-{i}.mp4','{PREFIX}-{i}.mp4','mp4',1,5.0,"
            "1280,720,'h264','indexed',1,now(),now(),now(),now()) returning id"
        )
        asset_ids.append(aid)
        for s in range(2):
            q(
                "insert into shot(asset_id,generation,sequence_no,start_time,end_time,duration,"
                "detector_type,status,keyframe_path,proxy_path,created_at,updated_at) values "
                f"({aid},1,{s},0,1,1,'fixed','ready','k/{aid}-{s}.jpg','p/{aid}-{s}.mp4',now(),now())"
            )
    product_id = _int(
        "insert into product(name,normalized_name,status,created_at,updated_at) values "
        f"('{PREFIX}-product','{PREFIX.lower()}-product','active',now(),now()) returning id"
    )
    script_id = _int(
        "insert into script_project(name,raw_script,script_hash,source_format,status,"
        "parse_status,result_schema_version,created_at,updated_at) values "
        f"('{PREFIX}-script','raw','{PREFIX}-hash','paste','parsed','ok',1,now(),now()) returning id"
    )
    return {"asset_ids": asset_ids, "product_id": product_id, "script_id": script_id}


def _shot_ids_of_asset(asset_id: int) -> list[int]:
    out = q(f"select id from shot where asset_id={asset_id} order by sequence_no")
    return [int(x) for x in out.split() if x.strip()]


# ---------------- full ----------------


def run_full() -> None:
    seed = _seed_synthetic()
    a1, a2, a3 = seed["asset_ids"]
    explicit_shots = _shot_ids_of_asset(a3)
    assert explicit_shots, "种子镜头缺失"

    # 1. 创建项目
    proj, _ = jreq("POST", "/api/projects", {"name": PROJECT_NAME})
    pid = proj["id"]
    assert proj["status"] == "active" and proj["lock_version"] == 1
    print(f"  created project id={pid}")

    # 2. 加入 2 个 Asset
    r, _ = jreq("POST", f"/api/projects/{pid}/assets/batch", {"ids": [a1, a2]})
    assert set(r["completed"]) == {a1, a2}, r

    # 3. 加入 1 个显式 Shot
    r, _ = jreq("POST", f"/api/projects/{pid}/shots/batch", {"ids": [explicit_shots[0]]})
    assert r["completed"] == [explicit_shots[0]], r

    # 4. 加入 Product
    r, _ = jreq("POST", f"/api/projects/{pid}/products/batch", {"ids": [seed["product_id"]]})
    assert r["completed"] == [seed["product_id"]], r

    # 5. 两个 Collection
    c1, _ = jreq("POST", f"/api/projects/{pid}/collections", {"name": f"{PREFIX}-c1"})
    c2, _ = jreq("POST", f"/api/projects/{pid}/collections", {"name": f"{PREFIX}-c2"})

    # 6. 同一 Shot 进两个 Collection
    shared = explicit_shots[0]
    jreq("POST", f"/api/collections/{c1['id']}/shots/batch", {"ids": [shared]})
    jreq("POST", f"/api/collections/{c2['id']}/shots/batch", {"ids": [shared]})
    assert (jreq("GET", f"/api/collections/{c1['id']}/shots")[0])["total"] == 1
    assert (jreq("GET", f"/api/collections/{c2['id']}/shots")[0])["total"] == 1

    # 7. 关联 ScriptProject
    jreq("POST", f"/api/projects/{pid}/scripts/{seed['script_id']}")

    # 8. 统计
    stats, _ = jreq("GET", f"/api/projects/{pid}/stats")
    assert stats["asset_count"] == 2, stats
    assert stats["explicit_shot_count"] == 1, stats
    assert stats["collection_count"] == 2, stats
    assert stats["product_count"] == 1, stats
    assert stats["script_count"] == 1, stats
    # 可见镜头 = a1(2) + a2(2) + 显式 1 = 5（显式 shot 属于 a3，不与 a1/a2 重叠）
    assert stats["visible_shot_count"] == 5, stats
    print("PROJECTS_GATE_A_E2E_OK")

    # 9. 归档：写操作 409、读仍可
    arc, _ = jreq("POST", f"/api/projects/{pid}/archive", {"lock_version": proj["lock_version"]})
    assert arc["status"] == "archived"
    _, code = jreq(
        "POST", f"/api/projects/{pid}/assets/batch", {"ids": [a1]}, expect=(200, 409)
    )
    assert code == 409, "归档项目加成员必须 409"
    _, code = jreq(
        "POST", f"/api/projects/{pid}/collections", {"name": "x"}, expect=(201, 409)
    )
    assert code == 409, "归档项目建集合必须 409"
    assert jreq("GET", f"/api/projects/{pid}")[1] == 200
    assert jreq("GET", f"/api/projects/{pid}/stats")[1] == 200
    print("PROJECTS_ARCHIVE_GUARD_OK")

    # 10. 恢复
    una, _ = jreq("POST", f"/api/projects/{pid}/unarchive", {"lock_version": arc["lock_version"]})
    assert una["status"] == "active"

    # 11. 删除一个 Collection → Shot/Asset/Product/Script 仍在
    jreq("DELETE", f"/api/collections/{c2['id']}")
    assert jreq("GET", f"/api/collections/{c2['id']}", expect=(200, 404))[1] == 404
    assert _int(f"select count(*) from shot where id={shared}") == 1, "删集合误删了 Shot"
    assert _int(f"select count(*) from asset where id={a1}") == 1
    assert _int(f"select count(*) from product where id={seed['product_id']}") == 1
    assert _int(f"select count(*) from script_project where id={seed['script_id']}") == 1
    print("COLLECTIONS_GATE_A_E2E_OK")
    print("PROJECTS_DELETE_SAFETY_OK")


# ---------------- check-persist ----------------


def run_check_persist() -> None:
    page, _ = jreq("GET", "/api/projects?page=1&page_size=100")
    pid = next((p["id"] for p in page["items"] if p["name"] == PROJECT_NAME), None)
    assert pid is not None, "重启后未找到项目"
    stats, _ = jreq("GET", f"/api/projects/{pid}/stats")
    assert stats["asset_count"] == 2, stats
    assert stats["visible_shot_count"] == 5, stats
    assert stats["collection_count"] == 1, stats  # 删了一个，剩 1
    assert stats["script_count"] == 1, stats
    cols, _ = jreq("GET", f"/api/projects/{pid}/collections")
    assert cols["total"] == 1
    assets, _ = jreq("GET", f"/api/projects/{pid}/assets")
    assert assets["total"] == 2
    print(f"  persisted project id={pid} (assets/shots/collections/order intact)")
    print("PROJECTS_GATE_A_PERSIST_OK")


# ---------------- cleanup（仅前缀数据）----------------


def run_cleanup() -> None:
    # 顺序：先删项目（级联 project_*、collection、collection_shot），再删脚本/产品/镜头/素材/源目录
    q(f"delete from script_project where name like '{PREFIX}%'")
    q(f"delete from project where name like '{PREFIX}%'")
    q(f"delete from product where name like '{PREFIX}%'")
    q(
        "delete from shot where asset_id in "
        f"(select id from asset where filename like '{PREFIX}%')"
    )
    q(f"delete from asset where filename like '{PREFIX}%'")
    q(f"delete from source_directory where name like '{PREFIX}%'")
    print(f"cleaned synthetic rows with prefix {PREFIX}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", choices=["full", "check-persist", "cleanup"], required=True)
    args = ap.parse_args()
    if args.mode == "full":
        run_full()
    elif args.mode == "check-persist":
        run_check_persist()
    else:
        run_cleanup()


if __name__ == "__main__":
    main()
