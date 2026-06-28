#!/usr/bin/env python3
"""PR-05 Gate A 脚本匹配端到端（docker-e2e 用；FakeProvider + Fake Script Parser）。

验证真实 API + 数据库 + 重启持久化，**不使用真实 MiMo、不读取真实脚本/视频**：
创建脚本 → 内容哈希幂等 → 拆段（fake，确定性）→ 段落编辑乐观锁（lock_version 递增 + 409）→
段落重排 → 候选表保持为空（Gate A 不伪造候选）→ 重启后 project/segments/顺序/lock_version 仍在。

仅打印计数/状态标志，**不输出脚本全文/密钥/Endpoint**。

用法：
    python scripts/ci_script_gate_a_e2e.py --mode full
    python scripts/ci_script_gate_a_e2e.py --mode check-persist
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

NAME = "gate-a-e2e-script"
# 多段、含痛点/卖点/引导结构；纯合成文案，无真实产品/客户信息
SCRIPT = (
    "痛点开场：出门旅行最怕吹风机难用。\n\n"
    "产品卖点：轻便手持，巴掌大小，不超过5秒展示。\n\n"
    "使用结果：洗完头几分钟吹到八成干。\n\n"
    "下单引导：点下方链接带走一台。"
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
        with urllib.request.urlopen(req, timeout=30) as r:  # noqa: S310
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


def _candidate_count(project_id: int) -> int:
    """本脚本项目的候选数（Gate B 会为其它脚本写候选，故 Gate A 断言须按项目限定）。"""
    return _int(
        "select count(*) from script_shot_candidate c "
        "join script_segment s on c.script_segment_id = s.id "
        f"where s.script_project_id = {int(project_id)}"
    )


def run_full() -> None:
    # 1. 创建 + 哈希幂等
    p1, c1 = jreq("POST", "/api/scripts", {"name": NAME, "raw_script": SCRIPT})
    assert c1 == 201, c1
    assert p1["status"] == "draft" and p1["parse_status"] == "pending", p1
    p2, _ = jreq("POST", "/api/scripts", {"name": "other-name", "raw_script": SCRIPT})
    assert p2["id"] == p1["id"], "相同内容必须幂等复用同一项目"
    sid = p1["id"]
    print(f"  created+idempotent script id={sid}")

    # 2. 拆段（fake）
    detail, _ = jreq("POST", f"/api/scripts/{sid}/parse", {"parser": "fake"})
    assert detail["parse_status"] == "ok", detail
    assert detail["status"] == "parsed", detail
    assert detail["parser_provider"] == "fake", detail
    segs = detail["segments"]
    n = len(segs)
    assert n >= 3, f"段落数应≥3，实际 {n}"
    assert [s["order_index"] for s in segs] == list(range(n)), "order_index 必须连续 0..n-1"
    print(f"  parsed segments={n}")

    # 3. 段落编辑乐观锁
    seg0 = segs[0]
    edited, _ = jreq(
        "PATCH",
        f"/api/scripts/{sid}/segments/{seg0['id']}",
        {"lock_version": seg0["lock_version"], "visual_requirement": "室内手持产品特写"},
    )
    assert edited["lock_version"] == seg0["lock_version"] + 1, "lock_version 必须递增"
    assert edited["candidates_stale"] is True, "需求变更应标记候选过期"
    conflict, code = jreq(
        "PATCH",
        f"/api/scripts/{sid}/segments/{seg0['id']}",
        {"lock_version": seg0["lock_version"], "visual_requirement": "x"},
        expect=(200, 409),
    )
    assert code == 409, "旧 lock_version 必须 409"
    print("  optimistic lock OK (incremented + 409 on stale)")

    # 4. 重排（逆序）
    ids = [s["id"] for s in segs]
    rev, _ = jreq("POST", f"/api/scripts/{sid}/segments/reorder", {"segment_ids": list(reversed(ids))})
    assert [s["id"] for s in rev["segments"]] == list(reversed(ids)), "重排顺序必须生效"
    assert [s["order_index"] for s in rev["segments"]] == list(range(n)), "重排后 order 连续"
    print("  reorder OK")

    # 5. 本脚本候选表保持为空（Gate A 不伪造候选；按本项目限定，避免与 Gate B 其它脚本的候选混淆）
    cand = _candidate_count(sid)
    assert cand == 0, f"Gate A 不应有候选，实际 {cand}"
    print(f"  candidate table empty for this script ({cand})")

    print("SCRIPT_GATE_A_E2E_OK")


def run_check_persist() -> None:
    sid = _find_project_id()
    assert sid is not None, "重启后未找到脚本项目"
    detail, _ = jreq("GET", f"/api/scripts/{sid}")
    assert detail["status"] == "parsed", detail
    segs = detail["segments"]
    n = len(segs)
    assert n >= 3, f"重启后段落丢失，实际 {n}"
    assert [s["order_index"] for s in segs] == list(range(n)), "重启后 order 必须仍连续"
    assert any(s["lock_version"] >= 1 for s in segs), "重启后编辑过的 lock_version 必须仍在"
    cand = _candidate_count(sid)
    assert cand == 0, f"重启后本脚本候选表应仍为空，实际 {cand}"
    print(f"  persisted script id={sid} segments={n} (order+lock_version intact, candidates empty)")
    print("SCRIPT_GATE_A_PERSIST_OK")


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
