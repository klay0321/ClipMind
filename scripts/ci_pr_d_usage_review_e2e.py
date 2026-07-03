#!/usr/bin/env python3
"""PR-D 端到端（统一使用记录中心；纯 API + 中性合成数据 + 隔离上传根）。

流程（--mode full，§十二）：
上传合成视频（A=3 镜头源、F=成片、B/C=带文件名标记）→ 分析 A → 建成片 →
2 条 manual proposed usage → 规则 + 导入产生 2 条 pending evidence →
统一 summary needs_review=4 → 批量确认 2 formal → confirmed=2 →
批量接受 2 legacy → confirmed 仍=2（隔离铁律）→ 两类进入不同已处理分组 →
制造 1 条 conflict → 混合批次 422 / 非法 action 422 / partial failure 明细 →
clue 补录（人工指定成片与第 3 个镜头 → manual proposed → confirmed 不变 →
再明确 confirm → +1）→ 事件计数 → Shot/Asset summary 口径 → 旧接口兼容。

隔离保证：只操作 /app/uploads 下 PRD-E2E 前缀合成文件；合成视频混入
tag 颜色段保证字节唯一；规则 pattern 带 tag；绝不触碰真实素材。

用法：
    API_BASE=http://localhost:8000 python scripts/ci_pr_d_usage_review_e2e.py --mode full
    API_BASE=http://localhost:8000 python scripts/ci_pr_d_usage_review_e2e.py --mode check-persist
    API_BASE=http://localhost:8000 python scripts/ci_pr_d_usage_review_e2e.py --mode seed-ui
    API_BASE=http://localhost:8000 python scripts/ci_pr_d_usage_review_e2e.py --mode cleanup
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
PREFIX = "PRD-E2E"
STATE_FILE = ".prd_e2e_state.json"
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


def expect_status(method: str, path: str, body, expected: int) -> None:
    status, data = _req(method, path, body)
    if status != expected:
        print(f"E2E FAIL: {method} {path} 应 {expected} 实际 {status}: {data}",
              file=sys.stderr)
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
          f"sd={res.get('source_directory_id')}")
    return int(res["source_directory_id"]), str(res["filename"])


def scan_and_wait(sd_id: int) -> None:
    def status():
        return jreq("GET", f"/api/source-directories/{sd_id}/status")

    poll(status,
         lambda s: (s.get("latest_run") or {}).get("status") not in ("queued", "running"),
         desc=f"等待前序扫描 root={sd_id}")
    run = jreq("POST", f"/api/source-directories/{sd_id}/scan", expect=(202,))
    done = poll(
        status,
        lambda s: (s.get("latest_run") or {}).get("id") == run["id"]
        and s["latest_run"]["status"] in ("completed", "failed"),
        desc=f"扫描 root={sd_id}",
    )
    check(done["latest_run"]["status"] == "completed", f"扫描失败: {done['latest_run']}")


def wait_asset(filename: str, sd_id: int, *, status="indexed") -> dict:
    deadline = time.time() + 300
    rescan_at = time.time() + 45
    while time.time() < deadline:
        q = urllib.parse.quote(filename)
        data = jreq("GET", f"/api/assets?page=1&page_size=50&q={q}")
        for item in data.get("items", []):
            if item["filename"] == filename and item["status"] == status:
                return item
        if time.time() >= rescan_at:
            _req("POST", f"/api/source-directories/{sd_id}/scan")
            rescan_at = time.time() + 45
        time.sleep(3)
    print(f"E2E FAIL: 等待素材 {filename} 超时", file=sys.stderr)
    sys.exit(1)


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


def bulk(items, action, expect=(200,)):
    return jreq("POST", "/api/usage-review/bulk",
                {"items": items, "action": action}, expect=expect)


def fref(uid):
    return {"item_type": "final_video_usage", "item_id": uid}


def lref(eid):
    return {"item_type": "legacy_usage_evidence", "item_id": eid}


def confirmed_count(shot_ids) -> int:
    total = 0
    for sid in shot_ids:
        s = jreq("GET", f"/api/shots/{sid}/usage-summary")
        total += s["confirmed_usage_count"]
    return total


def _seed_stage(tag: str):
    """上传 A/F/B/C → 索引 → 分析 A → 成片 + 2 usage + 规则 + 2 evidence。"""
    tmp = tempfile.mkdtemp(prefix="prd_e2e_")
    uniq = f"#{tag}"
    a_name = f"{PREFIX}-a-{tag}.mp4"
    f_name = f"{PREFIX}-final-{tag}.mp4"
    b_name = f"{PREFIX}-b.urc-{tag}.mp4"
    c_name = f"{PREFIX}-c.urc-{tag}.mp4"
    make_video(os.path.join(tmp, "a.mp4"), ["red", "blue", "yellow", uniq])
    make_video(os.path.join(tmp, "f.mp4"), ["green", uniq])
    make_video(os.path.join(tmp, "b.mp4"), ["gray", uniq])
    make_video(os.path.join(tmp, "c.mp4"), ["white", uniq])
    sd_id, a_name = upload_video(os.path.join(tmp, "a.mp4"), a_name)
    _, f_name = upload_video(os.path.join(tmp, "f.mp4"), f_name)
    _, b_name = upload_video(os.path.join(tmp, "b.mp4"), b_name)
    _, c_name = upload_video(os.path.join(tmp, "c.mp4"), c_name)
    scan_and_wait(sd_id)
    asset_a = wait_asset(a_name, sd_id)
    fin = wait_asset(f_name, sd_id)
    wait_asset(b_name, sd_id)
    wait_asset(c_name, sd_id)

    shots = analyze_and_wait(asset_a["id"])
    check(len(shots) >= 3, f"A 镜头不足: {len(shots)}")
    fv = jreq("POST", "/api/final-videos",
              {"asset_id": fin["id"], "title": f"{PREFIX}-成片-{tag}"}, expect=(201,))
    usages = []
    for s in shots[:2]:
        usages.append(jreq(
            "POST", f"/api/final-videos/{fv['id']}/usages",
            {"source_shot_id": s["id"]}, expect=(201,),
        ))
    rule = jreq("POST", "/api/legacy-usage-rules", {
        "name": f"{PREFIX}-文件名标记-{tag}",
        "match_target": "filename",
        "match_operator": "contains",
        "pattern": f".urc-{tag}.",
        "source_directory_id": sd_id,
    }, expect=(201,))
    done = run_import_and_wait({"source_directory_id": sd_id, "rule_ids": [rule["id"]]})
    check(done["created_evidence_count"] == 2, f"应产生 2 条证据: {done}")
    evs = jreq("GET",
               f"/api/legacy-usage-evidence?page=1&page_size=10&rule_id={rule['id']}")["items"]
    check(len(evs) == 2, f"证据数异常: {len(evs)}")
    return sd_id, asset_a, fv, shots, usages, rule, evs


def run_full() -> None:
    tag = uuid.uuid4().hex[:6]
    sd_id, asset_a, fv, shots, usages, rule, evs = _seed_stage(tag)
    uid1, uid2 = usages[0]["id"], usages[1]["id"]
    eid1, eid2 = evs[0]["id"], evs[1]["id"]
    shot_ids = [s["id"] for s in shots[:3]]

    # 1) 统一 Read Model：needs_review=4、两类并列、legacy 空 Shot/成片
    summary = jreq("GET", "/api/usage-review/summary")
    check(summary["formal"]["proposed"] >= 2 and summary["legacy"]["pending"] >= 2,
          f"summary 基线异常: {summary}")
    check("total_used_count" not in summary, "出现了被禁止的混合总数！")
    # q=tag 命中本次全部合成文件名（A 的 usage 行 + B/C 的证据行）
    items = jreq(
        "GET",
        f"/api/usage-review/items?review_group=needs_review&q={tag}"
        "&page=1&page_size=20",
    )
    check(items["total"] == 4, f"本次待审应为 4: {items['total']}")
    legacy_rows = [i for i in items["items"] if i["item_type"] == "legacy_usage_evidence"]
    formal_rows = [i for i in items["items"] if i["item_type"] == "final_video_usage"]
    check(len(legacy_rows) == 2 and len(formal_rows) == 2, "两类记录并列异常")
    check(all(i["shot_id"] is None and i["final_video_id"] is None for i in legacy_rows),
          "legacy 行必须无 Shot/成片")
    check(all(i["source_strength"] == "manual_proposed_lineage" for i in formal_rows),
          "formal 候选可信等级异常")
    detail = jreq("GET", f"/api/usage-review/items/legacy_usage_evidence/{eid1}")
    check(detail["legacy_evidence"] is not None and detail["formal_usage"] is None,
          "详情结构异常")
    print("PR_D_UNIFIED_READ_MODEL_OK")

    # 2) 批量确认 2 formal → confirmed=2
    out = bulk([fref(uid1), fref(uid2)], "confirm")
    check(out["succeeded"] == 2, f"formal 批量确认异常: {out}")
    check(confirmed_count(shot_ids) == 2, "confirmed count 应为 2")
    print("PR_D_FORMAL_BULK_REVIEW_OK")

    # 3) 批量接受 2 legacy → confirmed 仍=2（隔离铁律）
    usage_rows_before = psql("select count(*) from final_video_usage")
    out = bulk([lref(eid1), lref(eid2)], "accept")
    check(out["succeeded"] == 2, f"legacy 批量接受异常: {out}")
    check(confirmed_count(shot_ids) == 2, "legacy accept 改变了 confirmed count！")
    check(psql("select count(*) from final_video_usage") == usage_rows_before,
          "legacy accept 创建了 FinalVideoUsage！")
    print("PR_D_LEGACY_BULK_REVIEW_OK")

    # 4) 两类记录进入不同已处理分组（同组不同类型并列，绝不相加）
    done_items = jreq(
        "GET",
        "/api/usage-review/items?review_group=accepted_or_confirmed"
        f"&q={tag}&page=1&page_size=20",
    )
    types = {i["item_type"] for i in done_items["items"]}
    check(done_items["total"] == 4 and types == {
        "final_video_usage", "legacy_usage_evidence"}, f"已处理分组异常: {done_items}")
    strengths = {i["source_strength"] for i in done_items["items"]}
    check(strengths == {"confirmed_lineage", "accepted_legacy_evidence"},
          f"可信等级异常: {strengths}")

    # 5) 制造 conflict → 单独分组
    out = bulk([lref(eid2)], "mark_conflict")
    check(out["succeeded"] == 1, "标冲突失败")
    conf = jreq("GET", f"/api/usage-review/items?review_group=conflict&q={tag}")
    check(conf["total"] == 1, "conflict 分组异常")

    # 6) 守卫：混合类型 422、非法 action 422、partial failure 明细准确
    bulk([fref(uid1), lref(eid1)], "confirm", expect=(422,))
    bulk([fref(uid1)], "accept", expect=(422,))
    bulk([lref(eid1)], "confirm", expect=(422,))
    out = bulk([fref(uid1), fref(999999)], "confirm")  # 已 confirmed→skip；不存在→failed
    check(out["succeeded"] == 0 and out["skipped"] == 1 and out["failed"] == 1,
          f"partial failure 明细异常: {out}")
    outcomes = {r["item_id"]: r["outcome"] for r in out["results"]}
    check(outcomes[uid1] == "skipped" and outcomes[999999] == "failed", "明细逐条异常")
    print("PR_D_MIXED_TYPE_GUARD_OK")

    # 7) clue 补录：人工指定成片 + 第 3 个镜头 → manual proposed → 明确确认才 +1
    third = shots[2]
    created = jreq(
        "POST", f"/api/final-videos/{fv['id']}/usages",
        {"source_shot_id": third["id"],
         "evidence_summary": f"根据历史线索补录（证据 #{eid1}）"},
        expect=(201,),
    )
    check(created["status"] == "proposed" and created["evidence_method"] == "manual",
          f"补录应为 manual proposed: {created}")
    check(confirmed_count(shot_ids) == 2, "补录候选不得改变 confirmed count")
    ev1 = jreq("GET", f"/api/legacy-usage-evidence/{eid1}")
    check(ev1["review_status"] == "accepted", "补录后证据本体必须保留")
    # 同一 FinalVideo+Shot 已有关系 → 409
    expect_status("POST", f"/api/final-videos/{fv['id']}/usages",
                  {"source_shot_id": third["id"]}, 409)
    out = bulk([fref(created["id"])], "confirm")
    check(out["succeeded"] == 1, "补录确认失败")
    check(confirmed_count(shot_ids) == 3, "明确确认后 confirmed 应 +1")
    print("PR_D_MANUAL_LINEAGE_FROM_CLUE_OK")

    # 8) 隔离终检：Asset summary 两组口径并列不相加；Shot 不继承 legacy
    asum = jreq("GET", f"/api/assets/{asset_a['id']}/usage-summary")
    check(asum["confirmed_usage_count"] == 3, f"asset confirmed 应 3: {asum}")
    # 证据挂在 B/C 素材上：各自 summary 独立体现，A 不受影响（不均摊不相加）
    ev1_full = jreq("GET", f"/api/legacy-usage-evidence/{eid1}")
    b_sum = jreq("GET", f"/api/assets/{ev1_full['asset_id']}/usage-summary")
    check(b_sum["accepted_legacy_evidence_count"] == 1
          and b_sum["confirmed_usage_count"] == 0,
          f"证据素材 summary 异常: {b_sum}")
    ev2_full = jreq("GET", f"/api/legacy-usage-evidence/{eid2}")
    c_sum = jreq("GET", f"/api/assets/{ev2_full['asset_id']}/usage-summary")
    check(c_sum["conflict_legacy_evidence_count"] == 1, f"conflict 素材 summary 异常: {c_sum}")
    ssum = jreq("GET", f"/api/shots/{shot_ids[0]}/usage-summary")
    check(ssum["confirmed_usage_count"] == 1 and "legacy" not in json.dumps(ssum),
          "Shot summary 不得继承 legacy")
    # 事件数：3 manual_add + 3 confirm + 2 accept + 1 conflict（原领域事件）
    fe = psql(
        "select count(*) from final_video_usage_event where usage_id in "
        f"(select id from final_video_usage where source_asset_id={asset_a['id']})"
    )
    check(int(fe) == 6, f"formal 事件数应 6: {fe}")
    print("PR_D_USAGE_COUNT_ISOLATION_OK")

    # 9) 兼容：旧接口原样可用；搜索接口不受影响
    for path in (
        f"/api/final-videos/{fv['id']}/lineage",
        "/api/legacy-usage-evidence?page=1&page_size=5",
        "/api/legacy-usage-rules",
        "/api/final-videos?page=1&page_size=5",
        "/health/ready",
    ):
        jreq("GET", path)
    st, _ = _req("POST", "/api/search/shots", {"query": "test", "page": 1, "page_size": 5})
    check(st in (200, 422), f"搜索接口异常: {st}")
    print("PR_D_BACKWARD_COMPAT_OK")

    state = {
        "tag": tag, "sd_id": sd_id, "asset_a": asset_a["id"], "fv_id": fv["id"],
        "uid1": uid1, "eid1": eid1, "eid2": eid2, "clue_uid": created["id"],
        "shot_ids": shot_ids, "rule_id": rule["id"],
        "usage_rows": psql("select count(*) from final_video_usage"),
    }
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f)
    print("PR_D_API_E2E_OK")


def run_check_persist() -> None:
    with open(STATE_FILE, encoding="utf-8") as f:
        st = json.load(f)
    check(confirmed_count(st["shot_ids"]) == 3, "重启后 confirmed 变化")
    ev = jreq("GET", f"/api/legacy-usage-evidence/{st['eid1']}")
    check(ev["review_status"] == "accepted", "重启后证据状态丢失")
    ev2 = jreq("GET", f"/api/legacy-usage-evidence/{st['eid2']}")
    check(ev2["review_status"] == "conflict", "重启后 conflict 丢失")
    detail = jreq("GET", f"/api/usage-review/items/final_video_usage/{st['clue_uid']}")
    check(detail["item"]["review_status"] == "confirmed", "重启后补录确认丢失")
    check(len(detail["events"]) >= 2, "重启后事件轨迹丢失")
    check(psql("select count(*) from final_video_usage") == st["usage_rows"],
          "重启后 usage 行数变化")
    summary = jreq("GET", "/api/usage-review/summary")
    check(summary["legacy"]["conflict"] >= 1, "重启后 summary 异常")
    print("PR_D_RESTART_PERSIST_OK")


def run_seed_ui() -> None:
    """为 Playwright 播种：1 条 proposed usage + pending evidence
    （含 1 条挂在有镜头素材 A 上的证据，供 clue 补录流程选择镜头）。"""
    tag = uuid.uuid4().hex[:6]
    sd_id, asset_a, fv, shots, usages, rule, evs = _seed_stage(tag)
    # 只确认第 2 条 usage，第 1 条留 pending 给 UI；两条证据全留 pending
    out = bulk([fref(usages[1]["id"])], "confirm")
    check(out["succeeded"] == 1, "seed-ui 确认失败")
    # 给 A（有镜头）也产一条证据：clue 补录 UI 需要可选镜头
    rule_a = jreq("POST", "/api/legacy-usage-rules", {
        "name": f"{PREFIX}-A标记-{tag}",
        "match_target": "filename",
        "match_operator": "contains",
        "pattern": f"{PREFIX}-a-{tag}",
        "source_directory_id": sd_id,
    }, expect=(201,))
    done = run_import_and_wait(
        {"source_directory_id": sd_id, "rule_ids": [rule_a["id"]]}
    )
    check(done["created_evidence_count"] == 1, f"A 证据未产生: {done}")
    print("PR_D_UI_SEED_OK")


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
        ["docker", "compose", "exec", "-T", "api", "sh", "-c",
         f"rm -rf /app/uploads/{PREFIX}* 2>/dev/null; true"],
        capture_output=True, check=False,
    )
    print("PR_D_CLEANUP_OK")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--mode", choices=["full", "check-persist", "seed-ui", "cleanup"], default="full"
    )
    args = parser.parse_args()
    if args.mode == "full":
        run_full()
    elif args.mode == "check-persist":
        run_check_persist()
    elif args.mode == "seed-ui":
        run_seed_ui()
    else:
        run_cleanup()


if __name__ == "__main__":
    main()
