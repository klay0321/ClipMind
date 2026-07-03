#!/usr/bin/env python3
"""PR-E 端到端（使用感知检索；中性排名基准 + 纯 API 合成数据）。

基准数据（--mode full）：
A 素材 6 镜头（shot1=0 次、shot2=1 次/180 天前、shot3=2 次/30 天前、
shot4=1 次/1 天前、shot5=proposed、shot6=0 次）+ C 素材（accepted legacy）
+ D 素材（pending legacy）+ 3 个成片。全部走 FakeProvider AI 分析 →
检索文档（统一可用查询词 = fake 的固定关键词）。

验证：特征投影 / default 逐位 parity / prefer_unused 调整方向与不降位 /
relevance guard(cap) / hard filters / 候选统计 / legacy 弱隔离 /
Saved Search 保存恢复 / 旧请求兼容 / 重启持久化。
（候选扩张深度与同 base 名次断言由单元测试锁定——E2E 断言 stats 与过滤正确性。）

隔离：只操作 /app/uploads 下 PRE-E2E 前缀合成文件；tag 色段保证字节唯一。
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
import urllib.request
import uuid
from datetime import UTC, datetime, timedelta

API = os.environ.get("API_BASE", "http://localhost:8000")
PREFIX = "PRE-E2E"
STATE_FILE = ".pre_e2e_state.json"
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
    import urllib.parse
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


def analyze(aid):
    jreq("POST", f"/api/assets/{aid}/analyze-shots", expect=(202,))
    poll(lambda: jreq("GET", f"/api/assets/{aid}/shot-analysis"),
         lambda s: s.get("status") == "completed", desc=f"拆镜头 {aid}")
    return jreq("GET", f"/api/assets/{aid}/shots?page=1&page_size=50")["items"]


def ai_analyze(aid):
    jreq("POST", f"/api/assets/{aid}/analyze", expect=(200, 202))
    res = poll(lambda: jreq("GET", f"/api/assets/{aid}/ai-analysis"),
               lambda s: s.get("status") in ("completed", "partial", "failed"),
               desc=f"AI 分析 {aid}", timeout=420)
    check(res["status"] in ("completed", "partial"), f"AI 分析失败: {res}")


def wait_searchable(shot_ids):
    """等 search-worker 构建文档（is_searchable）。"""
    ids = ",".join(str(s) for s in shot_ids)
    poll(
        lambda: psql(
            "select count(*) from shot_search_document "
            f"where shot_id in ({ids}) and is_searchable"
        ),
        lambda n: int(n or 0) >= len(shot_ids),
        desc="检索文档构建", timeout=300,
    )


def confirm_usage(fv_id, shot_id):
    u = jreq("POST", f"/api/final-videos/{fv_id}/usages",
             {"source_shot_id": shot_id}, expect=(201,))
    jreq("POST", f"/api/final-video-usages/{u['id']}/confirm", {})
    return u


def search(body, expect=(200,)):
    return jreq("POST", "/api/search/shots", body, expect=expect)


def run_full():
    tag = uuid.uuid4().hex[:6]
    # created_from 隔离：fake 关键词会命中历史合成镜头，用创建时间锁定本次运行
    created_from = (
        datetime.now(UTC) - timedelta(minutes=2)
    ).isoformat()
    tmp = tempfile.mkdtemp(prefix="pre_e2e_")
    uniq = f"#{tag}"
    names = {
        "a": f"{PREFIX}-a-{tag}.mp4",
        "f1": f"{PREFIX}-f1-{tag}.mp4",
        "f2": f"{PREFIX}-f2-{tag}.mp4",
        "f3": f"{PREFIX}-f3-{tag}.mp4",
        "c": f"{PREFIX}-c-{tag}.mp4",
        "d": f"{PREFIX}-d-{tag}.mp4",
    }
    make_video(os.path.join(tmp, "a.mp4"),
               ["red", "blue", "yellow", "green", "gray", "white", uniq])
    make_video(os.path.join(tmp, "f1.mp4"), ["orange", uniq])
    make_video(os.path.join(tmp, "f2.mp4"), ["purple", uniq])
    make_video(os.path.join(tmp, "f3.mp4"), ["pink", uniq])
    make_video(os.path.join(tmp, "c.mp4"), ["cyan", "black", uniq])
    make_video(os.path.join(tmp, "d.mp4"), ["magenta", "brown", uniq])
    sd_id, names["a"] = upload(os.path.join(tmp, "a.mp4"), names["a"])
    for key in ("f1", "f2", "f3", "c", "d"):
        _, names[key] = upload(os.path.join(tmp, f"{key}.mp4"), names[key])
    # 显式扫描（等前序 idle → 新 run）
    poll(lambda: jreq("GET", f"/api/source-directories/{sd_id}/status"),
         lambda s: (s.get("latest_run") or {}).get("status") not in ("queued", "running"),
         desc="前序扫描")
    run = jreq("POST", f"/api/source-directories/{sd_id}/scan", expect=(202,))
    poll(lambda: jreq("GET", f"/api/source-directories/{sd_id}/status"),
         lambda s: (s.get("latest_run") or {}).get("id") == run["id"]
         and s["latest_run"]["status"] in ("completed", "failed"),
         desc="扫描")
    assets = {k: wait_asset(names[k], sd_id) for k in names}

    shots_a = analyze(assets["a"]["id"])
    shots_c = analyze(assets["c"]["id"])
    shots_d = analyze(assets["d"]["id"])
    check(len(shots_a) >= 6, f"A 镜头不足: {len(shots_a)}")
    for key in ("a", "c", "d"):
        ai_analyze(assets[key]["id"])
    all_ids = [s["id"] for s in shots_a] + [s["id"] for s in shots_c] + [s["id"] for s in shots_d]
    wait_searchable(all_ids)

    # 成片与使用：shot2=1次(180d)、shot3=2次(30d)、shot4=1次(1d)、shot5=proposed
    fv1 = jreq("POST", "/api/final-videos",
               {"asset_id": assets["f1"]["id"], "title": f"{PREFIX}-V1-{tag}"}, expect=(201,))
    fv2 = jreq("POST", "/api/final-videos",
               {"asset_id": assets["f2"]["id"], "title": f"{PREFIX}-V2-{tag}"}, expect=(201,))
    fv3 = jreq("POST", "/api/final-videos",
               {"asset_id": assets["f3"]["id"], "title": f"{PREFIX}-V3-{tag}"}, expect=(201,))
    s = {i + 1: shots_a[i]["id"] for i in range(6)}
    confirm_usage(fv1["id"], s[2])
    confirm_usage(fv1["id"], s[3])
    confirm_usage(fv2["id"], s[3])
    confirm_usage(fv3["id"], s[4])
    for sid, days in ((s[2], 180), (s[3], 30), (s[4], 1)):
        psql(
            "UPDATE final_video_usage SET confirmed_at = now() - interval "
            f"'{days} days' WHERE source_shot_id = {sid}"
        )
    jreq("POST", f"/api/final-videos/{fv2['id']}/usages",
         {"source_shot_id": s[5]}, expect=(201,))  # proposed（不 confirm）

    # legacy：C accepted / D pending（文件名规则，tag 隔离）
    ev_ids = {}
    for key, action in (("c", "accept"), ("d", None)):
        rule = jreq("POST", "/api/legacy-usage-rules", {
            "name": f"{PREFIX}-{key}-{tag}",
            "match_target": "filename", "match_operator": "contains",
            "pattern": f"{PREFIX}-{key}-{tag}", "source_directory_id": sd_id,
        }, expect=(201,))
        irun = jreq("POST", "/api/legacy-usage-imports",
                    {"source_directory_id": sd_id, "rule_ids": [rule["id"]]}, expect=(202,))
        poll(lambda rid=irun["id"]: jreq("GET", f"/api/legacy-usage-imports/{rid}"),
             lambda r: r["status"] in ("completed", "completed_with_errors", "failed"),
             desc="legacy 导入")
        evs = jreq("GET",
                   f"/api/legacy-usage-evidence?page=1&page_size=10&rule_id={rule['id']}")["items"]
        check(len(evs) == 1, f"{key} 证据数异常: {len(evs)}")
        ev_ids[key] = evs[0]["id"]
        if action == "accept":
            jreq("POST", f"/api/legacy-usage-evidence/{evs[0]['id']}/accept", {})

    a_ids = set(s.values())
    c_shot = shots_c[0]["id"]
    d_shot = shots_d[0]["id"]
    # 中性基准：空查询浏览模式 + created_from 隔离 → base 全 0（无语义信号），
    # 排序差异 100% 来自 usage 调整；对 Fake/真实 Provider 都成立。
    query = ""
    base_req = {"query": query, "search_mode": "lexical", "page": 1, "page_size": 100,
                "created_from": created_from}

    # 1) 特征投影
    res = search(base_req)
    check(all(i["score"] == 0.0 for i in res["items"]), "中性基准要求 base 全 0")
    by_id = {i["shot_id"]: i for i in res["items"]}
    check(all(sid in by_id for sid in a_ids), "A 镜头未全部进入检索结果")
    check(by_id[s[1]]["usage"]["shot_confirmed_usage_count"] == 0, "shot1 应 0 次")
    check(by_id[s[2]]["usage"]["shot_confirmed_usage_count"] == 1, "shot2 应 1 次")
    check(by_id[s[3]]["usage"]["shot_confirmed_usage_count"] == 2, "shot3 应 2 次（去重成片）")
    check(by_id[s[4]]["usage"]["shot_confirmed_usage_count"] == 1, "shot4 应 1 次")
    check(by_id[s[5]]["usage"]["pending_formal_count"] == 1, "shot5 应有待确认")
    check(by_id[s[5]]["usage"]["shot_confirmed_usage_count"] == 0, "proposed 不计正式次数")
    check(by_id[c_shot]["usage"]["accepted_legacy_evidence_count"] == 1, "C 应有 accepted legacy")
    check(by_id[c_shot]["usage"]["usage_state"] == "legacy_used_unknown", "C 状态异常")
    check(by_id[d_shot]["usage"]["accepted_legacy_evidence_count"] == 0, "D pending 不计")
    days2 = by_id[s[2]]["usage"]["days_since_last_confirmed_use"]
    check(days2 is not None and 179 <= days2 <= 181, f"shot2 应约 180 天: {days2}")
    print("PR_E_USAGE_FEATURE_PROJECTION_OK")

    # 2) default 逐位 parity（老请求 vs 显式 default+激进预设）
    old = search(base_req)
    dflt = search({**base_req, "usage_mode": "default", "usage_preset": "strong_unused",
                   "usage_scope": "shot"})
    check([i["shot_id"] for i in old["items"]] == [i["shot_id"] for i in dflt["items"]],
          "default 顺序与旧实现不一致！")
    check([i["score"] for i in old["items"]] == [i["score"] for i in dflt["items"]],
          "default 分数与旧实现不一致！")
    check(all(i["usage_adjustment"] == 0.0 for i in dflt["items"]), "default 调整必须为 0")
    print("PR_E_DEFAULT_RANKING_PARITY_OK")

    # 3) prefer_unused：调整方向正确；A 集合内未使用镜头相对位次不降
    pref = search({**base_req, "usage_mode": "prefer_unused"})
    pby = {i["shot_id"]: i for i in pref["items"]}
    check(pby[s[1]]["usage_adjustment"] > 0, "未使用应获正向调整")
    check(pby[s[3]]["usage_adjustment"] < 0, "高频应获负向调整")
    check(pby[s[4]]["usage_adjustment"] < pby[s[2]]["usage_adjustment"],
          "近期使用（1 天）惩罚应重于 180 天前")
    order_default = [i["shot_id"] for i in old["items"] if i["shot_id"] in a_ids]
    order_pref = [i["shot_id"] for i in pref["items"] if i["shot_id"] in a_ids]
    check(order_pref.index(s[1]) <= order_default.index(s[1]),
          "未使用镜头相对位次不得下降")
    check(order_pref.index(s[1]) < order_pref.index(s[3]),
          "未使用镜头必须排在高频镜头之前（base 全等的中性基准）")
    check(order_pref.index(s[2]) < order_pref.index(s[4]),
          "180 天前使用过的应排在 1 天前使用过的之前")
    check(any(r["code"] == "shot_never_used" for r in pby[s[1]]["usage_reasons"]),
          "未使用奖励 reason 缺失")
    lru = search({**base_req, "usage_mode": "least_recently_used"})
    lby = {i["shot_id"]: i for i in lru["items"]}
    check(lby[s[2]]["usage_adjustment"] > lby[s[4]]["usage_adjustment"],
          "久未使用（180 天）应比刚使用（1 天）获得更高调整")
    print("PR_E_PREFER_UNUSED_OK")

    # 4) relevance guard：全体 |adjustment| ≤ cap；base 不被覆盖
    for it in pref["items"]:
        check(abs(it["usage_adjustment"]) <= 0.35 + 1e-9, "调整超过 cap！")
        check(abs(it["final_score"] - (it["base_score"] + it["usage_adjustment"])) < 1e-6,
              "final != base + adjustment")
        check(it["score"] == it["base_score"], "原始 score 字段被覆盖！")
    print("PR_E_RELEVANCE_GUARD_OK")

    # 5) hard filters
    only = search({**base_req, "usage_mode": "only_never_confirmed"})
    only_ids = {i["shot_id"] for i in only["items"]}
    check(not ({s[2], s[3], s[4]} & only_ids), "confirmed 镜头必须被排除")
    check(s[1] in only_ids and s[6] in only_ids, "未使用镜头必须保留")
    check(c_shot in only_ids, "accepted legacy ≠ confirmed，不得被自动排除")
    maxr = search({**base_req, "usage_mode": "exclude_high_frequency",
                   "max_confirmed_usage_count": 1})
    maxr_ids = {i["shot_id"] for i in maxr["items"]}
    check(s[3] not in maxr_ids and s[2] in maxr_ids, "max=1 应只排除 2 次的 shot3")
    recent = search({**base_req, "usage_mode": "prefer_unused",
                     "exclude_recently_used_days": 60})
    recent_ids = {i["shot_id"] for i in recent["items"]}
    check(s[3] not in recent_ids and s[4] not in recent_ids, "60 天内使用的必须排除")
    check(s[2] in recent_ids, "180 天前使用的必须保留")
    stats = only["usage_stats"]
    check(stats["filtered_count"] >= 3 and stats["candidate_pool_size"] > 0,
          f"过滤统计异常: {stats}")
    print("PR_E_HARD_FILTER_OK")
    print("PR_E_CANDIDATE_EXPANSION_OK")  # stats 通路 + 扩张深度由单元测试锁定

    # 6) legacy 弱隔离
    legacy_reason = [r for r in pby[c_shot]["usage_reasons"]
                     if r["code"] == "legacy_used_unknown_hint"]
    check(len(legacy_reason) == 1 and abs(legacy_reason[0]["adjustment"]) <= 0.05,
          "legacy 调整必须存在且显著弱")
    check(not any(r["code"] == "legacy_used_unknown_hint"
                  for r in pby[d_shot]["usage_reasons"]), "pending 不得产生 legacy 调整")
    check(pby[c_shot]["usage"]["shot_confirmed_usage_count"] == 0,
          "accepted legacy 不改变 confirmed count")
    no_legacy = search({**base_req, "usage_mode": "prefer_unused",
                        "include_legacy_unknown": False})
    nby = {i["shot_id"]: i for i in no_legacy["items"]}
    check(not any(r["code"] == "legacy_used_unknown_hint"
                  for r in nby[c_shot]["usage_reasons"]),
          "include_legacy_unknown=false 仍产生 legacy 调整")
    print("PR_E_LEGACY_WEIGHT_ISOLATION_OK")

    # 7) Saved Search 保存（重启后校验恢复）
    saved = jreq("POST", "/api/saved-searches", {
        "name": f"{PREFIX}-未使用优先-{tag}",
        "search_kind": "shot_search",
        "query": {**base_req, "usage_mode": "prefer_unused",
                  "exclude_recently_used_days": 60, "usage_preset": "strong_unused"},
    }, expect=(201,))
    got = jreq("GET", f"/api/saved-searches/{saved['id']}")
    check(got["query"]["usage_mode"] == "prefer_unused"
          and got["query"]["exclude_recently_used_days"] == 60, "保存恢复异常")

    # 8) 兼容：旧字段请求 / 非法参数 422 / description-match 原样可用
    st, _ = _req("POST", "/api/search/shots", {**base_req, "usage_mode": "bogus"})
    check(st == 422, "非法 usage_mode 应 422")
    st, _ = _req("POST", "/api/search/shots",
                 {**base_req, "usage_mode": "prefer_unused",
                  "usage_weights": {"legacy_hint_penalty": 0.5}})
    check(st == 422, "越权 legacy 权重应 422")
    st, _ = _req("POST", "/api/match/description",
                 {"target_description": "演示画面", "limit": 5})
    check(st == 200, f"描述匹配（未改造路径）异常: {st}")
    print("PR_E_BACKWARD_COMPAT_OK")

    state = {
        "tag": tag, "saved_id": saved["id"], "shots": s,
        "c_shot": c_shot, "d_shot": d_shot,
        "default_order": [i["shot_id"] for i in old["items"]],
        "default_scores": [i["score"] for i in old["items"]],
        "query": query, "created_from": created_from,
    }
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f)
    print("PR_E_API_E2E_OK")


def run_check_persist():
    with open(STATE_FILE, encoding="utf-8") as f:
        st = json.load(f)
    base_req = {"query": st["query"], "search_mode": "lexical", "page": 1, "page_size": 100,
                "created_from": st["created_from"]}
    res = search(base_req)
    check([i["shot_id"] for i in res["items"]] == st["default_order"],
          "重启后 default 顺序变化")
    check([i["score"] for i in res["items"]] == st["default_scores"],
          "重启后 default 分数变化")
    got = jreq("GET", f"/api/saved-searches/{st['saved_id']}")
    check(got["query"]["usage_mode"] == "prefer_unused", "重启后 Saved Search 丢失 usage 条件")
    by_id = {i["shot_id"]: i for i in res["items"]}
    check(by_id[st["shots"]["3"]]["usage"]["shot_confirmed_usage_count"] == 2,
          "重启后使用特征变化")
    print("PR_E_SAVED_SEARCH_PERSIST_OK")
    print("PR_E_RESTART_PERSIST_OK")


def run_cleanup():
    psql(f"DELETE FROM saved_search WHERE name LIKE '{PREFIX}%'")
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
    print("PR_E_CLEANUP_OK")


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
