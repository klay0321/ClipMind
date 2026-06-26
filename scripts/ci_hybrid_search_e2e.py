#!/usr/bin/env python3
"""Gate B 混合检索 / 画面描述匹配 端到端（docker-e2e 用）。

前置：检索文档已索引（先跑 ``scripts/ci_search_e2e.py --mode full``），compose 配置
``EMBEDDING_PROVIDER=fake``（CI）。本脚本只经 HTTP 调 Gate B API，断言响应契约与降级语义，
不输出业务文本/密钥。

覆盖：索引状态、hybrid/lexical/structured 检索、分项分与规则解释、degraded 真实可见、
描述匹配契约、稳定分页、重启后检索仍可用。

用法：
    python scripts/ci_hybrid_search_e2e.py --mode full
    python scripts/ci_hybrid_search_e2e.py --mode check-persist
"""

from __future__ import annotations

import argparse
import json
import os
import urllib.error
import urllib.request

API = os.environ.get("API_BASE", "http://localhost:8000")


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


def _index_status() -> dict:
    return jreq("GET", "/api/search/index/status")


def _search(**body) -> dict:
    return jreq("POST", "/api/search/shots", body)


def _pick_term() -> tuple[str, str | None]:
    """从建议接口取一个真实可检索词（产品/标签）；返回 (词, 场景词或 None)。"""
    sug = jreq("GET", "/api/search/suggestions?limit=20").get("items", [])
    scene = next((s["value"] for s in sug if s["type"] == "scene"), None)
    term = next((s["value"] for s in sug if s["type"] in ("scene", "action", "product")), None)
    return term or "镜头", scene


def _assert_item_contract(item: dict) -> None:
    for f in (
        "shot_id", "asset_id", "duration", "asset", "score", "match_percent",
        "matched_reasons", "unmatched_requirements", "risk_warnings",
        "review_status", "review_is_stale", "embedding_degraded",
    ):
        if f not in item:
            raise SystemExit(f"搜索 item 缺字段: {f}")
    # 分项分键存在（值可为 null）
    for f in ("semantic_score", "lexical_score", "tag_score", "product_score"):
        if f not in item:
            raise SystemExit(f"搜索 item 缺分项分: {f}")


def full() -> int:
    status = _index_status()
    print(f"index_status: indexed={status['indexed_documents']} "
          f"completed_emb={status['completed_embeddings']} "
          f"version={status['current_embedding_version']!r} healthy={status['provider_healthy']}")
    if status["indexed_documents"] < 1:
        raise SystemExit("无已索引文档：请先运行 scripts/ci_search_e2e.py --mode full")

    term, scene = _pick_term()
    print(f"探测检索词: term={term!r} scene={scene!r}")

    # 1) hybrid 检索
    res = _search(query=term, search_mode="hybrid", page_size=10)
    if res["total"] < 1 or not res["items"]:
        raise SystemExit(f"hybrid 检索无结果（term={term!r}）")
    _assert_item_contract(res["items"][0])
    print(f"hybrid: total={res['total']} mode_used={res['search_mode_used']} "
          f"parser={res['parser_status']} emb={res['embedding_status']} "
          f"degraded={res['degraded']} elapsed_ms={res['elapsed_ms']}")
    # 有 completed 嵌入时，hybrid 的向量通道应可用且部分 item 有 semantic_score
    if status["completed_embeddings"] >= 1:
        if res["embedding_status"] != "ok":
            raise SystemExit(f"有 completed 嵌入但 embedding_status={res['embedding_status']}")
        if not any(it.get("semantic_score") is not None for it in res["items"]):
            raise SystemExit("hybrid 结果无任何 semantic_score（向量召回未生效）")
        # 进入向量召回的 item 才可有“语义相似”理由；degraded item 绝不出现
        for it in res["items"]:
            if it["embedding_degraded"] and "语义相似（向量召回）" in it["matched_reasons"]:
                raise SystemExit("degraded item 出现语义理由（违反契约）")

    # 2) lexical 模式：semantic_score 必为 null
    lex = _search(query=term, search_mode="lexical", page_size=10)
    if lex["items"] and any(it.get("semantic_score") is not None for it in lex["items"]):
        raise SystemExit("lexical 模式不应有 semantic_score")
    print(f"lexical: total={lex['total']} mode_used={lex['search_mode_used']}")

    # 3) structured（若有场景词）
    if scene:
        st = _search(scenes=[scene], search_mode="structured", page_size=10)
        print(f"structured(scene={scene!r}): total={st['total']}")
        if st["total"] < 1:
            raise SystemExit(f"structured 场景检索无结果（scene={scene!r}）")

    # 4) 稳定分页：page1 与 page2 不重叠
    p1 = _search(query=term, search_mode="hybrid", page=1, page_size=2)
    p2 = _search(query=term, search_mode="hybrid", page=2, page_size=2)
    ids1 = {it["shot_id"] for it in p1["items"]}
    ids2 = {it["shot_id"] for it in p2["items"]}
    if ids1 & ids2:
        raise SystemExit("分页出现重复 shot")
    print("HYBRID_SEARCH_E2E_OK")

    # 5) 画面描述匹配
    dm = jreq("POST", "/api/match/description",
              {"target_description": term, "limit": 10})
    if "target_requirements" not in dm:
        raise SystemExit("描述匹配缺 target_requirements")
    if dm["items"]:
        it = dm["items"][0]
        for f in ("recommendation_level", "requires_human_confirmation",
                  "matched_requirements", "target_requirements"):
            if f not in it:
                raise SystemExit(f"描述匹配 item 缺字段: {f}")
    print(f"description_match: total={dm['total']} reqs={len(dm['target_requirements'])}")
    print("DESCRIPTION_MATCH_E2E_OK")
    return 0


def check_persist() -> int:
    status = _index_status()
    if status["indexed_documents"] < 1:
        raise SystemExit("重启后无已索引文档")
    term, _ = _pick_term()
    res = _search(query=term, search_mode="hybrid", page_size=10)
    print(f"重启后 hybrid: total={res['total']} emb={res['embedding_status']} "
          f"indexed={status['indexed_documents']}")
    if res["total"] < 1:
        raise SystemExit("重启后检索无结果")
    print("SEARCH_API_PERSIST_OK")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="Gate B 混合检索 E2E")
    ap.add_argument("--mode", choices=["full", "check-persist"], default="full")
    args = ap.parse_args()
    return full() if args.mode == "full" else check_persist()


if __name__ == "__main__":
    raise SystemExit(main())
