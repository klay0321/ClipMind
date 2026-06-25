#!/usr/bin/env python3
"""PR-03B Docker AI 全链路端到端断言脚本（仅标准库，供 CI docker-e2e 使用）。

针对已 `docker compose up`（AI_PROVIDER=fake）的运行栈，通过真实 API 走通并断言**真正落库**：
AI 分析 → 轮询 completed → 有效结果 → 人工 confirm → review_state/review_event →
素材审核汇总 → projection-first 筛选命中 → 重启后仍存在。

**不**以 Celery task 自报成功为通过依据：所有断言都重新查询 API（投影/审核/汇总），
并由 CI 在重启 api+ai-worker 后再跑 --mode check-persist 验证持久化。

不含任何真实凭据；CI 必须用 AI_PROVIDER=fake，绝不在 Actions 注入真实 Key。

用法：
  API_BASE=http://localhost:8000 python scripts/ci_ai_e2e.py --mode full
  API_BASE=http://localhost:8000 python scripts/ci_ai_e2e.py --mode check-persist
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

API = os.environ.get("API_BASE", "http://localhost:8000")


def _req(method, path, body=None, headers=None):
    url = f"{API}{path}"
    data = json.dumps(body).encode() if body is not None else None
    h = {"Content-Type": "application/json"}
    if headers:
        h.update(headers)
    req = urllib.request.Request(url, data=data, method=method, headers=h)
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:  # noqa: S310
            raw = resp.read()
            return resp.status, json.loads(raw) if raw else {}
    except urllib.error.HTTPError as e:
        return e.code, {"_error": e.read().decode("utf-8", "replace")[:300]}


def jreq(method, path, body=None, expect=(200, 201, 202)):
    status, data = _req(method, path, body)
    if status not in expect:
        fail(f"{method} {path} -> {status}, 期望 {expect}: {data}")
    return data


def fail(msg):
    print(f"AI_E2E FAIL: {msg}", file=sys.stderr)
    sys.exit(1)


def poll(fn, ok, *, timeout=300, interval=3, desc=""):
    deadline = time.time() + timeout
    last = None
    while time.time() < deadline:
        last = fn()
        if ok(last):
            return last
        time.sleep(interval)
    fail(f"轮询超时（{desc}），最后状态：{last}")


def _asset_with_shots():
    assets = jreq("GET", "/api/assets?page=1&page_size=50")["items"]
    cand = [a for a in assets if a.get("shot_count", 0) > 0]
    if not cand:
        fail(f"无带镜头的素材：{[(a['id'], a.get('shot_count')) for a in assets]}")
    # 优先合成测试素材 ci_demo（含真实关键帧；CI 中是唯一素材）
    for a in cand:
        if "ci_demo" in a.get("filename", ""):
            return a
    return cand[0]


def full():
    asset = _asset_with_shots()
    aid = asset["id"]
    print(f"[1] 选用素材 id={aid} shots={asset['shot_count']}")

    # 2) 发起 AI 分析（fake）并轮询 completed
    jreq("POST", f"/api/assets/{aid}/analyze", expect=(200, 202))
    ai = poll(
        lambda: jreq("GET", f"/api/assets/{aid}/ai-analysis"),
        lambda s: s.get("status") in ("completed", "partial", "failed"),
        desc="AI 分析",
    )
    if ai["status"] not in ("completed", "partial"):
        fail(f"AI 分析未成功：{ai}")
    if (ai.get("analyzed_total") or 0) < 1:
        fail(f"analyzed_total 应 >0：{ai}")
    print(f"[2] AI 分析 status={ai['status']} analyzed_total={ai['analyzed_total']} provider={ai.get('provider')}")

    # 3) 取一个未审核镜头，确认有效结果（AI 来源）
    shots = jreq("GET", f"/api/assets/{aid}/shots")["items"]
    sid, rv = None, None
    for sh in shots:
        r = jreq("GET", f"/api/shots/{sh['id']}/review")
        if r["review_status"] in ("unreviewed", "pending_review"):
            sid, rv = sh["id"], r
            break
    if sid is None:  # 容错：已全部审核（本地重复跑），仍验证只读路径
        sid = shots[0]["id"]
    eff = jreq("GET", f"/api/shots/{sid}/effective-result")
    if not eff.get("result"):
        fail(f"effective-result 无结果：{eff}")
    scene = (eff["result"] or {}).get("scene")
    print(f"[3] 有效结果 shot={sid} source={eff['source']} ai_status={eff.get('ai_status')} scene={scene}")

    # 4) 人工 confirm（DB 级乐观锁）；若该镜头已审核则跳过写操作
    if rv is not None:
        jreq("POST", f"/api/shots/{sid}/review/confirm", {
            "lock_version": rv.get("lock_version", 0),
            "reviewer_label": "ci",
            "comment": "ci confirm",
            "confirmed_result": eff.get("result"),
        }, expect=(200,))
        rv2 = jreq("GET", f"/api/shots/{sid}/review")
        if rv2["review_status"] != "confirmed":
            fail(f"confirm 后状态应 confirmed：{rv2}")
        events = jreq("GET", f"/api/shots/{sid}/review-events")
        if not events:
            fail("review-events 应 >=1")
        print(f"[4] confirm OK status={rv2['review_status']} events={len(events)}")
    else:
        print("[4] 镜头已审核，跳过 confirm（验证既有审核态）")

    # 5) 素材汇总：confirmed 计数
    summary = jreq("GET", f"/api/assets/{aid}/review-summary")
    if (summary.get("confirmed_count") or 0) < 1:
        fail(f"汇总 confirmed_count 应 >=1：{summary}")
    print(f"[5] 汇总 confirmed={summary['confirmed_count']} total={summary['total_shots']} ai_overall={summary['ai_overall_status']}")

    # 6) projection-first 筛选命中：has_ai_result + scene 标签
    s1 = jreq("GET", f"/api/shot-search?asset_id={aid}&has_ai_result=true&page=1&page_size=24")
    if s1["total"] < 1:
        fail(f"has_ai_result 筛选应命中：{s1['total']}")
    if scene:
        sc = urllib.parse.quote(scene)
        s2 = jreq("GET", f"/api/shot-search?asset_id={aid}&scene={sc}&page=1&page_size=24")
        if s2["total"] < 1:
            fail(f"scene='{scene}' 投影筛选应命中（确认后 human 投影）：{s2['total']}")
        print(f"[6] 筛选 has_ai_result={s1['total']} scene='{scene}'={s2['total']}")
    else:
        print(f"[6] 筛选 has_ai_result={s1['total']}（无 scene 跳过标签筛选）")

    print(f"AI_E2E_OK asset_id={aid} shot_id={sid}")


def check_persist():
    # 重启后：AI run 仍 completed、汇总 confirmed 仍在、筛选仍命中
    assets = jreq("GET", "/api/assets?page=1&page_size=50")["items"]
    target = None
    for a in assets:
        if a.get("shot_count", 0) <= 0:
            continue
        ai = jreq("GET", f"/api/assets/{a['id']}/ai-analysis")
        sm = jreq("GET", f"/api/assets/{a['id']}/review-summary")
        if ai.get("status") in ("completed", "partial") and (sm.get("confirmed_count") or 0) >= 1:
            target = (a["id"], ai, sm)
            break
    if not target:
        fail("重启后找不到 AI 已分析且含 confirmed 的素材（持久化失败）")
    aid, ai, sm = target
    s1 = jreq("GET", f"/api/shot-search?asset_id={aid}&has_ai_result=true&page=1&page_size=24")
    if s1["total"] < 1:
        fail(f"重启后 has_ai_result 筛选应仍命中：{s1['total']}")
    print(f"[persist] asset={aid} ai_status={ai['status']} confirmed={sm['confirmed_count']} has_ai_result={s1['total']}")
    print("AI_E2E_PERSIST_OK")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", choices=["full", "check-persist"], default="full")
    args = ap.parse_args()
    if args.mode == "full":
        full()
    else:
        check_persist()


if __name__ == "__main__":
    main()
