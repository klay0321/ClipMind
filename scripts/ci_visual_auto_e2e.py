"""VIS-AUTO 端到端（fake provider，栈内）：自动视觉候选全链。

前置：VISUAL_EMBEDDING_PROVIDER=fake + VISUAL_AUTO_CANDIDATES=true +
AUTO 链开（与 AAP 同一开关窗口）。链路：参考图上传（钩子索引）→ 图片素材
upload → 扫描/海报 → 视觉嵌入 → 自动候选 → suggestions 出 visual →
dismiss 不复活 → fake 确认守卫 422。

标志：VISAUTO_CANDIDATE_OK / VISAUTO_DISMISS_OK / VISAUTO_NO_RESURRECT_OK /
VISAUTO_FAKE_GUARD_OK / VISAUTO_API_E2E_OK；check-persist 出
VISAUTO_PERSIST_OK。
"""

from __future__ import annotations

import json
import struct
import subprocess
import sys
import time
import urllib.error
import urllib.request
import uuid
import zlib

API = "http://localhost:8000"
PREFIX = "VAE2E"
TOKEN = "vae2e-family-token"
_PSQL = [
    "docker", "compose", "exec", "-T", "postgres",
    "psql", "-U", "clipmind", "-d", "clipmind", "-t", "-A", "-c",
]


def _req(method, path, body=None, *, raw=None, content_type="application/json"):
    url = f"{API}{path}"
    data = raw if raw is not None else (
        json.dumps(body).encode() if body is not None else None
    )
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
    def chunk(t, d):
        c = struct.pack(">I", len(d)) + t + d
        return c + struct.pack(">I", zlib.crc32(t + d) & 0xFFFFFFFF)
    return (b"\x89PNG\r\n\x1a\n"
            + chunk(b"IHDR", struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(b"\x00" + bytes((r, g, b))))
            + chunk(b"IEND", b"") + f"FAKE:{token}:{salt}".encode())


def upload_ref(family_id, token, angle):
    png = make_png(200, 30, 30, token, salt=angle)
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
    return rid


def upload_asset_image(token):
    content = make_png(90, 90, 90, token, salt=f"asset-{uuid.uuid4().hex[:6]}")
    name = f"{PREFIX.lower()}-{uuid.uuid4().hex[:8]}.png"
    boundary = uuid.uuid4().hex
    body = (
        f"--{boundary}\r\nContent-Disposition: form-data; name=\"file\"; "
        f"filename=\"{name}\"\r\nContent-Type: image/png\r\n\r\n"
    ).encode() + content + f"\r\n--{boundary}--\r\n".encode()
    res = jreq("POST", "/api/uploads", raw=body,
               content_type=f"multipart/form-data; boundary={boundary}", expect=(202,))
    return int(res["source_directory_id"]), name


def wait_asset(name, deadline_s=300):
    deadline = time.time() + deadline_s
    while time.time() < deadline:
        aid = psql(
            "SELECT id FROM asset WHERE filename="
            f"'{name}' ORDER BY id DESC LIMIT 1"
        )
        if aid:
            return int(aid)
        time.sleep(3)
    print(f"E2E FAIL: 素材 {name} 未在 {deadline_s}s 内出现", file=sys.stderr)
    sys.exit(1)


def wait_visual_suggestion(asset_id, *, present=True, deadline_s=240):
    deadline = time.time() + deadline_s
    last = []
    while time.time() < deadline:
        data = jreq(
            "GET",
            f"/api/product-media/suggestions?target_type=asset&target_id={asset_id}",
        )
        last = [s for s in data if s.get("suggestion_type") == "visual"]
        if bool(last) == present:
            return last
        time.sleep(3)
    # 失败诊断：嵌入/候选/参考向量状态（无敏感内容）
    diag = psql(
        "SELECT status, source_sha256 IS NOT NULL, candidates_ref_revision IS NOT NULL "
        f"FROM visual_media_embedding WHERE target_type='asset' AND target_id={asset_id}"
    )
    refs = psql(
        "SELECT count(*) FROM visual_media_embedding "
        "WHERE target_type='reference' AND status='completed'"
    )
    cands = psql(
        "SELECT count(*) FROM visual_product_candidate "
        f"WHERE target_type='asset' AND target_id={asset_id}"
    )
    print(
        f"E2E FAIL: asset {asset_id} 视觉候选 present={present} 未在 "
        f"{deadline_s}s 内满足（当前 {last}；emb=[{diag}] ref_emb={refs} "
        f"cand_rows={cands}）",
        file=sys.stderr,
    )
    sys.exit(1)


def wait_asset_embedding(asset_id, deadline_s=240):
    """等真实自动链算得该素材的视觉嵌入（证明 海报→钩子→索引 链路通）。"""
    deadline = time.time() + deadline_s
    rescan_at = 0.0
    sd_id = psql(f"SELECT source_directory_id FROM asset WHERE id={asset_id}")
    while time.time() < deadline:
        row = psql(
            "SELECT status FROM visual_media_embedding "
            f"WHERE target_type='asset' AND target_id={asset_id} LIMIT 1"
        )
        if row == "completed":
            return
        if time.time() >= rescan_at:  # scan 尾 sweep 兜底（钩子丢失时）
            _req("POST", f"/api/source-directories/{sd_id}/scan")
            rescan_at = time.time() + 45
        time.sleep(3)
    print(f"E2E FAIL: asset {asset_id} 视觉嵌入未在 {deadline_s}s 内完成", file=sys.stderr)
    sys.exit(1)


def implant_marker_poster(asset_id):
    """把带族标记的 PNG 植入 data 卷并指为该素材海报。

    真实海报是 ffmpeg 转码副本，必然剥掉 fake 字节标记——fake E2E 只验
    管线（链路/决策/落库/守卫），视觉语义相似度由真实验收（local SigLIP）
    覆盖。植入后清 sha 与水位，触发重嵌入+候选重算。
    """
    import base64 as _b64

    png_b64 = _b64.b64encode(make_png(90, 90, 90, TOKEN, salt="implant")).decode()
    out = subprocess.run(
        ["docker", "compose", "exec", "-T", "api", "sh", "-c",
         f"mkdir -p /app/data/assets/{asset_id} && echo '{png_b64}' | base64 -d "
         f"> /app/data/assets/{asset_id}/vafake.png"],
        capture_output=True, text=True, check=False,
    )
    if out.returncode != 0:
        print(f"E2E FAIL: 植入标记海报失败: {out.stderr[:200]}", file=sys.stderr)
        sys.exit(1)
    psql(
        f"UPDATE asset SET poster_path='assets/{asset_id}/vafake.png' "
        f"WHERE id={asset_id}"
    )
    # 清 sha 强制重嵌入 + 清水位强制候选重算（sweep stale 路径）
    psql(
        "UPDATE visual_media_embedding SET source_sha256=NULL, "
        "candidates_ref_revision=NULL "
        f"WHERE target_type='asset' AND target_id={asset_id}"
    )


def run_full():
    # 1) approved 产品 + 2 张合格参考图（上传钩子自动排视觉索引）
    fam = jreq("POST", "/api/product-families", {
        "code": f"{PREFIX}-{uuid.uuid4().hex[:6]}", "name_zh": "视觉自动E2E产品",
    }, expect=(201,))
    fid = fam["id"]
    psql(f"UPDATE product_family SET status='active' WHERE id={fid}")
    psql(f"DELETE FROM product_onboarding_review WHERE family_id={fid}")
    psql(
        "INSERT INTO product_onboarding_review (family_id, status, created_at, updated_at)"
        f" VALUES ({fid}, 'approved', now(), now())"
    )
    upload_ref(fid, TOKEN, "front")
    upload_ref(fid, TOKEN, "left")

    # 2) 图片素材走全自动链（upload→扫描→海报→钩子→视觉嵌入）——链路证明
    _sd, name = upload_asset_image(TOKEN)
    asset_id = wait_asset(name)
    wait_asset_embedding(asset_id)
    print("VISAUTO_PIPELINE_OK")

    # 3) 植入带族标记的海报（真实海报经 ffmpeg 转码必剥字节标记；fake E2E
    #    只验管线与决策落库，视觉语义由真实验收覆盖）→ sweep 重算出候选
    implant_marker_poster(asset_id)
    sd_id = psql(f"SELECT source_directory_id FROM asset WHERE id={asset_id}")
    jreq("POST", f"/api/source-directories/{sd_id}/scan", expect=(200, 201, 202, 409))
    visual = wait_visual_suggestion(asset_id, present=True)
    top = visual[0]
    check(top["family_id"] == fid, f"候选产品错位: {top}")
    check((top.get("score") or 0) >= 0.5, f"候选分数异常: {top}")
    check(top.get("candidate_id"), f"候选缺 candidate_id: {top}")
    check(top.get("origin_on_confirm") == "visual_suggestion_confirmed",
          f"确认 origin 错误: {top}")
    print("VISAUTO_CANDIDATE_OK")

    # 4) fake 确认守卫：fake provider 的候选禁止落正式关系（422）
    status, data = _req("POST", "/api/product-media/links", {
        "target_type": "asset", "target_id": asset_id, "family_id": fid,
        "role": "related", "origin": "visual_suggestion_confirmed",
    })
    check(status == 422, f"fake 确认应 422，实际 {status}: {data}")
    print("VISAUTO_FAKE_GUARD_OK")

    # 5) dismiss → 候选从建议消失
    cid = top["candidate_id"]
    jreq("POST", f"/api/product-media/visual-candidates/{cid}/dismiss")
    wait_visual_suggestion(asset_id, present=False, deadline_s=30)
    print("VISAUTO_DISMISS_OK")

    # 6) 强制重算（清水位 + 触发 sweep）→ dismissed 组合不复活
    psql(
        "UPDATE visual_media_embedding SET candidates_ref_revision=NULL "
        f"WHERE target_type='asset' AND target_id={asset_id}"
    )
    sd_id = psql(
        f"SELECT source_directory_id FROM asset WHERE id={asset_id}"
    )
    jreq("POST", f"/api/source-directories/{sd_id}/scan", expect=(200, 201, 202, 409))
    deadline = time.time() + 180
    while time.time() < deadline:
        rev = psql(
            "SELECT candidates_ref_revision FROM visual_media_embedding "
            f"WHERE target_type='asset' AND target_id={asset_id}"
        )
        if rev:
            break
        time.sleep(3)
    check(rev, "候选水位未被 sweep 重算")
    pending = psql(
        "SELECT count(*) FROM visual_product_candidate "
        f"WHERE target_type='asset' AND target_id={asset_id} AND status='pending'"
    )
    dismissed = psql(
        "SELECT count(*) FROM visual_product_candidate "
        f"WHERE target_type='asset' AND target_id={asset_id} AND status='dismissed'"
    )
    check(pending == "0" and dismissed == "1",
          f"dismissed 组合复活（pending={pending}, dismissed={dismissed}）")
    print("VISAUTO_NO_RESURRECT_OK")

    print("VISAUTO_API_E2E_OK")


def run_check_persist():
    emb = psql("SELECT count(*) FROM visual_media_embedding WHERE status='completed'")
    dis = psql("SELECT count(*) FROM visual_product_candidate WHERE status='dismissed'")
    check(int(emb) >= 3, f"重启后视觉嵌入行缺失（{emb}）")  # 2 参考图 + 1 素材
    check(int(dis) >= 1, f"重启后 dismissed 候选丢失（{dis}）")
    print("VISAUTO_PERSIST_OK")


def main():
    mode = sys.argv[sys.argv.index("--mode") + 1] if "--mode" in sys.argv else "full"
    if mode == "full":
        run_full()
    elif mode == "check-persist":
        run_check_persist()
    else:
        print(f"未知 mode: {mode}", file=sys.stderr)
        sys.exit(2)


if __name__ == "__main__":
    main()
