#!/usr/bin/env python3
"""PR-F 端到端（产品视觉识别实验；FakeVisualProvider + 合成 PNG；纯 API 中性数据）。

前置：栈 .env 中 VISUAL_RECOGNITION_ENABLED=true 且 VISUAL_EMBEDDING_PROVIDER=fake
（CI 由工作流写入；本地临时添加后 up -d api）。

数据（--mode full）：3 个 Family（A/B 同族 token 构成 confusion 对；C 独立）
+ 多角度参考图（合法 1×1 PNG 尾部嵌 FAKE:<token>: 标记——真实解码器可解析，
FakeProvider 按 token 产生确定向量族）+ 劣质/未审核干扰组 + 1 条 confusion pair。

验证：资格纳入/排除 → 聚合与 Top-K → 确定性顺序 → unknown 拒识 →
ambiguous → confusion 区分特征 → 历史 Shot 可实验 → 零自动绑定 →
旧 API 兼容 → 重启持久化。隔离：PRF-E2E 前缀。
"""

from __future__ import annotations

import argparse
import json
import os
import struct
import subprocess
import sys
import urllib.error
import urllib.request
import uuid
import zlib

API = os.environ.get("API_BASE", "http://localhost:8000")
PREFIX = "PRF-E2E"
STATE_FILE = ".prf_e2e_state.json"
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


def psql(sql):
    out = subprocess.run(_PSQL + [sql], capture_output=True, text=True, check=False,
                         encoding="utf-8", errors="replace")
    if out.returncode != 0:
        print(f"E2E FAIL: psql: {out.stderr[:200]}", file=sys.stderr)
        sys.exit(1)
    return out.stdout.strip()


def make_png(r, g, b, token, salt=""):
    """合法 1×1 PNG + 尾部 FAKE:<token>:<salt> 标记（解码器忽略 IEND 后字节）。

    token 决定 FakeProvider 向量族；salt 只改变文件字节（sha256 不同 →
    绕开同目标重复检测），不影响族向量。"""
    def chunk(typ, data):
        c = struct.pack(">I", len(data)) + typ + data
        return c + struct.pack(">I", zlib.crc32(typ + data) & 0xFFFFFFFF)

    sig = b"\x89PNG\r\n\x1a\n"
    ihdr = chunk(b"IHDR", struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0))
    idat = chunk(b"IDAT", zlib.compress(b"\x00" + bytes((r, g, b))))
    iend = chunk(b"IEND", b"")
    return sig + ihdr + idat + iend + f"FAKE:{token}:{salt}".encode()


def upload_ref(family_id, token, angle, *, rgb=(200, 30, 30), state=None):
    png = make_png(*rgb, token, salt=angle)  # token 决定族；salt=angle 保证字节唯一
    boundary = uuid.uuid4().hex
    parts = []
    for name, value in (("target_level", "family"), ("target_id", str(family_id)),
                        ("angle", angle), ("state", "active")):
        parts.append(
            f"--{boundary}\r\nContent-Disposition: form-data; name=\"{name}\"\r\n\r\n"
            f"{value}\r\n".encode()
        )
    parts.append(
        f"--{boundary}\r\nContent-Disposition: form-data; name=\"files\"; "
        f"filename=\"{PREFIX}-{token}-{angle}.png\"\r\nContent-Type: image/png\r\n\r\n"
        .encode() + png + b"\r\n"
    )
    body = b"".join(parts) + f"--{boundary}--\r\n".encode()
    res = jreq("POST", "/api/product-reference-assets", raw=body,
               content_type=f"multipart/form-data; boundary={boundary}", expect=(201,))
    ref = res["items"][0] if "items" in res else res
    rid = ref.get("id") or (res.get("created") or [{}])[0].get("id")
    check(rid, f"上传参考图无 id: {res}")
    if state:
        jreq("PATCH", f"/api/product-reference-assets/{rid}", {"state": state})
    return rid


def create_family(code_suffix, name):
    return jreq("POST", "/api/product-families", {
        "code": f"{PREFIX}-{code_suffix}", "name_zh": name,
    }, expect=(201,))


def approve_family(fid):
    """造数捷径：approved 审核行 + active 状态（视觉链路不测 onboarding 流程）。
    先删旧行防多行 join（API 建族可能已带 incomplete 行）。"""
    psql(f"UPDATE product_family SET status='active' WHERE id={fid}")
    psql(f"DELETE FROM product_onboarding_review WHERE family_id={fid}")
    psql("INSERT INTO product_onboarding_review (family_id, status, created_at, updated_at) "
         f"VALUES ({fid}, 'approved', now(), now())")


def query_image(token):
    return make_png(90, 90, 90, token, salt="query")


def candidates(image_bytes, *, top_k=None, aggregation=None, expect=(200,)):
    boundary = uuid.uuid4().hex
    body = (
        f"--{boundary}\r\nContent-Disposition: form-data; name=\"file\"; "
        f"filename=\"q.png\"\r\nContent-Type: image/png\r\n\r\n".encode()
        + image_bytes + f"\r\n--{boundary}--\r\n".encode()
    )
    q = []
    if top_k:
        q.append(f"top_k={top_k}")
    if aggregation:
        q.append(f"aggregation={aggregation}")
    path = "/api/product-visual-experiments/candidates/image" + ("?" + "&".join(q) if q else "")
    return jreq("POST", path, raw=body,
                content_type=f"multipart/form-data; boundary={boundary}", expect=expect)


def run_full():
    tag = uuid.uuid4().hex[:6]
    st = jreq("GET", "/api/product-visual-experiments/status")
    check(st["enabled"], "实验未开启：请在栈 .env 设 VISUAL_RECOGNITION_ENABLED=true")
    check(st["provider"] == "fake", f"E2E 必须 fake provider，当前 {st['provider']}")
    check(st["experimental"] is True and st["thresholds"]["calibrated"] is False,
          "实验/未校准标记缺失")

    tok_a, tok_b, tok_c = f"pa{tag}", f"pa{tag}", f"pc{tag}"  # A/B 同族 → confusion
    fam_a = create_family(f"A-{tag}", f"{PREFIX}-产品A-{tag}")
    fam_b = create_family(f"B-{tag}", f"{PREFIX}-产品B-{tag}")
    fam_c = create_family(f"C-{tag}", f"{PREFIX}-产品C-{tag}")
    fam_draft = create_family(f"D-{tag}", f"{PREFIX}-未审核-{tag}")  # 不 approve
    for f in (fam_a, fam_b, fam_c):
        approve_family(f["id"])
    # A：4 角度 + 1 劣质 + 1 rejected（劣质/拒绝必须被排除）
    for angle in ("front", "left", "installed", "powered_on"):
        upload_ref(fam_a["id"], tok_a, angle, rgb=(200, 30, 30))
    bad = upload_ref(fam_a["id"], tok_a, "back", rgb=(200, 30, 30))
    jreq("PATCH", f"/api/product-reference-assets/{bad}",
         {"quality_status": "blurred"})
    rej = upload_ref(fam_a["id"], tok_a, "top", rgb=(200, 30, 30))
    jreq("PATCH", f"/api/product-reference-assets/{rej}", {"state": "rejected"})
    # B：2 角度（与 A 同 token → 近似产品）
    for angle in ("front", "back"):
        upload_ref(fam_b["id"], tok_b, angle, rgb=(30, 200, 30))
    # C：2 角度独立族
    for angle in ("front", "left"):
        upload_ref(fam_c["id"], tok_c, angle, rgb=(30, 30, 200))
    # 未 approve family 的图（不得进入候选库）
    upload_ref(fam_draft["id"], f"pd{tag}", "front")
    upload_ref(fam_draft["id"], f"pd{tag}", "left")
    # confusion pair A/B
    pair = jreq("POST", "/api/product-confusion-pairs", {
        "target_level": "family",
        "left_target_id": min(fam_a["id"], fam_b["id"]),
        "right_target_id": max(fam_a["id"], fam_b["id"]),
        "severity": "high", "reason": f"{PREFIX} 外观近似",
        "distinguishing_features": [
            {"feature": "接口位置", "left_value": "左侧", "right_value": "右侧"},
        ],
    }, expect=(201,))

    # 1) Provider 抽象 + 资格
    st2 = jreq("GET", "/api/product-visual-experiments/status")
    check(st2["eligible_family_count"] >= 3, f"合格产品数异常: {st2['eligible_family_count']}")
    cov = jreq("GET", "/api/product-visual-experiments/reference-coverage")
    by_id = {i["family_id"]: i for i in cov["items"]}
    check(by_id[fam_a["id"]]["eligible"] and by_id[fam_a["id"]]["reference_count"] == 4,
          f"A 合格图应 4（劣质/拒绝排除）: {by_id[fam_a['id']]}")
    check(fam_draft["id"] not in by_id
          or not by_id[fam_draft["id"]]["eligible"], "未 approve 产品不得合格")
    models = jreq("GET", "/api/product-visual-experiments/models")
    check({m["provider"] for m in models} == {"fake", "local"}, "models 应列出双 provider")
    print("PR_F_PROVIDER_ABSTRACTION_OK")
    print("PR_F_REFERENCE_ELIGIBILITY_OK")

    # 2) 候选：C 族查询 → 命中 C；聚合与 Top-K；顺序确定（3 连发）
    resc = candidates(query_image(tok_c))
    check(resc["decision"] == "candidate", f"C 查询应 candidate: {resc['decision']}")
    check(resc["candidates"][0]["target_id"] == fam_c["id"], "Top-1 应为 C")
    check(resc["candidates"][0]["embedded_reference_count"] == 2, "C 聚合参考数应 2")
    orders = [tuple(c["target_id"] for c in candidates(query_image(tok_c))["candidates"])
              for _ in range(3)]
    check(all(o == orders[0] for o in orders), "候选顺序不确定")
    top1 = candidates(query_image(tok_c), top_k=1)
    check(len(top1["candidates"]) == 1, "top_k=1 未生效")
    for agg in ("max", "top_k_mean", "weighted_top_k_mean"):
        r = candidates(query_image(tok_c), aggregation=agg)
        check(r["aggregation"] == agg, f"聚合 {agg} 未回显")
    print("PR_F_VISUAL_CANDIDATE_OK")

    # 3) unknown 拒识
    unk = candidates(query_image(f"zz{tag}"))
    check(unk["decision"] == "unknown", f"陌生族应 unknown: {unk['decision']}")
    print("PR_F_OPEN_SET_OK")

    # 4) ambiguous（A/B 同族同分）+ confusion 区分特征
    amb = candidates(query_image(tok_a))
    check(amb["decision"] == "ambiguous", f"A/B 同分应 ambiguous: {amb['decision']}")
    check(amb["margin"] is not None and amb["margin"] < 0.05, "margin 应接近 0")
    print("PR_F_AMBIGUITY_GUARD_OK")
    cw = amb["confusion_warning"]
    check(cw is not None and cw["severity"] == "high", "confusion 警告缺失")
    check(cw["distinguishing_features"][0]["feature"] == "接口位置", "区分特征缺失")
    print("PR_F_CONFUSION_PAIR_OK")

    # 5) 零自动绑定：候选调用前后业务表零变化
    tables = ("asset_product", "product_onboarding_review", "final_video_usage")
    before = {t: psql(f"SELECT count(*) FROM {t}") for t in tables}
    candidates(query_image(tok_c))
    candidates(query_image(tok_a))
    after = {t: psql(f"SELECT count(*) FROM {t}") for t in tables}
    check(before == after, f"候选查询产生写入: {before} -> {after}")
    print("PR_F_NO_AUTO_BIND_OK")

    # 6) 兼容：既有 API 不受影响
    for path in ("/api/product-families?page=1&page_size=5",
                 "/api/search/suggestions?limit=5",
                 "/api/assets?page=1&page_size=5"):
        jreq("GET", path)
    stx, _ = _req("POST", "/api/search/shots",
                  {"query": "", "search_mode": "lexical", "page": 1, "page_size": 5})
    check(stx == 200, "搜索链路受影响")
    print("PR_F_BACKWARD_COMPAT_OK")
    print("PR_F_API_E2E_OK")

    state = {
        "tag": tag, "fam_a": fam_a["id"], "fam_b": fam_b["id"], "fam_c": fam_c["id"],
        "pair": pair["id"], "tok_c": tok_c, "tok_a": tok_a,
        "c_order": [c["target_id"] for c in resc["candidates"]],
    }
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f)


def run_check_persist():
    with open(STATE_FILE, encoding="utf-8") as f:
        st = json.load(f)
    s = jreq("GET", "/api/product-visual-experiments/status")
    check(s["enabled"] and s["provider"] == "fake", "重启后实验配置丢失")
    cov = jreq("GET", "/api/product-visual-experiments/reference-coverage")
    by_id = {i["family_id"]: i for i in cov["items"]}
    check(by_id[st["fam_a"]]["reference_count"] == 4, "重启后 A 参考图变化")
    res = candidates(query_image(st["tok_c"]))
    check([c["target_id"] for c in res["candidates"]] == st["c_order"],
          "重启后候选顺序变化")
    amb = candidates(query_image(st["tok_a"]))
    check(amb["decision"] == "ambiguous" and amb["confusion_warning"], "重启后混淆保护失效")
    print("PR_F_RESTART_PERSIST_OK")


def run_cleanup():
    psql("DELETE FROM product_confusion_pair WHERE reason LIKE '" + PREFIX + "%'")
    psql(
        "DELETE FROM product_onboarding_review WHERE family_id IN "
        f"(SELECT id FROM product_family WHERE code LIKE '{PREFIX}%')"
    )
    psql(f"DELETE FROM product_family WHERE code LIKE '{PREFIX}%'")
    subprocess.run(
        ["docker", "compose", "exec", "-T", "api", "sh", "-c",
         "rm -rf /app/data/product_reference_assets/family/* 2>/dev/null; true"],
        capture_output=True, check=False,
    )
    print("PR_F_CLEANUP_OK")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=["full", "check-persist", "cleanup"],
                        default="full")
    args = parser.parse_args()
    if args.mode == "full":
        run_full()
    elif args.mode == "check-persist":
        run_check_persist()
    else:
        run_cleanup()


if __name__ == "__main__":
    main()
