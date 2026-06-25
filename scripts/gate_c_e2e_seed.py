#!/usr/bin/env python3
"""Gate C 截图/E2E 种子脚本（仅标准库，针对已 docker compose up 的运行栈）。

走真实 API 填充可视化数据：
源目录 → 扫描 → 镜头分析 → AI 分析(fake) → 建产品 → 一镜 confirm、一镜 modify(注入风险/产品)。
不含任何真实凭据或公司素材；源目录为容器内只读 /app/source。

用法：API_BASE=http://localhost:8000 python scripts/gate_c_e2e_seed.py
"""

from __future__ import annotations

import json
import os
import sys
import time
import urllib.error
import urllib.request

API = os.environ.get("API_BASE", "http://localhost:8000")


def _req(method, path, body=None):
    url = f"{API}{path}"
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(
        url, data=data, method=method, headers={"Content-Type": "application/json"}
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:  # noqa: S310
            raw = resp.read()
            return resp.status, json.loads(raw) if raw else {}
    except urllib.error.HTTPError as e:
        return e.code, {"_error": e.read().decode("utf-8", "replace")[:300]}


def jreq(method, path, body=None, expect=(200, 201, 202)):
    status, data = _req(method, path, body)
    if status not in expect:
        print(f"SEED FAIL: {method} {path} -> {status}: {data}", file=sys.stderr)
        sys.exit(1)
    return data


def poll(fn, ok, *, timeout=240, interval=3, desc=""):
    deadline = time.time() + timeout
    last = None
    while time.time() < deadline:
        last = fn()
        if ok(last):
            return last
        time.sleep(interval)
    print(f"SEED FAIL: 轮询超时（{desc}），最后：{last}", file=sys.stderr)
    sys.exit(1)


RICH = {
    "one_line": "人工修订：产品手持特写，画面含竞品 logo",
    "detailed": "人工审核修订示例（Gate C 演示）。",
    "product": {"name": "示例扫地机 X10", "model": "X10", "color": "白色", "state": "新品"},
    "scene": "室内",
    "action": "展示",
    "shot_type": "产品特写",
    "subject": "手持产品",
    "marketing_use": ["产品卖点", "开箱"],
    "selling_points": ["大吸力", "自清洁"],
    "visible_text": ["X10"],
    "logo_brand": ["示例品牌"],
    "quality_issues": [],
    "risk_flags": ["竞品 logo"],
    "confidence": 0.9,
    "needs_human_review": False,
    "search_keywords": ["扫地机", "特写"],
    "recommended_scenes": ["电商主图"],
}


def main():
    # 1) 源目录（幂等：复用已有 /app/source 目录，避免重复创建）+ 扫描
    dirs = jreq("GET", "/api/source-directories")
    existing = next((d for d in dirs if d["mount_path"] == "/app/source"), None)
    if existing:
        sd_id = existing["id"]
    else:
        sd = jreq("POST", "/api/source-directories", {
            "name": "gate-c-demo", "mount_path": "/app/source",
            "recursive": True, "include_extensions": ["mp4", "mov"],
        }, expect=(201, 200))
        sd_id = sd["id"]
    jreq("POST", f"/api/source-directories/{sd_id}/scan", expect=(202,))
    poll(lambda: jreq("GET", f"/api/source-directories/{sd_id}/status"),
         lambda s: s["scan_status"] in ("completed", "failed"), desc="扫描")
    print(f"[1] 源目录+扫描 OK sd={sd_id}")

    # 2) 找 ci_demo 素材
    assets = jreq("GET", "/api/assets?page=1&page_size=50")["items"]
    asset = next((a for a in assets if "ci_demo" in a["filename"]), None) or assets[0]
    aid = asset["id"]
    print(f"[2] 素材 id={aid} file={asset['filename']}")

    # 3) 镜头分析
    jreq("POST", f"/api/assets/{aid}/analyze-shots", expect=(202,))
    poll(lambda: jreq("GET", f"/api/assets/{aid}/shot-analysis"),
         lambda s: s.get("status") in ("completed", "failed"), desc="镜头分析")
    shots = jreq("GET", f"/api/assets/{aid}/shots")["items"]
    print(f"[3] 拆镜头 OK shots={len(shots)}")

    # 4) AI 分析（fake）
    jreq("POST", f"/api/assets/{aid}/analyze", expect=(202, 200))
    ai = poll(lambda: jreq("GET", f"/api/assets/{aid}/ai-analysis"),
              lambda s: s.get("status") in ("completed", "partial", "failed"), desc="AI 分析")
    print(f"[4] AI 分析 status={ai.get('status')} analyzed={ai.get('analyzed_total')}")

    # 5) 建产品（产品库页 + 候选/绑定）
    products = []
    for p in [
        {"brand": "示例品牌", "name": "示例扫地机 X10", "model": "X10", "sku": "SP-X10",
         "selling_points": ["大吸力", "自清洁", "静音"]},
        {"brand": "示例品牌", "name": "示例吸尘器 V5", "model": "V5", "sku": "SP-V5",
         "selling_points": ["轻量", "长续航"]},
        {"brand": "对比品牌", "name": "竞品扫地机 A1", "model": "A1", "sku": "CP-A1",
         "selling_points": ["低价"]},
    ]:
        products.append(jreq("POST", "/api/products", p, expect=(201, 200)))
    pid = products[0]["id"]
    print(f"[5] 建产品 OK ids={[p['id'] for p in products]}")

    # 6) 一镜 confirm（人工确认 AI 结果）
    if shots:
        sid0 = shots[0]["id"]
        eff = jreq("GET", f"/api/shots/{sid0}/effective-result")
        rv = jreq("GET", f"/api/shots/{sid0}/review")
        jreq("POST", f"/api/shots/{sid0}/review/confirm", {
            "lock_version": rv.get("lock_version", 0),
            "reviewer_label": "demo",
            "comment": "演示：确认 AI 结果",
            "confirmed_result": eff.get("result") or None,
        }, expect=(200,))
        print(f"[6] confirm 镜头 {sid0} OK")

    # 7) 另一镜 modify（注入风险/产品/营销 + 绑定产品）
    if len(shots) > 1:
        sid1 = shots[1]["id"]
        rv1 = jreq("GET", f"/api/shots/{sid1}/review")
        jreq("POST", f"/api/shots/{sid1}/review/modify", {
            "lock_version": rv1.get("lock_version", 0),
            "reviewer_label": "demo",
            "comment": "演示：修订并标注风险 + 绑定产品",
            "confirmed_result": RICH,
            "confirmed_product_id": pid,
        }, expect=(200,))
        print(f"[7] modify 镜头 {sid1} OK（风险/产品已注入，绑定产品 {pid}）")

    # 8) 汇总
    summary = jreq("GET", f"/api/assets/{aid}/review-summary")
    print(f"[8] 素材汇总：{json.dumps(summary, ensure_ascii=False)}")
    print(f"SEED_OK asset_id={aid} shots={len(shots)}")


if __name__ == "__main__":
    main()
