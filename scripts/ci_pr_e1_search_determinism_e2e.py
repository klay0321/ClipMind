#!/usr/bin/env python3
"""PR-E.1 端到端（检索顺序确定性；中性合成数据 + 20 连发逐位断言）。

--mode full：上传 1 素材（6+ 镜头）→ 拆镜头 → AI 分析 → 检索文档 →
造 1 条 confirmed usage（30 天前）。然后对 lexical / vector(semantic) /
hybrid / 四种 usage 模式分别连发 20 次断言 Shot ID 顺序逐位一致；
分页拼接 == 一次性 top_k；default parity（非并列相对序=分数序，且与显式
default 请求逐位一致）。--mode check-persist：重启后同请求顺序仍一致。

真实栈（mimo parser）依赖 PR-E.1 的解析缓存达成确定；CI（rulebased/fake）
本身确定——两种环境同一断言。隔离：PRE1-E2E 前缀 + created_from/to 时间窗。
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
from datetime import UTC, datetime, timedelta

API = os.environ.get("API_BASE", "http://localhost:8000")
PREFIX = "PRE1-E2E"
STATE_FILE = ".pre1_e2e_state.json"
REPEAT = 20
QUERY = "确定性基准查询"  # 中性固定词：召回靠向量近邻/词法，无需命中语义
_PSQL = [
    "docker", "compose", "exec", "-T", "postgres",
    "psql", "-U", "clipmind", "-d", "clipmind", "-tAc",
]


def _req(method, path, body=None, *, raw=None, content_type="application/json"):
    url = f"{API}{path}"
    data = raw if raw is not None else (json.dumps(body).encode() if body is not None else None)
    req = urllib.request.Request(url, data=data, method=method,
                                 headers={"Content-Type": content_type})
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:  # noqa: S310
            payload = resp.read()
            return resp.status, json.loads(payload) if payload else {}
    except urllib.error.HTTPError as e:
        return e.code, {"_error": e.read().decode("utf-8", "replace")[:300]}


def jreq(method, path, body=None, expect=(200, 201, 202), **kw):
    status, data = _req(method, path, body, **kw)
    if status not in expect:
        print(f"E2E FAIL: {method} {path} -> {status}: {data}", file=sys.stderr)
        sys.exit(1)
    return data


def check(cond, msg):
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
    print(f"E2E FAIL: 轮询超时（{desc}）: {last}", file=sys.stderr)
    sys.exit(1)


def psql(sql):
    out = subprocess.run(_PSQL + [sql], capture_output=True, text=True, check=False,
                         encoding="utf-8", errors="replace")
    if out.returncode != 0:
        print(f"E2E FAIL: psql: {out.stderr[:200]}", file=sys.stderr)
        sys.exit(1)
    return out.stdout.strip()


def make_video(path, colors):
    inputs = []
    for c in colors:
        inputs += ["-f", "lavfi", "-i", f"color=c={c}:s=320x240:d=2.5:r=25"]
    n = len(colors)
    filt = "".join(f"[{i}:v]" for i in range(n)) + f"concat=n={n}:v=1:a=0,format=yuv420p[v]"
    out = subprocess.run(
        ["ffmpeg", "-y", *inputs, "-filter_complex", filt, "-map", "[v]",
         "-c:v", "libx264", "-preset", "ultrafast", path],
        capture_output=True, check=False,
    )
    check(out.returncode == 0, f"ffmpeg: {out.stderr[-200:]!r}")


def upload(local, name):
    boundary = uuid.uuid4().hex
    with open(local, "rb") as f:
        content = f.read()
    body = (
        f"--{boundary}\r\nContent-Disposition: form-data; name=\"file\"; "
        f"filename=\"{name}\"\r\nContent-Type: video/mp4\r\n\r\n"
    ).encode() + content + f"\r\n--{boundary}--\r\n".encode()
    res = jreq("POST", "/api/uploads", raw=body,
               content_type=f"multipart/form-data; boundary={boundary}", expect=(202,))
    return int(res["source_directory_id"]), str(res["filename"])


def wait_asset(name, sd_id):
    deadline = time.time() + 300
    rescan_at = time.time() + 45
    while time.time() < deadline:
        data = jreq("GET", f"/api/assets?page=1&page_size=50&q={urllib.parse.quote(name)}")
        for it in data.get("items", []):
            if it["filename"] == name and it["status"] == "indexed":
                return it
        if time.time() >= rescan_at:
            _req("POST", f"/api/source-directories/{sd_id}/scan")
            rescan_at = time.time() + 45
        time.sleep(3)
    print(f"E2E FAIL: 等待素材 {name} 超时", file=sys.stderr)
    sys.exit(1)


def search(body):
    return jreq("POST", "/api/search/shots", body)


def ids(res):
    return [i["shot_id"] for i in res["items"]]


def assert_repeat_stable(body, flag_name, times=REPEAT):
    first = search(body)
    for n in range(times - 1):
        cur = ids(search(body))
        check(cur == ids(first), f"{flag_name}: 第 {n + 2} 次顺序与首访不一致")
    return first


def run_full():
    tag = uuid.uuid4().hex[:6]
    created_from = (datetime.now(UTC) - timedelta(minutes=2)).isoformat()
    tmp = tempfile.mkdtemp(prefix="pre1_e2e_")
    name = f"{PREFIX}-a-{tag}.mp4"
    fv_name = f"{PREFIX}-f-{tag}.mp4"
    make_video(os.path.join(tmp, "a.mp4"),
               ["red", "blue", "yellow", "green", "gray", "white", f"#{tag}"])
    make_video(os.path.join(tmp, "f.mp4"), ["orange", f"#{tag}"])
    sd_id, name = upload(os.path.join(tmp, "a.mp4"), name)
    _, fv_name = upload(os.path.join(tmp, "f.mp4"), fv_name)
    poll(lambda: jreq("GET", f"/api/source-directories/{sd_id}/status"),
         lambda s: (s.get("latest_run") or {}).get("status") not in ("queued", "running"),
         desc="前序扫描")
    run = jreq("POST", f"/api/source-directories/{sd_id}/scan", expect=(202,))
    poll(lambda: jreq("GET", f"/api/source-directories/{sd_id}/status"),
         lambda s: (s.get("latest_run") or {}).get("id") == run["id"]
         and s["latest_run"]["status"] in ("completed", "failed"),
         desc="扫描")
    asset = wait_asset(name, sd_id)
    fv_asset = wait_asset(fv_name, sd_id)

    jreq("POST", f"/api/assets/{asset['id']}/analyze-shots", expect=(202,))
    poll(lambda: jreq("GET", f"/api/assets/{asset['id']}/shot-analysis"),
         lambda s: s.get("status") == "completed", desc="拆镜头")
    shots = jreq("GET", f"/api/assets/{asset['id']}/shots?page=1&page_size=50")["items"]
    check(len(shots) >= 6, f"镜头不足: {len(shots)}")
    jreq("POST", f"/api/assets/{asset['id']}/analyze", expect=(200, 202))
    res = poll(lambda: jreq("GET", f"/api/assets/{asset['id']}/ai-analysis"),
               lambda s: s.get("status") in ("completed", "partial", "failed"),
               desc="AI 分析", timeout=420)
    check(res["status"] in ("completed", "partial"), f"AI 分析失败: {res}")
    # AI partial 时个别镜头可能无文档：等 ≥6 个（排序断言只需足量同窗镜头），
    # 覆盖断言基于实际 searchable 集合
    sids = ",".join(str(s["id"]) for s in shots)
    poll(lambda: psql("select count(*) from shot_search_document "
                      f"where shot_id in ({sids}) and is_searchable"),
         lambda n: int(n or 0) >= 6, desc="检索文档", timeout=300)
    searchable = {
        int(x) for x in psql(
            "select shot_id from shot_search_document "
            f"where shot_id in ({sids}) and is_searchable"
        ).splitlines() if x.strip()
    }

    # 1 条 confirmed usage（30 天前）→ usage 模式有信号
    fv = jreq("POST", "/api/final-videos",
              {"asset_id": fv_asset["id"], "title": f"{PREFIX}-V-{tag}"}, expect=(201,))
    u = jreq("POST", f"/api/final-videos/{fv['id']}/usages",
             {"source_shot_id": shots[1]["id"]}, expect=(201,))
    jreq("POST", f"/api/final-video-usages/{u['id']}/confirm", {})
    psql("UPDATE final_video_usage SET confirmed_at = now() - interval '30 days' "
         f"WHERE id = {u['id']}")

    window = {"created_from": created_from,
              "created_to": datetime.now(UTC).isoformat()}

    # ---- lexical（空查询浏览：base 全 0，纯 tie-break 全序）----
    lex_body = {"query": "", "search_mode": "lexical", "page": 1, "page_size": 100, **window}
    lex_first = assert_repeat_stable(lex_body, "LEXICAL")
    check(searchable <= set(ids(lex_first)), "lexical 未覆盖本次可检索镜头")
    print("PR_E1_LEXICAL_ORDER_OK")

    # ---- vector（semantic 模式带词：查询向量单条嵌入确定）----
    sem_body = {"query": QUERY, "search_mode": "semantic",
                "page": 1, "page_size": 100, **window}
    sem_first = assert_repeat_stable(sem_body, "VECTOR")
    check(len(sem_first["items"]) > 0, "semantic 无结果")
    print("PR_E1_VECTOR_ORDER_OK")

    # ---- hybrid（带词：真实栈靠解析缓存 + 各通道 tie-break）----
    hyb_body = {"query": QUERY, "search_mode": "hybrid",
                "page": 1, "page_size": 100, **window}
    assert_repeat_stable(hyb_body, "HYBRID")
    print("PR_E1_HYBRID_ORDER_OK")

    # ---- 四种 usage 模式 ----
    for mode in ("default", "prefer_unused", "only_never_confirmed", "least_recently_used"):
        assert_repeat_stable({**lex_body, "usage_mode": mode}, f"USAGE:{mode}")
    print("PR_E1_USAGE_ORDER_OK")

    # ---- 分页稳定性：page1+page2 == 一次性 top_k，无重复无遗漏 ----
    p1 = ids(search({**lex_body, "page": 1, "page_size": 4}))
    p2 = ids(search({**lex_body, "page": 2, "page_size": 4}))
    top8 = ids(search({**lex_body, "page": 1, "page_size": 8}))
    check(p1 + p2 == top8, f"分页拼接 != 一次性 top_k: {p1}+{p2} vs {top8}")
    check(len(set(p1 + p2)) == len(p1 + p2), "分页出现重复")
    for mode in ("prefer_unused", "only_never_confirmed"):
        q1 = ids(search({**lex_body, "usage_mode": mode, "page": 1, "page_size": 4}))
        q2 = ids(search({**lex_body, "usage_mode": mode, "page": 2, "page_size": 4}))
        t8 = ids(search({**lex_body, "usage_mode": mode, "page": 1, "page_size": 8}))
        check(q1 + q2 == t8, f"{mode} 分页拼接不一致")
    print("PR_E1_PAGINATION_OK")

    # ---- default parity：非并列相对序 = 分数降序；与显式 default 逐位一致 ----
    scores = [i["score"] for i in lex_first["items"]]
    check(scores == sorted(scores, reverse=True), "default 非并列相对序违反分数降序")
    explicit = search({**lex_body, "usage_mode": "default", "usage_preset": "strong_unused"})
    check(ids(explicit) == ids(lex_first), "显式 default 与旧格式请求顺序不一致")
    check([i["score"] for i in explicit["items"]] == scores, "显式 default 分数不一致")
    print("PR_E1_DEFAULT_PARITY_OK")

    state = {
        "tag": tag, "window": window,
        "lex_order": ids(lex_first),
        "sem_order": ids(sem_first),
        "usage_order": ids(search({**lex_body, "usage_mode": "prefer_unused"})),
        "query": QUERY,
    }
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f)
    print("PR_E1_API_E2E_OK")


def run_check_persist():
    with open(STATE_FILE, encoding="utf-8") as f:
        st = json.load(f)
    lex_body = {"query": "", "search_mode": "lexical", "page": 1, "page_size": 100,
                **st["window"]}
    check(ids(search(lex_body)) == st["lex_order"], "重启后 lexical 顺序变化")
    sem_body = {"query": st["query"], "search_mode": "semantic",
                "page": 1, "page_size": 100, **st["window"]}
    check(ids(search(sem_body)) == st["sem_order"], "重启后 semantic 顺序变化")
    check(ids(search({**lex_body, "usage_mode": "prefer_unused"})) == st["usage_order"],
          "重启后 usage 排序变化")
    print("PR_E1_RESTART_DETERMINISM_OK")


def run_cleanup():
    psql(
        "DELETE FROM final_video_usage WHERE source_asset_id IN "
        f"(SELECT id FROM asset WHERE filename LIKE '{PREFIX}%')"
    )
    psql(f"DELETE FROM final_video WHERE title LIKE '{PREFIX}%'")
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
    print("PR_E1_CLEANUP_OK")


def main():
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
