#!/usr/bin/env python3
"""PR-B 端到端（最终成片 / 使用血缘；纯 API + 中性合成数据，无外部依赖）。

覆盖 §十三 中性通用验收：
上传合成源视频 → 拆镜头（真实 media-worker）→ 建脚本并选择/锁定镜头 →
上传合成成片 → 创建 FinalVideo → propose-from-project（proposed 不计数）→
人工确认（=1）→ 两个 occurrence（仍=1）→ 第二成片确认同一镜头（=2）→
撤销一条（=1）→ rejected/suspected 不计数 → 并发唯一 → 归档保持计数 →
旧接口兼容 → （--mode check-persist）重启后关系与事件全在。

合成数据前缀 ``PRB-E2E``；``--mode cleanup`` 仅清理本前缀行。
仅打印计数/状态标志，不输出真实文件名/密钥/公司素材。

用法：
    API_BASE=http://localhost:8000 python scripts/ci_pr_b_lineage_e2e.py --mode full
    API_BASE=http://localhost:8000 python scripts/ci_pr_b_lineage_e2e.py --mode check-persist
    API_BASE=http://localhost:8000 python scripts/ci_pr_b_lineage_e2e.py --mode cleanup
"""

from __future__ import annotations

import argparse
import concurrent.futures
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
PREFIX = "PRB-E2E"
_PSQL = [
    "docker", "compose", "exec", "-T", "postgres",
    "psql", "-U", "clipmind", "-d", "clipmind", "-tAc",
]


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


# ---------------- 合成视频（本机 ffmpeg lavfi，两段纯色 → 场景切分点） ----------------


def make_video(path: str, colors: list[str], seg_seconds: float = 2.5) -> None:
    inputs: list[str] = []
    for c in colors:
        inputs += ["-f", "lavfi", "-i", f"color=c={c}:s=320x240:d={seg_seconds}:r=25"]
    n = len(colors)
    filt = "".join(f"[{i}:v]" for i in range(n)) + f"concat=n={n}:v=1:a=0,format=yuv420p[v]"
    cmd = [
        "ffmpeg", "-y", *inputs, "-filter_complex", filt, "-map", "[v]",
        "-c:v", "libx264", "-preset", "ultrafast", path,
    ]
    out = subprocess.run(cmd, capture_output=True, check=False)
    if out.returncode != 0:
        print(f"E2E FAIL: ffmpeg 合成失败: {out.stderr[-300:]!r}", file=sys.stderr)
        sys.exit(1)


def upload_video(local_path: str, filename: str) -> None:
    boundary = uuid.uuid4().hex
    with open(local_path, "rb") as f:
        content = f.read()
    body = (
        f"--{boundary}\r\nContent-Disposition: form-data; name=\"file\"; "
        f"filename=\"{filename}\"\r\nContent-Type: video/mp4\r\n\r\n"
    ).encode() + content + f"\r\n--{boundary}--\r\n".encode()
    jreq(
        "POST", "/api/uploads", raw=body,
        content_type=f"multipart/form-data; boundary={boundary}",
        expect=(202,),
    )


def wait_asset(filename: str) -> dict:
    def find():
        q = urllib.parse.quote(filename)
        data = jreq("GET", f"/api/assets?page=1&page_size=50&q={q}")
        for item in data.get("items", []):
            if item["filename"] == filename and item["status"] == "indexed":
                return item
        return None

    return poll(find, lambda a: a is not None, desc=f"等待素材索引 {filename}")


def analyze_and_wait_shots(asset_id: int) -> list[dict]:
    jreq("POST", f"/api/assets/{asset_id}/analyze-shots", expect=(202,))

    def analysis_status():
        return jreq("GET", f"/api/assets/{asset_id}/shot-analysis")

    poll(
        analysis_status,
        lambda s: s.get("status") == "completed",
        desc=f"等待拆镜头 asset={asset_id}",
    )
    shots = jreq("GET", f"/api/assets/{asset_id}/shots?page=1&page_size=50")
    check(len(shots["items"]) >= 1, f"asset {asset_id} 无 ready 镜头")
    return shots["items"]


def shot_summary(shot_id: int) -> dict:
    return jreq("GET", f"/api/shots/{shot_id}/usage-summary")


# ---------------- full ----------------


def run_full() -> None:
    run_tag = uuid.uuid4().hex[:6]

    # 1) 合成并上传：源素材 A（两色 → 期望多镜头）、源素材 B、成片 A、成片 B
    tmp = tempfile.mkdtemp(prefix="prb_e2e_")
    names = {
        "src_a": f"{PREFIX}-src-a-{run_tag}.mp4",
        "src_b": f"{PREFIX}-src-b-{run_tag}.mp4",
        "fin_a": f"{PREFIX}-final-a-{run_tag}.mp4",
        "fin_b": f"{PREFIX}-final-b-{run_tag}.mp4",
    }
    make_video(os.path.join(tmp, "a.mp4"), ["red", "blue"])
    make_video(os.path.join(tmp, "b.mp4"), ["green"])
    make_video(os.path.join(tmp, "fa.mp4"), ["yellow", "purple"])
    make_video(os.path.join(tmp, "fb.mp4"), ["cyan"])
    for local, key in [("a.mp4", "src_a"), ("b.mp4", "src_b"), ("fa.mp4", "fin_a"), ("fb.mp4", "fin_b")]:
        upload_video(os.path.join(tmp, local), names[key])

    src_a = wait_asset(names["src_a"])
    src_b = wait_asset(names["src_b"])
    fin_a = wait_asset(names["fin_a"])
    fin_b = wait_asset(names["fin_b"])

    shots_a = analyze_and_wait_shots(src_a["id"])
    shots_b = analyze_and_wait_shots(src_b["id"])
    all_shots = shots_a + shots_b
    check(len(all_shots) >= 2, f"合成源镜头不足 2 个（{len(all_shots)}）")
    shot1, shot2 = shots_a[0], shots_b[0]
    print(f"PR_B_SEED_OK shots_a={len(shots_a)} shots_b={len(shots_b)}")

    # 2) 项目 + 脚本 + 选择/锁定镜头（明确人工动作）
    proj = jreq("POST", "/api/projects", {"name": f"{PREFIX}-项目-{run_tag}"}, expect=(201,))
    script = jreq(
        "POST", "/api/scripts",
        {"name": f"{PREFIX}-脚本-{run_tag}", "raw_script": "1. 开场展示产品\n2. 特写按键细节"},
        expect=(201, 200),
    )
    script_id = script["id"]
    jreq("POST", f"/api/projects/{proj['id']}/scripts/{script_id}", expect=(200,))
    jreq("POST", f"/api/scripts/{script_id}/parse", expect=(200, 202))
    detail = poll(
        lambda: jreq("GET", f"/api/scripts/{script_id}"),
        lambda d: len(d.get("segments", [])) >= 2,
        desc="等待脚本拆段",
    )
    segs = detail["segments"]
    jreq(
        "POST", f"/api/scripts/{script_id}/segments/{segs[0]['id']}/lock",
        {"shot_id": shot1["id"], "lock_version": segs[0]["lock_version"], "allow_override": True},
    )
    jreq(
        "POST", f"/api/scripts/{script_id}/segments/{segs[1]['id']}/select",
        {"shot_id": shot2["id"], "lock_version": segs[1]["lock_version"], "allow_override": True},
    )

    # 3) FinalVideo A（绑定项目）
    fv1 = jreq(
        "POST", "/api/final-videos",
        {"asset_id": fin_a["id"], "title": f"{PREFIX}-成片A-{run_tag}", "project_id": proj["id"]},
        expect=(201,),
    )
    print("PR_B_FINAL_VIDEO_OK")

    # 4) propose-from-project：locked+selected 均生成 proposed；幂等
    res = jreq("POST", f"/api/final-videos/{fv1['id']}/propose-from-project", {})
    check(res["created"] == 2, f"proposal created={res['created']} != 2")
    res2 = jreq("POST", f"/api/final-videos/{fv1['id']}/propose-from-project", {})
    check(res2["created"] == 0 and res2["existing"] == 2, f"proposal 不幂等: {res2}")
    print("PR_B_PROJECT_PROPOSAL_OK")

    # proposed 不计数
    s = shot_summary(shot1["id"])
    check(s["confirmed_usage_count"] == 0 and s["proposed_count"] == 1, f"proposed 误计数: {s}")

    usages = jreq("GET", f"/api/final-videos/{fv1['id']}/usages")["items"]
    u_shot1 = next(u for u in usages if u["source_shot_id"] == shot1["id"])
    u_shot2 = next(u for u in usages if u["source_shot_id"] == shot2["id"])
    check(u_shot1["evidence_method"] == "clipmind_project", "证据来源错误")
    check(u_shot1["evidence_refs"]["segments"][0]["kind"] == "locked", "锁定来源未记录")

    # 5) 人工确认 → 计数 1
    jreq("POST", f"/api/final-video-usages/{u_shot1['id']}/confirm", {"actor_label": "e2e"})
    s = shot_summary(shot1["id"])
    check(s["confirmed_usage_count"] == 1, f"确认后计数 != 1: {s}")
    check(s["final_videos"][0]["final_video_id"] == fv1["id"], "成片引用缺失")

    # 6) 两个 occurrence → 仍只计 1 次
    sh1_start = int(shot1["start_time"] * 1000)
    occ_payload = {
        "source_start_ms": sh1_start,
        "source_end_ms": sh1_start + 800,
        "final_start_ms": 0,
        "final_end_ms": 800,
    }
    jreq("POST", f"/api/final-video-usages/{u_shot1['id']}/occurrences", occ_payload, expect=(201,))
    occ2 = dict(occ_payload, source_start_ms=sh1_start + 900, source_end_ms=sh1_start + 1600,
                final_start_ms=2000, final_end_ms=2700)
    jreq("POST", f"/api/final-video-usages/{u_shot1['id']}/occurrences", occ2, expect=(201,))
    occs = jreq("GET", f"/api/final-video-usages/{u_shot1['id']}/occurrences")["items"]
    check(len(occs) == 2, f"occurrence 数 != 2: {len(occs)}")
    s = shot_summary(shot1["id"])
    check(s["confirmed_usage_count"] == 1, f"两 occurrence 后计数 != 1: {s}")
    # 非法时间码 422
    bad = dict(occ_payload, source_end_ms=occ_payload["source_start_ms"])
    st, _ = _req("POST", f"/api/final-video-usages/{u_shot1['id']}/occurrences", bad)
    check(st == 422, f"非法时间码应 422，实际 {st}")
    print("PR_B_OCCURRENCES_OK")

    # 7) 第二成片确认同一镜头 → 计数 2；撤销 → 1
    fv2 = jreq(
        "POST", "/api/final-videos",
        {"asset_id": fin_b["id"], "title": f"{PREFIX}-成片B-{run_tag}"},
        expect=(201,),
    )
    u2 = jreq(
        "POST", f"/api/final-videos/{fv2['id']}/usages",
        {"source_shot_id": shot1["id"]}, expect=(201,),
    )
    jreq("POST", f"/api/final-video-usages/{u2['id']}/confirm", {})
    s = shot_summary(shot1["id"])
    check(s["confirmed_usage_count"] == 2, f"两成片确认后计数 != 2: {s}")
    jreq("POST", f"/api/final-video-usages/{u2['id']}/revoke", {"note": "e2e 撤销"})
    s = shot_summary(shot1["id"])
    check(s["confirmed_usage_count"] == 1, f"撤销后计数 != 1: {s}")
    print("PR_B_REVOKE_RECOUNT_OK")

    # 8) rejected / suspected 不计数
    jreq("POST", f"/api/final-video-usages/{u_shot2['id']}/reject", {})
    s2 = shot_summary(shot2["id"])
    check(s2["confirmed_usage_count"] == 0, f"rejected 误计数: {s2}")
    # suspected 由 psql 注入（本阶段无产生流程，仅验证不计数）
    psql(
        "UPDATE final_video_usage SET status='suspected' "
        f"WHERE id={u_shot2['id']}"
    )
    s2 = shot_summary(shot2["id"])
    check(
        s2["confirmed_usage_count"] == 0 and s2["suspected_count"] == 1,
        f"suspected 误计数: {s2}",
    )
    psql(f"UPDATE final_video_usage SET status='rejected' WHERE id={u_shot2['id']}")

    # 9) 并发创建同一关系 → 恰一条成功
    def try_create():
        return _req(
            "POST", f"/api/final-videos/{fv2['id']}/usages",
            {"source_shot_id": shot2["id"]},
        )[0]

    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
        codes = sorted(pool.map(lambda _: try_create(), range(2)))
    check(codes == [201, 409], f"并发唯一性失败: {codes}")
    rows = psql(
        f"SELECT count(*) FROM final_video_usage WHERE final_video_id={fv2['id']} "
        f"AND source_shot_id={shot2['id']}"
    )
    check(rows == "1", f"并发后重复行: {rows}")

    # 10) 归档成片：历史 confirmed 保持计数；不允许新确认
    jreq("POST", f"/api/final-videos/{fv1['id']}/archive")
    s = shot_summary(shot1["id"])
    check(s["confirmed_usage_count"] == 1, f"归档后计数丢失: {s}")
    st, _ = _req("POST", f"/api/final-videos/{fv1['id']}/usages", {"source_shot_id": shot2["id"]})
    check(st == 409, f"归档成片新增 usage 应 409，实际 {st}")
    jreq("POST", f"/api/final-videos/{fv1['id']}/restore")
    print("PR_B_USAGE_COUNT_SEMANTICS_OK")

    # 11) 事件审计 append-only（同事务写入）
    events = jreq("GET", f"/api/final-video-usages/{u_shot1['id']}/events")["items"]
    actions = [e["action"] for e in events]
    check(
        actions[:2] == ["create_proposal", "confirm"] and "occurrence_add" in actions,
        f"事件序列异常: {actions}",
    )
    ev_cnt = psql(f"SELECT count(*) FROM final_video_usage_event WHERE usage_id={u_shot1['id']}")
    check(int(ev_cnt) == len(events), "事件行数与 API 不一致")

    # 12) 血缘与统计视图
    lineage = jreq("GET", f"/api/final-videos/{fv1['id']}/lineage")
    check(len(lineage["usages"]) == 2, "lineage usage 数异常")
    asset_sum = jreq("GET", f"/api/assets/{src_a['id']}/usage-summary")
    check(asset_sum["used_shot_count"] == 1, f"asset summary 异常: {asset_sum}")
    check(asset_sum["distinct_final_video_count"] == 1, f"asset distinct 异常: {asset_sum}")
    batch = jreq("GET", f"/api/shot-usage-summaries?shot_ids={shot1['id']},{shot2['id']}")
    m = {it["shot_id"]: it for it in batch["items"]}
    check(m[shot1["id"]]["confirmed_usage_count"] == 1, "批量计数异常")
    print("PR_B_USAGE_LINEAGE_OK")

    # 13) 旧业务兼容（关键旧接口仍工作）
    for path in ("/api/products?limit=1", "/api/product-catalog/tree", "/api/projects?page=1&page_size=1",
                 "/api/assets?page=1&page_size=1", "/health/ready"):
        jreq("GET", path)
    print("PR_B_BACKWARD_COMPAT_OK")

    # 持久化状态供 check-persist 使用（仅 ID 与计数，不含路径）
    state = {
        "run_tag": run_tag,
        "fv1": fv1["id"], "fv2": fv2["id"],
        "usage_confirmed": u_shot1["id"],
        "shot1": shot1["id"],
        "expected_shot1_confirmed": 1,
        "expected_events_min": len(events),
        "expected_occurrences": 2,
    }
    with open(".prb_e2e_state.json", "w", encoding="utf-8") as f:
        json.dump(state, f)
    print("PR_B_API_E2E_OK")


def run_check_persist() -> None:
    with open(".prb_e2e_state.json", encoding="utf-8") as f:
        st = json.load(f)
    fv1 = jreq("GET", f"/api/final-videos/{st['fv1']}")
    check(fv1["usage_stats"]["confirmed_count"] >= 1, "重启后 confirmed 丢失")
    s = shot_summary(st["shot1"])
    check(
        s["confirmed_usage_count"] == st["expected_shot1_confirmed"],
        f"重启后计数变化: {s}",
    )
    occs = jreq("GET", f"/api/final-video-usages/{st['usage_confirmed']}/occurrences")["items"]
    check(len(occs) == st["expected_occurrences"], "重启后 occurrence 丢失")
    events = jreq("GET", f"/api/final-video-usages/{st['usage_confirmed']}/events")["items"]
    check(len(events) >= st["expected_events_min"], "重启后事件丢失")
    print("PR_B_RESTART_PERSIST_OK")
    print("PR_B_PERSIST_OK")


def run_cleanup() -> None:
    # 仅清理本前缀数据：血缘行（级联 usage/occurrence/event）→ 脚本/项目 → 上传素材行。
    # RESTRICT 外键要求先删任何引用本前缀素材的成片行（含 UI E2E 的 PRB-UI 前缀），
    # 再删素材行——否则 DB 兜底会拒绝（这正是血缘保护的预期行为）。
    psql(f"DELETE FROM final_video WHERE title LIKE '{PREFIX}%'")
    psql(
        "DELETE FROM final_video WHERE asset_id IN "
        f"(SELECT id FROM asset WHERE filename LIKE '{PREFIX}%')"
    )
    psql(
        "DELETE FROM final_video_usage WHERE source_asset_id IN "
        f"(SELECT id FROM asset WHERE filename LIKE '{PREFIX}%')"
    )
    psql(f"DELETE FROM script_project WHERE name LIKE '{PREFIX}%'")
    psql(f"DELETE FROM project WHERE name LIKE '{PREFIX}%'")
    psql(f"DELETE FROM asset WHERE filename LIKE '{PREFIX}%'")
    print("PR_B_CLEANUP_OK")


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
