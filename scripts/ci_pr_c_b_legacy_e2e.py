#!/usr/bin/env python3
"""PR-C Gate B 端到端（历史使用证据；纯 API + 中性合成数据 + 隔离上传根）。

流程（--mode full）：
上传 3 个合成视频（A/B/C）→ A 移入 ``hist-marker-<tag>`` 目录再扫描（形成目录标记位置）→
经 API 创建两条中性规则（目录名 equals + 文件名 contains，绝不写死业务词）→
只读预览（零写入断言）→ 正式导入 → 幂等重跑（不增证据、观察数累加、不覆盖人工结论）→
审核工作流（accept/reject/reset/bulk + 409 守卫 + 事件轨迹）→
Asset 派生状态 → confirmed 使用次数隔离（accept 前后一个数字都不变）→
再移动文件（证据仍绑 Asset）→ 规则修改不重解释历史 → 旧接口兼容。

隔离保证：只操作 ``/app/uploads`` 下 ``PRCB-E2E`` 前缀合成文件；规则 pattern 带随机
tag（不会误伤其他数据）；预览/导入均限定 rule_ids + 上传根。绝不触碰真实素材。

用法：
    API_BASE=http://localhost:8000 python scripts/ci_pr_c_b_legacy_e2e.py --mode full
    API_BASE=http://localhost:8000 python scripts/ci_pr_c_b_legacy_e2e.py --mode check-persist
    API_BASE=http://localhost:8000 python scripts/ci_pr_c_b_legacy_e2e.py --mode cleanup
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
PREFIX = "PRCB-E2E"
STATE_FILE = ".prcb_e2e_state.json"
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


def expect_status(method: str, path: str, body, expected: int) -> None:
    status, data = _req(method, path, body)
    if status != expected:
        print(f"E2E FAIL: {method} {path} 应 {expected} 实际 {status}: {data}", file=sys.stderr)
        sys.exit(1)


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


def upload_video(local_path: str, filename: str) -> tuple[int, str]:
    """上传并返回 (source_directory_id, 服务端实际落盘文件名)。

    以服务端返回名为准（重名去重会追加后缀），并打印响应便于 CI 诊断。
    """
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
    print(f"[upload] {res.get('filename')} bytes={res.get('bytes')} "
          f"sd={res.get('source_directory_id')} scan_run={res.get('scan_run_id')}")
    check(int(res.get("bytes") or 0) > 0, f"上传字节数为 0: {res}")
    return int(res["source_directory_id"]), str(res["filename"])


def wait_asset(filename: str, sd_id: int | None = None, *, status="indexed") -> dict:
    deadline = time.time() + 300
    rescan_at = time.time() + 45

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
            # 周期性重扫（非一次性）：上传若撞上仍在跑的旧 scan run，
            # POST 会被幂等合并进旧 run（其目录快照不含新文件）；
            # 旧 run 结束后的下一次 POST 才会真正开新 run 扫到新文件。
            _req("POST", f"/api/source-directories/{sd_id}/scan")
            rescan_at = time.time() + 45
        time.sleep(3)
    if sd_id is not None:
        st, s = _req("GET", f"/api/source-directories/{sd_id}/status")
        print(f"E2E DIAG: sd={sd_id} status={st} latest_run={s.get('latest_run')}",
              file=sys.stderr)
    print(f"E2E FAIL: 等待素材 {filename} 超时", file=sys.stderr)
    sys.exit(1)


def scan_and_wait(sd_id: int) -> None:
    def status():
        return jreq("GET", f"/api/source-directories/{sd_id}/status")

    poll(
        status,
        lambda s: (s.get("latest_run") or {}).get("status") not in ("queued", "running"),
        desc=f"等待前序扫描 root={sd_id}",
    )
    run = jreq("POST", f"/api/source-directories/{sd_id}/scan", expect=(202,))
    done = poll(
        status,
        lambda s: (s.get("latest_run") or {}).get("id") == run["id"]
        and s["latest_run"]["status"] in ("completed", "failed"),
        desc=f"扫描 root={sd_id}",
    )
    check(done["latest_run"]["status"] == "completed", f"扫描失败: {done['latest_run']}")
    lr = done["latest_run"]
    print(f"[scan] run={lr.get('id')} discovered={lr.get('files_discovered')} "
          f"new={lr.get('files_new')} missing={lr.get('files_missing')} "
          f"errored={lr.get('files_errored')}")


def run_fingerprint(asset_id: int, kind: str) -> None:
    """移动前先算指纹——PR-C 场景 A 自动 relink 只认 full hash。"""
    job = jreq("POST", f"/api/assets/{asset_id}/fingerprint", {"kind": kind}, expect=(202,))
    done = poll(
        lambda: jreq("GET", f"/api/assets/fingerprint-jobs/{job['id']}"),
        lambda j: j["status"] in ("completed", "partial", "failed"),
        desc=f"指纹 {kind} asset={asset_id}",
    )
    check(done["status"] == "completed", f"指纹任务失败: {done}")


def analyze_and_wait(asset_id: int) -> list[dict]:
    jreq("POST", f"/api/assets/{asset_id}/analyze-shots", expect=(202,))
    poll(
        lambda: jreq("GET", f"/api/assets/{asset_id}/shot-analysis"),
        lambda s: s.get("status") == "completed",
        desc=f"拆镜头 asset={asset_id}",
    )
    return jreq("GET", f"/api/assets/{asset_id}/shots?page=1&page_size=50")["items"]


def run_import_and_wait(body: dict) -> dict:
    run = jreq("POST", "/api/legacy-usage-imports", body, expect=(202,))
    done = poll(
        lambda: jreq("GET", f"/api/legacy-usage-imports/{run['id']}"),
        lambda r: r["status"] in ("completed", "completed_with_errors", "failed", "cancelled"),
        timeout=180, desc=f"导入 run={run['id']}",
    )
    check(done["status"] == "completed", f"导入运行未成功: {done}")
    return done


def legacy_counts() -> tuple[int, int, int, int]:
    return tuple(
        int(psql(f"select count(*) from {t}"))
        for t in ("legacy_usage_rule", "legacy_usage_import_run",
                  "legacy_usage_evidence", "legacy_usage_evidence_event")
    )


def evidence_for_asset(asset_id: int) -> list[dict]:
    return jreq(
        "GET", f"/api/legacy-usage-evidence?page=1&page_size=50&asset_id={asset_id}"
    )["items"]


def prefix_usage_rows() -> str:
    return psql(
        "select count(*) from final_video_usage where source_asset_id in "
        f"(select id from asset where filename like '{PREFIX}%')"
    )


def run_full() -> None:
    tag = uuid.uuid4().hex[:6]
    tmp = tempfile.mkdtemp(prefix="prcb_e2e_")
    marker_dir = f"hist-marker-{tag}"
    a_name = f"{PREFIX}-a-{tag}.mp4"
    b_name = f"{PREFIX}-b-{tag}.used-copy.mp4"
    c_name = f"{PREFIX}-c-{tag}.mp4"
    fin_name = f"{PREFIX}-final-{tag}.mp4"

    # 1) 上传 A/B/C + 成片文件 → 显式扫描（等前序活动 run 结束再开新 run，
    #    避免上传撞上旧 run 被幂等合并而错过快照）→ 索引
    # tag 作为颜色段混入内容：ffmpeg 合成是字节确定性的，若与其他 E2E 的
    # 视频同字节，会被 PR-C 复制/歧义检测挂为已有 Asset 的位置而不建新 Asset
    uniq = f"#{tag}"  # uuid hex[:6] 恰为合法 RGB
    make_video(os.path.join(tmp, "a.mp4"), ["red", "blue", uniq])
    make_video(os.path.join(tmp, "b.mp4"), ["yellow", uniq])
    make_video(os.path.join(tmp, "c.mp4"), ["gray", uniq])
    make_video(os.path.join(tmp, "f.mp4"), ["green", uniq])
    sd_id, a_name = upload_video(os.path.join(tmp, "a.mp4"), a_name)
    _, b_name = upload_video(os.path.join(tmp, "b.mp4"), b_name)
    _, c_name = upload_video(os.path.join(tmp, "c.mp4"), c_name)
    _, fin_name = upload_video(os.path.join(tmp, "f.mp4"), fin_name)
    scan_and_wait(sd_id)
    asset_a = wait_asset(a_name, sd_id)
    asset_b = wait_asset(b_name, sd_id)
    asset_c = wait_asset(c_name, sd_id)
    fin = wait_asset(fin_name, sd_id)

    # 2) A 移入历史标记目录（模拟旧运营习惯）→ 再扫描 relink（PR-C 场景 A）
    # relink 只认 full hash（权威身份），移动前先算 quick+full
    run_fingerprint(asset_a["id"], "quick")
    run_fingerprint(asset_a["id"], "full")
    container_sh(
        f"mkdir -p /app/uploads/{PREFIX}-root-{tag}/{marker_dir} && "
        f"mv \"/app/uploads/{a_name}\" \"/app/uploads/{PREFIX}-root-{tag}/{marker_dir}/{a_name}\""
    )
    scan_and_wait(sd_id)
    moved = jreq("GET", f"/api/assets/{asset_a['id']}")
    check(marker_dir in moved["relative_path"], f"A 未 relink 到标记目录: {moved['relative_path']}")

    # 3) 血缘前置：A 拆镜头 + 成片 + confirmed usage（供隔离断言用）
    shots = analyze_and_wait(asset_a["id"])
    check(len(shots) >= 1, "A 无镜头")
    fv = jreq("POST", "/api/final-videos",
              {"asset_id": fin["id"], "title": f"{PREFIX}-成片-{tag}"}, expect=(201,))
    usage = jreq("POST", f"/api/final-videos/{fv['id']}/usages",
                 {"source_shot_id": shots[0]["id"]}, expect=(201,))
    jreq("POST", f"/api/final-video-usages/{usage['id']}/confirm", {})

    # 4) 经 API 创建两条中性受控规则（目录名 equals + 文件名 contains；带 tag 不误伤）
    r1 = jreq("POST", "/api/legacy-usage-rules", {
        "name": f"{PREFIX}-目录标记-{tag}",
        "match_target": "directory_segment",
        "match_operator": "equals",
        "pattern": marker_dir,
        "source_directory_id": sd_id,
    }, expect=(201,))
    r2 = jreq("POST", "/api/legacy-usage-rules", {
        "name": f"{PREFIX}-文件名标记-{tag}",
        "match_target": "filename",
        "match_operator": "contains",
        "pattern": f"-{tag}.used-copy",
        "source_directory_id": sd_id,
    }, expect=(201,))
    rule_ids = [r1["id"], r2["id"]]
    # 受控白名单：任意正则/穿越 pattern 均 422
    expect_status("POST", "/api/legacy-usage-rules", {
        "name": "bad", "match_target": "regex", "match_operator": "equals", "pattern": "x",
    }, 422)
    expect_status("POST", "/api/legacy-usage-rules", {
        "name": "bad", "match_target": "filename", "match_operator": "matches_regex",
        "pattern": "x",
    }, 422)
    expect_status("POST", "/api/legacy-usage-rules", {
        "name": "bad", "match_target": "filename", "match_operator": "equals",
        "pattern": "a/../b",
    }, 422)
    print("PR_C_B_RULE_ENGINE_OK")

    # 5) 只读预览：命中 A（目录）+ B（文件名），C 不命中；四表零写入
    before = legacy_counts()
    scope = {"source_directory_id": sd_id, "rule_ids": rule_ids}
    prev = jreq("POST", "/api/legacy-usage-imports/preview", scope)
    check(prev["matched_asset_count"] == 2, f"预览应命中 2 素材: {prev}")
    check(prev["would_create_count"] == 2, f"预览应新建 2 证据: {prev}")
    check(prev["existing_evidence_count"] == 0, "预览前不应有证据")
    check(str(r1["id"]) in prev["by_rule"] and str(r2["id"]) in prev["by_rule"],
          f"by_rule 缺失: {prev['by_rule']}")
    check(legacy_counts() == before, "预览发生写入！")
    print("PR_C_B_DRY_RUN_OK")

    # 6) 正式导入 → 2 条 pending 证据（绑定 Asset，绝不绑定 Shot/成片）
    done = run_import_and_wait(scope)
    check(done["created_evidence_count"] == 2 and done["existing_evidence_count"] == 0,
          f"导入计数异常: {done}")
    ev_a = evidence_for_asset(asset_a["id"])
    ev_b = evidence_for_asset(asset_b["id"])
    check(len(ev_a) == 1 and ev_a[0]["review_status"] == "pending", f"A 证据异常: {ev_a}")
    check(ev_a[0]["matched_component"] == marker_dir, f"A 命中片段异常: {ev_a[0]}")
    check(len(ev_b) == 1 and ev_b[0]["evidence_type"] == "filename_marker", f"B 证据异常: {ev_b}")
    check(evidence_for_asset(asset_c["id"]) == [], "C 不应有证据")
    print("PR_C_B_IMPORT_OK")

    # 7) 幂等重跑：不增证据、观察数累加、pending 保持
    done2 = run_import_and_wait(scope)
    check(done2["created_evidence_count"] == 0 and done2["existing_evidence_count"] == 2,
          f"幂等导入计数异常: {done2}")
    ev_a2 = evidence_for_asset(asset_a["id"])
    check(len(ev_a2) == 1 and ev_a2[0]["observation_count"] == 2, f"观察数未累加: {ev_a2}")
    check(ev_a2[0]["review_status"] == "pending", "幂等导入不得改审核状态")
    print("PR_C_B_IMPORT_IDEMPOTENT_OK")

    # 8) 审核工作流：accept（带操作人）→ 409 守卫；B reject → reset → bulk-reject
    eid_a, eid_b = ev_a[0]["id"], ev_b[0]["id"]
    usage_rows_before = prefix_usage_rows()
    summary_before = jreq("GET", f"/api/assets/{asset_a['id']}/usage-summary")

    acc = jreq("POST", f"/api/legacy-usage-evidence/{eid_a}/accept",
               {"actor_label": "e2e-审核员", "note": "目录语义确认"})
    check(acc["review_status"] == "accepted" and acc["actor_label"] == "e2e-审核员",
          f"accept 异常: {acc}")
    expect_status("POST", f"/api/legacy-usage-evidence/{eid_a}/accept", {}, 409)
    rej = jreq("POST", f"/api/legacy-usage-evidence/{eid_b}/reject", {})
    check(rej["review_status"] == "rejected", "reject 异常")
    rst = jreq("POST", f"/api/legacy-usage-evidence/{eid_b}/reset", {})
    check(rst["review_status"] == "pending", "reset 异常")
    bulk = jreq("POST", "/api/legacy-usage-evidence/bulk-reject",
                {"evidence_ids": [eid_b, eid_a], "actor_label": "e2e-批量"})
    check(bulk["succeeded"] == 1 and bulk["skipped"] == 1 and bulk["skipped_ids"] == [eid_a],
          f"bulk 结果异常: {bulk}")  # accepted 的 A 被跳过，绝不静默覆盖
    events = jreq("GET", f"/api/legacy-usage-evidence/{eid_b}/events")["items"]
    actions = [e["action"] for e in events]
    check(actions == ["detected", "observed_again", "rejected", "reset_to_pending",
                      "bulk_rejected"],
          f"事件轨迹异常: {actions}")
    print("PR_C_B_REVIEW_WORKFLOW_OK")

    # 9) Asset 派生状态：A=used_unknown；B=rejected；C=no_evidence
    sum_a = jreq("GET", f"/api/assets/{asset_a['id']}/usage-summary")
    sum_b = jreq("GET", f"/api/assets/{asset_b['id']}/usage-summary")
    sum_c = jreq("GET", f"/api/assets/{asset_c['id']}/usage-summary")
    check(sum_a["legacy_usage_state"] == "legacy_used_unknown", f"A 状态异常: {sum_a}")
    check(sum_a["accepted_legacy_evidence_count"] == 1, "A accepted 计数异常")
    check(sum_b["legacy_usage_state"] == "legacy_evidence_rejected", f"B 状态异常: {sum_b}")
    check(sum_c["legacy_usage_state"] == "no_legacy_evidence", f"C 状态异常: {sum_c}")
    lsum = jreq("GET", f"/api/assets/{asset_a['id']}/legacy-usage-summary")
    check(lsum["legacy_usage_state"] == "legacy_used_unknown" and lsum["accepted_count"] == 1,
          f"legacy-usage-summary 异常: {lsum}")
    print("PR_C_B_LEGACY_STATE_OK")

    # 10) 隔离铁律：accept 前后 confirmed 一个数字都不变；无新 FinalVideoUsage
    check(prefix_usage_rows() == usage_rows_before, "证据审核改变了 FinalVideoUsage 行数！")
    for key in ("confirmed_usage_count", "used_shot_count", "distinct_final_video_count",
                "usage_distribution", "total_shots"):
        check(sum_a[key] == summary_before[key],
              f"confirmed 统计被证据改变: {key} {summary_before[key]} -> {sum_a[key]}")
    check(sum_a["confirmed_usage_count"] == 1 and sum_a["usage_count_known"] is True,
          f"A confirmed 基线异常: {sum_a}")
    shot_sum = jreq("GET", f"/api/shots/{shots[0]['id']}/usage-summary")
    check(shot_sum["confirmed_usage_count"] == 1, "Shot confirmed 被证据影响")
    print("PR_C_B_USAGE_COUNT_UNCHANGED_OK")

    # 11) 再移动 A（离开标记目录）：证据仍绑 Asset、审核结论不变、位置历史保留
    container_sh(
        f"mkdir -p /app/uploads/{PREFIX}-clean-{tag} && "
        f"mv \"/app/uploads/{PREFIX}-root-{tag}/{marker_dir}/{a_name}\" "
        f"\"/app/uploads/{PREFIX}-clean-{tag}/{a_name}\""
    )
    scan_and_wait(sd_id)
    moved2 = jreq("GET", f"/api/assets/{asset_a['id']}")
    check(f"{PREFIX}-clean-{tag}" in moved2["relative_path"], "A 第二次移动未 relink")
    ev_a3 = evidence_for_asset(asset_a["id"])
    check(len(ev_a3) == 1 and ev_a3[0]["review_status"] == "accepted",
          f"移动后证据丢失/状态变化: {ev_a3}")
    locs = jreq("GET", f"/api/assets/{asset_a['id']}/locations")
    check(any(loc["location_status"] == "historical" and marker_dir in loc["relative_path"]
              for loc in locs), "标记目录应保留在位置历史中")
    print("PR_C_B_LOCATION_HISTORY_OK")

    # 12) 规则修改不重解释历史：改 pattern 后旧证据快照/命中片段不变
    jreq("PATCH", f"/api/legacy-usage-rules/{r1['id']}", {"pattern": f"renamed-{tag}"})
    ev_a4 = evidence_for_asset(asset_a["id"])
    check(ev_a4[0]["matched_component"] == marker_dir, "规则修改重解释了历史证据！")
    snap_pattern = psql(
        f"select rule_snapshot->>'pattern' from legacy_usage_evidence where id={eid_a}"
    )
    check(snap_pattern == marker_dir, f"证据快照被改写: {snap_pattern}")
    jreq("PATCH", f"/api/legacy-usage-rules/{r1['id']}", {"pattern": marker_dir})

    # 13) 旧业务兼容
    for path in ("/api/products?limit=1", "/api/final-videos?page=1&page_size=1",
                 f"/api/assets/{asset_c['id']}", "/health/ready"):
        jreq("GET", path)
    print("PR_C_B_BACKWARD_COMPAT_OK")

    state = {
        "tag": tag, "sd_id": sd_id,
        "asset_a": asset_a["id"], "asset_b": asset_b["id"], "asset_c": asset_c["id"],
        "rule_ids": rule_ids, "eid_a": eid_a, "eid_b": eid_b,
        "marker_dir": marker_dir, "usage_rows": prefix_usage_rows(),
        "shot_id": shots[0]["id"],
    }
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f)
    print("PR_C_B_API_E2E_OK")


def run_check_persist() -> None:
    with open(STATE_FILE, encoding="utf-8") as f:
        st = json.load(f)
    # 规则仍在且配置完整
    r1 = jreq("GET", f"/api/legacy-usage-rules/{st['rule_ids'][0]}")
    check(r1["pattern"] == st["marker_dir"], "重启后规则配置丢失")
    # 证据状态/观察数/事件轨迹仍在
    ev_a = jreq("GET", f"/api/legacy-usage-evidence/{st['eid_a']}")
    check(ev_a["review_status"] == "accepted" and ev_a["observation_count"] >= 2,
          f"重启后 A 证据状态丢失: {ev_a}")
    # full 结束时 B=rejected；若 UI E2E 已在同栈审核过则为 accepted——两者都证明
    # 人工结论跨重启持久（丢失时会回 pending/404）
    ev_b = jreq("GET", f"/api/legacy-usage-evidence/{st['eid_b']}")
    check(ev_b["review_status"] in ("rejected", "accepted"),
          f"重启后 B 证据状态丢失: {ev_b}")
    events = jreq("GET", f"/api/legacy-usage-evidence/{st['eid_b']}/events")["items"]
    check(len(events) >= 5, f"重启后事件轨迹丢失: {len(events)}")
    # 派生状态与 confirmed 隔离仍成立
    sum_a = jreq("GET", f"/api/assets/{st['asset_a']}/usage-summary")
    check(sum_a["legacy_usage_state"] == "legacy_used_unknown", "重启后派生状态丢失")
    check(sum_a["confirmed_usage_count"] == 1, "重启后 confirmed 变化")
    check(prefix_usage_rows() == st["usage_rows"], "重启后 FinalVideoUsage 行数变化")
    runs = jreq("GET", "/api/legacy-usage-imports?page=1&page_size=10")
    check(runs["total"] >= 2, "重启后导入运行记录丢失")
    print("PR_C_B_RESTART_PERSIST_OK")


def run_cleanup() -> None:
    psql(
        "DELETE FROM legacy_usage_evidence WHERE asset_id IN "
        f"(SELECT id FROM asset WHERE filename LIKE '{PREFIX}%')"
    )
    psql(f"DELETE FROM legacy_usage_rule WHERE name LIKE '{PREFIX}%'")
    psql(f"DELETE FROM legacy_usage_import_run WHERE rule_snapshot::text LIKE '%{PREFIX}%'")
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
         f"rm -rf /app/uploads/{PREFIX}* 2>/dev/null; true"],
        capture_output=True, check=False,
    )
    print("PR_C_B_CLEANUP_OK")


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
