#!/usr/bin/env python3
"""PR-04 Gate A 检索文档索引端到端（docker-e2e 用）。

Gate A 无搜索 API，故经 API 驱动审核 + ``docker compose exec psql`` 断言 DB 产物：
AI 分析/人工审核后 search-worker 自动构建 shot_search_document 并以 FakeEmbedding 写 vector(384)。

覆盖（自包含，不依赖 ci_ai_e2e 的具体审核）：completed 文档>0、维度 384、embedding_version 非空、
source 溯源、当前代次唯一、document_status=indexed；confirm→human、modify→重建、reject→excluded、
reopen→重新 searchable；重启后持久化。仅计数/维度/状态，**不输出业务文本/密钥**。

用法：
    python scripts/ci_search_e2e.py --mode full
    python scripts/ci_search_e2e.py --mode check-persist
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
_PSQL = ["docker", "compose", "exec", "-T", "postgres", "psql", "-U", "clipmind", "-d", "clipmind", "-tAc"]


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
    return json.loads(raw) if raw else {}


def poll(fn, ok, *, timeout=150, interval=3, desc=""):
    deadline = time.time() + timeout
    while time.time() < deadline:
        v = fn()
        if ok(v):
            return v
        print(f"  等待 {desc}: 当前={v}")
        time.sleep(interval)
    raise SystemExit(f"超时等待: {desc}")


def completed_docs() -> int:
    return _int(
        "select count(*) from shot_search_document "
        "where embedding_status='completed' and embedding is not null"
    )


def _review(shot_id: int) -> dict:
    return jreq("GET", f"/api/shots/{shot_id}/review")


def _action(shot_id: int, action: str, **extra) -> None:
    lv = _review(shot_id).get("lock_version", 0)
    jreq("POST", f"/api/shots/{shot_id}/review/{action}",
         {"lock_version": lv, "reviewer_label": "ci", **extra})


def _doc_field(shot_id: int, field: str) -> str:
    return q(f"select {field} from shot_search_document where shot_id={shot_id}")


def _asset_with_shots() -> int:
    for a in jreq("GET", "/api/assets?page=1&page_size=100").get("items", []):
        if jreq("GET", f"/api/shots?asset_id={a['id']}&page=1&page_size=100").get("items"):
            return a["id"]
    raise SystemExit("找不到带镜头的素材")


def full() -> int:
    aid = _asset_with_shots()
    shots = jreq("GET", f"/api/shots?asset_id={aid}&page=1&page_size=100")["items"]

    # 1) search-worker 在 AI 完成后自动构建并嵌入
    print("等待 search-worker 构建并嵌入检索文档（FakeEmbedding）...")
    poll(completed_docs, lambda n: n >= 1, desc="completed 检索文档")
    dim = _int("select vector_dims(embedding) from shot_search_document where embedding is not null limit 1")
    if dim != 384:
        raise SystemExit(f"向量维度不为 384: {dim}")
    if _int("select count(*) from shot_search_document where embedding_status='completed' and coalesce(embedding_version,'')=''"):
        raise SystemExit("存在 completed 文档缺 embedding_version")
    if _int("select count(*) from shot_search_document where embedding_status='completed' and document_status<>'indexed'"):
        raise SystemExit("completed 文档 document_status 非 indexed")
    if _int("select count(*) from shot_search_document where is_searchable and source_ai_analysis_id is null and source_review_state_id is null"):
        raise SystemExit("searchable 文档缺 source 溯源")
    # 当前代次唯一：无 shot 出现多条文档
    if _int("select coalesce(max(c),0) from (select shot_id,count(*) c from shot_search_document group by shot_id) t") > 1:
        raise SystemExit("存在同一 shot 多条检索文档")
    print(f"completed_docs={completed_docs()} dim={dim}")

    # 选未审核镜头驱动状态机
    unrev = [s["id"] for s in shots
             if _review(s["id"]).get("review_status") in ("unreviewed", "pending_review")]
    if not unrev:
        raise SystemExit("无未审核镜头可驱动")
    a_id = unrev[0]
    b_id = unrev[1] if len(unrev) > 1 else None

    # 2) confirm → 文档来源切 human
    _action(a_id, "confirm")
    poll(lambda: _doc_field(a_id, "effective_source"), lambda s: s == "human",
         desc=f"shot {a_id} 切 human")
    if _int(f"select count(*) from shot_search_document where shot_id={a_id} and source_review_state_id is not null") != 1:
        raise SystemExit("确认后缺 human 溯源")
    print(f"shot {a_id} confirm → human OK")

    # 3) modify → 文档重建反映新内容
    marker = "E2E修改标记ZZ"
    _action(a_id, "modify", confirmed_result={"one_line": marker, "scene": "室内"})
    poll(lambda: _int(f"select count(*) from shot_search_document where shot_id={a_id} and search_document like '%{marker}%'"),
         lambda n: n == 1, desc=f"shot {a_id} modify 重建")
    print(f"shot {a_id} modify → 重建 OK")

    # 4) reject → excluded；reopen → 重新 searchable
    if b_id is not None:
        _action(b_id, "reject")
        poll(lambda: _doc_field(b_id, "document_status"), lambda s: s == "excluded",
             desc=f"shot {b_id} excluded")
        if _int(f"select count(*) from shot_search_document where shot_id={b_id} and is_searchable") != 0:
            raise SystemExit("驳回后仍 searchable")
        print(f"shot {b_id} reject → excluded OK")
        _action(b_id, "reopen")
        poll(lambda: _int(f"select count(*) from shot_search_document where shot_id={b_id} and is_searchable"),
             lambda n: n == 1, desc=f"shot {b_id} reopen 重新 searchable")
        print(f"shot {b_id} reopen → searchable OK")
    else:
        print("（仅 1 个未审核镜头，跳过 reject/reopen 子流程）")

    print("SEARCH_E2E_OK")
    return 0


def check_persist() -> int:
    poll(completed_docs, lambda n: n >= 1, timeout=60, desc="重启后 completed 文档")
    human = _int("select count(*) from shot_search_document where effective_source='human'")
    print(f"重启后 completed_docs={completed_docs()} human_docs={human}")
    if human < 1:
        raise SystemExit("重启后人工来源文档丢失")
    print("SEARCH_E2E_PERSIST_OK")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="PR-04 检索文档索引 E2E")
    ap.add_argument("--mode", choices=["full", "check-persist"], default="full")
    args = ap.parse_args()
    return full() if args.mode == "full" else check_persist()


if __name__ == "__main__":
    raise SystemExit(main())
