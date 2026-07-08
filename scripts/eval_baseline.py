#!/usr/bin/env python3
"""EVAL 基线评测（只读）：检索 recall@k + 视觉阈值分布。

ground truth = 人工确认的产品素材绑定（product_media_link）。
只输出统计量与数据库 id，绝不输出文件名、路径或素材内容。

用法（任一模式，DB 直连只读；DATABASE_URL 形如 postgresql://...）:
  python scripts/eval_baseline.py --db postgresql://user:pass@host:5432/clipmind \
      --mode visual
  python scripts/eval_baseline.py --db ... --mode retrieval --api http://localhost:8000
  python scripts/eval_baseline.py --db ... --mode all --api http://localhost:8000 \
      --json out.json

visual 模式：正对（绑定素材↔本产品参考图 max-sim）与干扰对分布、
阈值网格 precision/recall、类数≥2 时的 top1/margin。
retrieval 模式：对每个有绑定的产品，用产品名称搜素材（POST /api/search/assets），
计算其确认绑定图片的 recall@k。
"""

from __future__ import annotations

import argparse
import json
import sys
import urllib.request

try:
    import psycopg
except ImportError:  # pragma: no cover
    psycopg = None

THRESHOLD_GRID = [0.50, 0.55, 0.60, 0.65, 0.70, 0.75, 0.80, 0.85]
RECALL_KS = [10, 30]


def _pct(rows: list[float], q: float) -> float | None:
    if not rows:
        return None
    s = sorted(rows)
    i = min(len(s) - 1, max(0, int(round(q * (len(s) - 1)))))
    return round(s[i], 4)


def visual_eval(conn) -> dict:
    """正对/干扰对相似度 + 阈值网格；全部 SQL 只读。"""
    with conn.cursor() as cur:
        cur.execute(
            """
            WITH ref_emb AS (
              SELECT pra.family_id, vme.embedding
              FROM product_reference_asset pra
              JOIN visual_media_embedding vme
                ON vme.target_type='reference' AND vme.target_id=pra.id
               AND vme.status='completed'
              WHERE pra.archived_at IS NULL
            ),
            linked_img AS (
              SELECT DISTINCT pml.family_id, pml.asset_id
              FROM product_media_link pml
              JOIN asset a ON a.id = pml.asset_id AND a.media_kind='image'
              WHERE pml.asset_id IS NOT NULL
            ),
            best AS (
              SELECT li.family_id AS linked_family, li.asset_id,
                     r.family_id AS ref_family,
                     max(1 - (v.embedding <=> r.embedding)) AS sim
              FROM linked_img li
              JOIN visual_media_embedding v
                ON v.target_type='asset' AND v.target_id=li.asset_id
               AND v.status='completed'
              JOIN ref_emb r ON true
              GROUP BY 1, 2, 3
            )
            SELECT linked_family, asset_id, ref_family, sim FROM best
            """
        )
        rows = cur.fetchall()

    ref_families = sorted({r[2] for r in rows})
    pos = [float(r[3]) for r in rows if r[0] == r[2]]
    neg = [float(r[3]) for r in rows if r[0] != r[2]]

    grid = []
    for t in THRESHOLD_GRID:
        tp = sum(1 for s in pos if s >= t)
        fp = sum(1 for s in neg if s >= t)
        fn = len(pos) - tp
        precision = round(tp / (tp + fp), 3) if (tp + fp) else None
        recall = round(tp / (tp + fn), 3) if (tp + fn) else None
        grid.append({"threshold": t, "tp": tp, "fp": fp, "precision": precision, "recall": recall})

    out: dict = {
        "ref_family_count": len(ref_families),
        "positive_pairs": {
            "n": len(pos), "mean": _pct(pos, 0.5) and round(sum(pos) / len(pos), 4),
            "p10": _pct(pos, 0.1), "p50": _pct(pos, 0.5), "p90": _pct(pos, 0.9),
        },
        "distractor_pairs": {
            "n": len(neg), "mean": neg and round(sum(neg) / len(neg), 4),
            "p10": _pct(neg, 0.1), "p50": _pct(neg, 0.5), "p90": _pct(neg, 0.9),
        },
        "threshold_grid": grid,
    }

    # 类数 >= 2 才有 top1/margin 语义
    if len(ref_families) >= 2:
        by_asset: dict[int, list[tuple[int, int, float]]] = {}
        for lf, aid, rf, sim in rows:
            by_asset.setdefault(aid, []).append((lf, rf, float(sim)))
        top1_correct = 0
        margins_right: list[float] = []
        margins_wrong: list[float] = []
        for aid, items in by_asset.items():
            items.sort(key=lambda x: -x[2])
            lf = items[0][0]
            top1 = items[0]
            margin = items[0][2] - items[1][2] if len(items) > 1 else None
            if top1[1] == lf:
                top1_correct += 1
                if margin is not None:
                    margins_right.append(margin)
            elif margin is not None:
                margins_wrong.append(margin)
        out["multiclass"] = {
            "assets": len(by_asset),
            "top1_correct": top1_correct,
            "top1_acc": round(top1_correct / len(by_asset), 3) if by_asset else None,
            "margin_when_right_p50": _pct(margins_right, 0.5),
            "margin_when_wrong_p50": _pct(margins_wrong, 0.5),
        }
    else:
        out["multiclass"] = None
        out["note"] = "参考图只覆盖 1 个产品——先补齐多产品参考图再做 margin/终稿阈值校准"
    return out


def retrieval_eval(conn, api: str) -> dict:
    """以确认绑定为 ground truth 的素材搜索 recall@k（走真实 API）。"""
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT pf.id, pf.name_zh, array_agg(DISTINCT pml.asset_id)
            FROM product_media_link pml
            JOIN product_family pf ON pf.id = pml.family_id
            JOIN asset a ON a.id = pml.asset_id AND a.media_kind='image'
            WHERE pml.asset_id IS NOT NULL
            GROUP BY pf.id, pf.name_zh
            """
        )
        families = cur.fetchall()

    results = []
    for fid, name, truth_ids in families:
        truth = set(truth_ids)
        payload = json.dumps(
            {"query": name, "media_kind": "image", "page": 1, "page_size": max(RECALL_KS)}
        ).encode("utf-8")
        req = urllib.request.Request(
            f"{api}/api/search/assets", data=payload,
            headers={"Content-Type": "application/json"}, method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=60) as resp:
                body = json.loads(resp.read())
        except Exception as exc:  # noqa: BLE001
            results.append({"family_id": fid, "error": str(exc)[:80]})
            continue
        got = [it.get("asset_id") for it in body.get("items", [])]
        row = {"family_id": fid, "truth_n": len(truth)}
        for k in RECALL_KS:
            hit = len(truth & set(got[:k]))
            row[f"recall@{k}"] = round(hit / len(truth), 3) if truth else None
        results.append(row)

    valid = [r for r in results if "error" not in r]
    summary = {
        "families": len(results),
        "errors": len(results) - len(valid),
    }
    for k in RECALL_KS:
        vals = [r[f"recall@{k}"] for r in valid if r.get(f"recall@{k}") is not None]
        summary[f"macro_recall@{k}"] = round(sum(vals) / len(vals), 3) if vals else None
    return {"summary": summary, "per_family": results}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--db", required=True, help="postgresql://... 只读连接")
    ap.add_argument("--mode", choices=["visual", "retrieval", "all"], default="all")
    ap.add_argument("--api", default="http://localhost:8000", help="retrieval 模式的 API 地址")
    ap.add_argument("--json", dest="json_out", default=None, help="结果另存 JSON 文件")
    args = ap.parse_args()

    if psycopg is None:
        print("需要 psycopg：pip install psycopg[binary]", file=sys.stderr)
        return 2

    report: dict = {}
    with psycopg.connect(args.db) as conn:
        conn.execute("SET default_transaction_read_only = on")
        if args.mode in ("visual", "all"):
            report["visual"] = visual_eval(conn)
        if args.mode in ("retrieval", "all"):
            report["retrieval"] = retrieval_eval(conn, args.api.rstrip("/"))

    print(json.dumps(report, ensure_ascii=False, indent=2))
    if args.json_out:
        with open(args.json_out, "w", encoding="utf-8") as f:
            json.dump(report, f, ensure_ascii=False, indent=2)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
