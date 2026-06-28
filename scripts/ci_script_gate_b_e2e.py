#!/usr/bin/env python3
"""PR-05 Gate B 脚本镜头匹配端到端（docker-e2e 用；FakeProvider + FakeEmbedding）。

前置：同一 compose 栈已由 ci_pr02/ai/search E2E 播种了可检索镜头（合成 ci_demo.mp4）。
本脚本验证真实 API + 数据库 + export-worker + 重启持久化（不使用真实 MiMo/视频/脚本）：
创建脚本 → 拆段（fake）→ 全脚本匹配（generation=1）→ 选择 → 锁定 → 单段重匹配（generation=2）
→ 锁定不被全脚本重匹配覆盖 → 解锁 → 剪辑清单 → CSV 导出（export 队列）→ 校验 CSV →
重启后候选/锁定/导出仍在。

仅打印计数/状态标志，不输出脚本全文/密钥/Endpoint。

用法：
    python scripts/ci_script_gate_b_e2e.py --mode full
    python scripts/ci_script_gate_b_e2e.py --mode check-persist
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request

API = os.environ.get("API_BASE", "http://localhost:8000")
_PSQL = ["docker", "compose", "exec", "-T", "postgres", "psql", "-U", "clipmind",
         "-d", "clipmind", "-tAc"]

NAME = "gate-b-e2e-script"
# 多段合成文案（无真实产品/客户信息）；与 Gate A 同结构，确保 fake 拆段 >= 2 段
SCRIPT = (
    "开场画面：展示产品整体外观，时长不超过3秒。\n\n"
    "使用演示：手持操作，画面清晰。\n\n"
    "卖点强调：突出便携与轻巧。\n\n"
    "结尾引导：点击下方了解更多。"
)


def q(sql: str) -> str:
    out = subprocess.run([*_PSQL, sql], capture_output=True, text=True, timeout=30, check=False)
    if out.returncode != 0:
        print(f"psql 失败: {out.stderr.strip()}", file=sys.stderr)
        return ""
    return out.stdout.strip()


def _int(sql: str) -> int:
    try:
        return int(q(sql))
    except ValueError:
        return 0


def jreq(method: str, path: str, body=None, expect=(200, 201, 202)):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(
        f"{API}{path}", data=data, method=method, headers={"Content-Type": "application/json"}
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as r:  # noqa: S310
            code, raw = r.status, r.read()
    except urllib.error.HTTPError as e:
        code, raw = e.code, e.read()
    if code not in expect:
        raise SystemExit(f"{method} {path} -> {code}: {raw[:300]!r}")
    return (json.loads(raw) if raw else {}), code


def _find_project_id() -> int | None:
    page, _ = jreq("GET", "/api/scripts?page=1&page_size=100")
    for item in page.get("items", []):
        if item.get("name") == NAME:
            return item["id"]
    return None


def _setup_script() -> tuple[int, list[dict]]:
    p1, c1 = jreq("POST", "/api/scripts", {"name": NAME, "raw_script": SCRIPT})
    sid = p1["id"]
    detail, _ = jreq("POST", f"/api/scripts/{sid}/parse", {"parser": "fake"})
    assert detail["parse_status"] == "ok", detail
    segs = detail["segments"]
    assert len(segs) >= 2, f"需要 >=2 段，实际 {len(segs)}"
    return sid, segs


def run_full() -> None:
    sid, segs = _setup_script()
    print(f"  script id={sid} segments={len(segs)}")

    # 1. 全脚本匹配 → generation 1
    res, _ = jreq("POST", f"/api/scripts/{sid}/match", {"match_token": "e2e-1"})
    assert res["total_segments"] == len(segs), res
    assert res["completed_segments"], "应有已匹配段落"
    c0, _ = jreq("GET", f"/api/scripts/{sid}/segments/{segs[0]['id']}/candidates")
    assert c0["generation"] == 1, c0
    assert c0["candidate_count"] >= 1, f"段0应有候选: {c0}"
    print(f"  full match OK; seg0 gen={c0['generation']} candidates={c0['candidate_count']}")
    print("SCRIPT_MATCH_E2E_OK")

    # 2. 选择 + 锁定 + 单段重匹配 generation 2 + 锁定不被覆盖 + 解锁
    shot0 = c0["candidates"][0]["shot_id"]
    lv = c0["lock_version"]
    sel, _ = jreq("POST", f"/api/scripts/{sid}/segments/{segs[0]['id']}/select",
                  {"shot_id": shot0, "lock_version": lv})
    assert sel["selected_shot_id"] == shot0, sel
    lk, _ = jreq("POST", f"/api/scripts/{sid}/segments/{segs[0]['id']}/lock",
                 {"shot_id": shot0, "lock_version": sel["lock_version"]})
    assert lk["locked_shot_id"] == shot0, lk

    rematch, _ = jreq("POST", f"/api/scripts/{sid}/segments/{segs[0]['id']}/match", {})
    assert rematch["generation"] == 2, f"重匹配应为 generation 2: {rematch}"
    # 历史代次仍可查
    hist, _ = jreq("GET", f"/api/scripts/{sid}/segments/{segs[0]['id']}/candidates?generation=1")
    assert hist["generation"] == 1, hist

    full2, _ = jreq("POST", f"/api/scripts/{sid}/match", {})
    assert segs[0]["id"] in full2["skipped_locked_segments"], "锁定段应被跳过"
    cur, _ = jreq("GET", f"/api/scripts/{sid}/segments/{segs[0]['id']}/candidates")
    assert cur["locked_shot_id"] == shot0, "锁定不得被全脚本重匹配覆盖"

    # 第二段锁定并保留（供重启持久化校验）
    c1, _ = jreq("GET", f"/api/scripts/{sid}/segments/{segs[1]['id']}/candidates")
    if c1["candidate_count"] >= 1:
        shot1 = c1["candidates"][0]["shot_id"]
        jreq("POST", f"/api/scripts/{sid}/segments/{segs[1]['id']}/lock",
             {"shot_id": shot1, "lock_version": c1["lock_version"]})

    # 解锁第一段
    cur2, _ = jreq("GET", f"/api/scripts/{sid}/segments/{segs[0]['id']}/candidates")
    unlocked, _ = jreq("POST", f"/api/scripts/{sid}/segments/{segs[0]['id']}/unlock",
                       {"lock_version": cur2["lock_version"]})
    assert unlocked["locked_shot_id"] is None, "解锁后锁定应清空"
    print("  select/lock/rematch(gen2)/lock-protected/unlock OK")
    print("SCRIPT_LOCK_E2E_OK")

    # 3. 剪辑清单
    el, _ = jreq("GET", f"/api/scripts/{sid}/edit-list")
    assert el["summary"]["total_segments"] == len(segs), el["summary"]
    assert len(el["rows"]) == len(segs), "每段一行（含无匹配段）"
    print(f"  edit-list rows={len(el['rows'])} matched={el['summary']['matched_segments']}")
    print("SCRIPT_EDIT_LIST_E2E_OK")

    # 4. CSV 导出（export 队列 → export-worker）
    exp, code = jreq("POST", f"/api/scripts/{sid}/exports/csv", {}, expect=(202,))
    eid = exp["id"]
    assert exp["status"] == "queued", exp
    deadline = time.time() + 120
    status = exp["status"]
    while time.time() < deadline:
        st, _ = jreq("GET", f"/api/scripts/{sid}/exports/{eid}")
        status = st["status"]
        if status in ("completed", "failed"):
            break
        time.sleep(2)
    assert status == "completed", f"CSV 导出未完成: {status}"
    # 下载并校验 BOM + 表头
    req = urllib.request.Request(f"{API}/api/scripts/{sid}/exports/{eid}/download")
    with urllib.request.urlopen(req, timeout=30) as r:  # noqa: S310
        raw = r.read()
    assert raw[:3] == b"\xef\xbb\xbf", "CSV 必须含 UTF-8 BOM"
    text = raw[3:].decode("utf-8")
    assert "段落序号" in text.splitlines()[0], "CSV 表头缺失"
    print(f"  csv export id={eid} bytes={len(raw)} rows~{text.count(chr(10))}")
    print("SCRIPT_CSV_E2E_OK")

    # DB 级基线（不以 HTTP 自报为准）
    cand = _int("select count(*) from script_shot_candidate")
    locked = _int("select count(*) from script_segment where locked_shot_id is not null")
    exports = _int("select count(*) from script_export where status='completed'")
    print(f"  DB baseline candidates={cand} locked_segments={locked} completed_exports={exports}")
    assert cand >= 1 and exports >= 1, "候选/导出未持久化"


def run_check_persist() -> None:
    sid = _find_project_id()
    assert sid is not None, "重启后未找到脚本项目"
    detail, _ = jreq("GET", f"/api/scripts/{sid}")
    assert detail["status"] == "parsed", detail
    segs = detail["segments"]
    # 候选持久化
    c0, _ = jreq("GET", f"/api/scripts/{sid}/segments/{segs[0]['id']}/candidates")
    assert c0["current_generation"] >= 2, f"重启后代次应保留: {c0['current_generation']}"
    # 第二段锁定持久化
    locked = _int("select count(*) from script_segment where locked_shot_id is not null")
    cand = _int("select count(*) from script_shot_candidate")
    exports = _int("select count(*) from script_export where status='completed'")
    assert locked >= 1, "重启后锁定段应仍在"
    assert cand >= 1, "重启后候选应仍在"
    assert exports >= 1, "重启后已完成导出应仍在"
    print(f"  persisted script id={sid} candidates={cand} locked={locked} exports={exports}")
    print("SCRIPT_GATE_B_PERSIST_OK")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", choices=["full", "check-persist"], required=True)
    args = ap.parse_args()
    if args.mode == "full":
        run_full()
    else:
        run_check_persist()


if __name__ == "__main__":
    main()
