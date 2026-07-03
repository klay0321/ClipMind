#!/usr/bin/env python3
"""PR-C 端到端（稳定素材身份；纯 API + 中性合成数据 + 容器内文件操作）。

覆盖 §十三 中性验收：
上传合成视频 → 扫描索引 → quick/full 指纹 → 分析 gen1 → confirmed Usage →
容器内移动文件 → 再扫描 → Asset ID 不变 + 位置历史 + Usage 不变 →
重新分析 gen2 → gen1 保留（retired）→ 默认查询只回 gen2 → lineage 仍引用 gen1 →
复制同文件 → 第二位置不重复分析 → quick-only 相同仅候选不自动合并 →
（--mode check-persist）重启后身份/位置/代次/Usage 全在。

只在"上传素材"根（/app/uploads 可写卷）内移动/复制**合成文件**，
绝不触碰任何真实素材。前缀 ``PRC-E2E``；--mode cleanup 仅清理本前缀。

用法：
    API_BASE=http://localhost:8000 python scripts/ci_pr_c_identity_e2e.py --mode full
    API_BASE=http://localhost:8000 python scripts/ci_pr_c_identity_e2e.py --mode check-persist
    API_BASE=http://localhost:8000 python scripts/ci_pr_c_identity_e2e.py --mode cleanup
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid

API = os.environ.get("API_BASE", "http://localhost:8000")
PREFIX = "PRC-E2E"
_PSQL = [
    "docker", "compose", "exec", "-T", "postgres",
    "psql", "-U", "clipmind", "-d", "clipmind", "-tAc",
]
_API_EXEC = ["docker", "compose", "exec", "-T", "api"]


def _req(method: str, path: str, body=None, *, raw: bytes | None = None,
         content_type: str = "application/json"):
    url = f"{API}{path}"
    data = raw if raw is not None else (json.dumps(body).encode() if body is not None else None)
    req = urllib.request.Request(
        url, data=data, method=method, headers={"Content-Type": content_type}
    )
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:  # noqa: S310
            payload = resp.read()
            return resp.status, json.loads(payload) if payload else {}
    except urllib.error.HTTPError as e:
        return e.code, {"_error": e.read().decode("utf-8", "replace")[:400]}


def jreq(method: str, path: str, body=None, expect=(200, 201, 202), **kw):
    status, data = _req(method, path, body, **kw)
    if status not in expect:
        print(f"E2E FAIL: {method} {path} -> {status}: {data}", file=sys.stderr)
        sys.exit(1)
    return data


def check(cond: bool, msg: str):
    if not cond:
        print(f"E2E FAIL: {msg}", file=sys.stderr)
        sys.exit(1)


def poll(fn, ok, *, timeout=300, interval=3, desc=""):
    deadline = time.time() + timeout
    last = None
    while time.time() < deadline:
        last = fn()
        if ok(last):
            return last
        time.sleep(interval)
    print(f"E2E FAIL: 轮询超时（{desc}），最后：{last}", file=sys.stderr)
    sys.exit(1)


def psql(sql: str) -> str:
    out = subprocess.run(_PSQL + [sql], capture_output=True, text=True, check=False)
    if out.returncode != 0:
        print(f"E2E FAIL: psql: {out.stderr[:300]}", file=sys.stderr)
        sys.exit(1)
    return out.stdout.strip()


def container_sh(cmd: str) -> None:
    """在 api 容器内执行 shell（仅操作 /app/uploads 下的合成文件）。"""
    check("/app/uploads/" in cmd, f"容器命令必须限定 /app/uploads: {cmd}")
    out = subprocess.run(
        [*_API_EXEC, "sh", "-c", cmd], capture_output=True, text=True, check=False
    )
    if out.returncode != 0:
        print(f"E2E FAIL: container sh: {out.stderr[:300]}", file=sys.stderr)
        sys.exit(1)


def make_video(path: str, colors: list[str], seg_seconds: float = 2.5) -> None:
    inputs: list[str] = []
    for c in colors:
        inputs += ["-f", "lavfi", "-i", f"color=c={c}:s=320x240:d={seg_seconds}:r=25"]
    n = len(colors)
    filt = "".join(f"[{i}:v]" for i in range(n)) + f"concat=n={n}:v=1:a=0,format=yuv420p[v]"
    out = subprocess.run(
        ["ffmpeg", "-y", *inputs, "-filter_complex", filt, "-map", "[v]",
         "-c:v", "libx264", "-preset", "ultrafast", path],
        capture_output=True, check=False,
    )
    if out.returncode != 0:
        print(f"E2E FAIL: ffmpeg: {out.stderr[-300:]!r}", file=sys.stderr)
        sys.exit(1)


def upload_video(local_path: str, filename: str) -> int:
    boundary = uuid.uuid4().hex
    with open(local_path, "rb") as f:
        content = f.read()
    body = (
        f"--{boundary}\r\nContent-Disposition: form-data; name=\"file\"; "
        f"filename=\"{filename}\"\r\nContent-Type: video/mp4\r\n\r\n"
    ).encode() + content + f"\r\n--{boundary}--\r\n".encode()
    res = jreq(
        "POST", "/api/uploads", raw=body,
        content_type=f"multipart/form-data; boundary={boundary}", expect=(202,),
    )
    return int(res["source_directory_id"])


def wait_asset(filename: str, sd_id: int | None = None, *, status="indexed") -> dict:
    deadline = time.time() + 300
    rescan_at = time.time() + 60

    def find():
        q = urllib.parse.quote(filename)
        data = jreq("GET", f"/api/assets?page=1&page_size=50&q={q}")
        for item in data.get("items", []):
            if item["filename"] == filename and item["status"] == status:
                return item
        return None

    while time.time() < deadline:
        item = find()
        if item is not None:
            return item
        if sd_id is not None and time.time() >= rescan_at:
            _req("POST", f"/api/source-directories/{sd_id}/scan")
            rescan_at = deadline
        time.sleep(3)
    print(f"E2E FAIL: 等待素材 {filename} 超时", file=sys.stderr)
    sys.exit(1)


def scan_and_wait(sd_id: int) -> dict:
    def status():
        return jreq("GET", f"/api/source-directories/{sd_id}/status")

    # 先等前序扫描结束（POST 对活动 run 幂等复用，会拿到旧 run id）
    poll(
        status,
        lambda s: (s.get("latest_run") or {}).get("status") not in ("queued", "running"),
        desc=f"等待前序扫描 root={sd_id}",
    )
    run = jreq("POST", f"/api/source-directories/{sd_id}/scan", expect=(202,))
    run_id = run["id"]
    done = poll(
        status,
        lambda s: (s.get("latest_run") or {}).get("id") == run_id
        and s["latest_run"]["status"] in ("completed", "failed"),
        desc=f"扫描 root={sd_id}",
    )
    check(done["latest_run"]["status"] == "completed", f"扫描失败: {done['latest_run']}")
    return done


def run_fingerprint(asset_id: int, kind: str) -> None:
    job = jreq("POST", f"/api/assets/{asset_id}/fingerprint", {"kind": kind}, expect=(202,))

    def get():
        return jreq("GET", f"/api/assets/fingerprint-jobs/{job['id']}")

    done = poll(get, lambda j: j["status"] in ("completed", "partial", "failed"),
                desc=f"指纹 {kind} asset={asset_id}")
    check(done["status"] == "completed", f"指纹任务失败: {done}")


def analyze_and_wait(asset_id: int) -> list[dict]:
    jreq("POST", f"/api/assets/{asset_id}/analyze-shots", expect=(202,))
    poll(
        lambda: jreq("GET", f"/api/assets/{asset_id}/shot-analysis"),
        lambda s: s.get("status") == "completed",
        desc=f"拆镜头 asset={asset_id}",
    )
    return jreq("GET", f"/api/assets/{asset_id}/shots?page=1&page_size=50")["items"]


def run_full() -> None:
    tag = uuid.uuid4().hex[:6]
    tmp = tempfile.mkdtemp(prefix="prc_e2e_")
    src_name = f"{PREFIX}-src-{tag}.mp4"
    fin_name = f"{PREFIX}-final-{tag}.mp4"

    # 1) 上传合成源视频 + 成片视频 → 索引
    make_video(os.path.join(tmp, "s.mp4"), ["red", "blue"])
    make_video(os.path.join(tmp, "f.mp4"), ["green"])
    sd_id = upload_video(os.path.join(tmp, "s.mp4"), src_name)
    src = wait_asset(src_name, sd_id)
    upload_video(os.path.join(tmp, "f.mp4"), fin_name)
    fin = wait_asset(fin_name, sd_id)
    src_id = src["id"]

    # 2) quick + full 指纹
    run_fingerprint(src_id, "quick")
    run_fingerprint(src_id, "full")
    ident = jreq("GET", f"/api/assets/{src_id}/identity")
    check(ident["full_hash_available"] and ident["fingerprint_state"] == "full_ready",
          f"指纹状态异常: {ident['fingerprint_state']}")
    check(ident["quick_fingerprint_short"] is not None, "quick 指纹缺失")
    print("PR_C_FULL_HASH_AUTHORITY_OK")

    # 3) 分析 gen1 + confirmed Usage
    shots1 = analyze_and_wait(src_id)
    check(len(shots1) >= 2, f"gen1 镜头不足: {len(shots1)}")
    check(all(s["generation"] == 1 and not s["retired"] for s in shots1), "gen1 状态异常")
    shot1 = shots1[0]
    fv = jreq("POST", "/api/final-videos",
              {"asset_id": fin["id"], "title": f"{PREFIX}-成片-{tag}"}, expect=(201,))
    usage = jreq("POST", f"/api/final-videos/{fv['id']}/usages",
                 {"source_shot_id": shot1["id"]}, expect=(201,))
    jreq("POST", f"/api/final-video-usages/{usage['id']}/confirm", {})
    s = jreq("GET", f"/api/shots/{shot1['id']}/usage-summary")
    check(s["confirmed_usage_count"] == 1, "确认计数异常")

    # 4) 容器内移动文件（模拟"挪进已使用目录"的运营动作；仅合成文件）
    moved_rel = f"moved-{tag}/{src_name}"
    container_sh(f"mkdir -p /app/uploads/moved-{tag} && "
                 f"mv \"/app/uploads/{src_name}\" \"/app/uploads/{moved_rel}\"")
    scan_and_wait(sd_id)

    # Asset ID 不变；位置历史正确；Usage 不变
    moved = jreq("GET", f"/api/assets/{src_id}")
    check(moved["relative_path"].endswith(src_name) and f"moved-{tag}" in moved["relative_path"],
          f"投影未切到新位置: {moved['relative_path']}")
    assets_same = jreq("GET", f"/api/assets?page=1&page_size=50&q={urllib.parse.quote(src_name)}")
    live = [a for a in assets_same["items"] if a["filename"] == src_name]
    check(len(live) == 1 and live[0]["id"] == src_id, "移动后出现重复 Asset")
    print("PR_C_STABLE_ASSET_ID_OK")

    locs = jreq("GET", f"/api/assets/{src_id}/locations")
    stats = {loc["location_status"] for loc in locs}
    check(len(locs) == 2 and "historical" in stats and "present" in stats,
          f"位置历史异常: {[(x['location_status'], x['is_primary']) for x in locs]}")
    primary = [loc for loc in locs if loc["is_primary"]]
    check(len(primary) == 1 and primary[0]["location_status"] == "present", "primary 异常")
    s = jreq("GET", f"/api/shots/{shot1['id']}/usage-summary")
    check(s["confirmed_usage_count"] == 1, "移动后使用次数变化")
    print("PR_C_MOVE_RELINK_OK")

    # 5) 重新分析 gen2（有血缘也允许）：gen1 保留、默认只回 gen2、lineage 引用 gen1
    shots2 = analyze_and_wait(src_id)
    check(all(s["generation"] == 2 for s in shots2), "gen2 未生效")
    gens = jreq("GET", f"/api/assets/{src_id}/analysis-generations")
    check(gens["current_generation"] == 2 and len(gens["items"]) == 2, f"代次异常: {gens}")
    hist = jreq("GET", f"/api/assets/{src_id}/shots?generation=1")["items"]
    check({h["id"] for h in hist} == {s["id"] for s in shots1}, "gen1 镜头丢失")
    check(all(h["retired"] for h in hist), "gen1 应标记 retired")
    print("PR_C_HISTORICAL_SHOT_PRESERVED_OK")

    default = jreq("GET", f"/api/assets/{src_id}/shots?page=1&page_size=50")["items"]
    check({d["id"] for d in default} == {s["id"] for s in shots2}, "默认查询混入历史代次")
    all_shots = jreq("GET", "/api/shots?page=1&page_size=100")["items"]
    check(not ({s["id"] for s in shots1} & {a["id"] for a in all_shots}),
          "全局列表混入 retired")
    print("PR_C_CURRENT_GENERATION_FILTER_OK")

    s = jreq("GET", f"/api/shots/{shot1['id']}/usage-summary")
    check(s["confirmed_usage_count"] == 1, "重新分析后使用次数变化")
    lineage = jreq("GET", f"/api/final-videos/{fv['id']}/lineage")
    u = lineage["usages"][0]
    check(u["source_shot_id"] == shot1["id"] and u["shot"]["retired"] is True,
          "lineage 未保留历史代次引用")
    print("PR_C_REANALYSIS_WITH_LINEAGE_OK")

    # 6) 复制同文件 → 第二位置（不重复分析、不重复建 Asset）
    copy_rel = f"copy-{tag}/{src_name}"
    container_sh(f"mkdir -p /app/uploads/copy-{tag} && "
                 f"cp \"/app/uploads/{moved_rel}\" \"/app/uploads/{copy_rel}\"")
    scan_and_wait(sd_id)
    locs = jreq("GET", f"/api/assets/{src_id}/locations")
    present = [loc for loc in locs if loc["location_status"] == "present"]
    check(len(present) == 2, f"复制未识别为多位置: {[x['location_status'] for x in locs]}")
    check(sum(1 for loc in locs if loc["is_primary"]) == 1, "primary 不唯一")
    gens = jreq("GET", f"/api/assets/{src_id}/analysis-generations")
    check(gens["current_generation"] == 2, "复制触发了重复分析")
    print("PR_C_MULTIPLE_LOCATIONS_OK")

    # 7) quick-only 相同 → 仅候选不自动合并：上传同字节成片副本（fin 无 full_hash）
    fin2_name = f"{PREFIX}-final-copy-{tag}.mp4"
    upload_video(os.path.join(tmp, "f.mp4"), fin2_name)
    fin2 = wait_asset(fin2_name, sd_id)
    check(fin2["id"] != fin["id"], "quick 相同被误自动合并")
    recon = psql(
        "SELECT reconciliation->'counts'->>'ambiguous_candidates' FROM scan_run "
        "WHERE reconciliation IS NOT NULL ORDER BY id DESC LIMIT 1"
    )
    check(recon not in ("", "0", None), f"ambiguous 未记录: {recon!r}")
    print("PR_C_QUICK_HASH_NOT_AUTHORITATIVE_OK")

    # 8) 旧业务兼容
    for path in ("/api/products?limit=1", "/api/product-catalog/tree",
                 "/api/final-videos?page=1&page_size=1", "/health/ready"):
        jreq("GET", path)
    print("PR_C_BACKWARD_COMPAT_OK")

    state = {
        "tag": tag, "src_id": src_id, "fv_id": fv["id"], "usage_id": usage["id"],
        "shot1_id": shot1["id"], "expected_locations": len(locs) + 0,
        "expected_current_gen": 2,
    }
    with open(".prc_e2e_state.json", "w", encoding="utf-8") as f:
        json.dump(state, f)
    print("PR_C_API_E2E_OK")


def run_check_persist() -> None:
    with open(".prc_e2e_state.json", encoding="utf-8") as f:
        st = json.load(f)
    ident = jreq("GET", f"/api/assets/{st['src_id']}/identity")
    check(ident["full_hash_available"], "重启后 full_hash 丢失")
    check(ident["current_generation"] == st["expected_current_gen"], "重启后代次变化")
    check(ident["historical_generation_count"] >= 1, "重启后历史代次丢失")
    locs = jreq("GET", f"/api/assets/{st['src_id']}/locations")
    check(len(locs) >= 3, f"重启后位置历史丢失: {len(locs)}")
    s = jreq("GET", f"/api/shots/{st['shot1_id']}/usage-summary")
    check(s["confirmed_usage_count"] == 1, "重启后使用次数变化")
    hist = jreq("GET", f"/api/assets/{st['src_id']}/shots?generation=1")["items"]
    check(len(hist) >= 1 and all(h["retired"] for h in hist), "重启后历史 Shot 丢失")
    print("PR_C_RESTART_PERSIST_OK")
    print("PR_C_PERSIST_OK")


def run_cleanup() -> None:
    psql(f"DELETE FROM final_video WHERE title LIKE '{PREFIX}%'")
    psql(
        "DELETE FROM final_video_usage WHERE source_asset_id IN "
        f"(SELECT id FROM asset WHERE filename LIKE '{PREFIX}%')"
    )
    psql(
        "DELETE FROM final_video WHERE asset_id IN "
        f"(SELECT id FROM asset WHERE filename LIKE '{PREFIX}%')"
    )
    psql(f"DELETE FROM asset WHERE filename LIKE '{PREFIX}%'")
    subprocess.run(
        [*_API_EXEC, "sh", "-c",
         f"rm -rf /app/uploads/{PREFIX}* /app/uploads/moved-* /app/uploads/copy-* 2>/dev/null; true"],
        capture_output=True, check=False,
    )
    print("PR_C_CLEANUP_OK")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=["full", "check-persist", "cleanup"], default="full")
    args = parser.parse_args()
    if args.mode == "full":
        run_full()
    elif args.mode == "check-persist":
        run_check_persist()
    else:
        run_cleanup()


if __name__ == "__main__":
    main()
