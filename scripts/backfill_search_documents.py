#!/usr/bin/env python3
"""回填检索文档（PR-04）：把既有 ready 镜头的有效结果构建为 shot_search_document 并嵌入。

幂等：相同内容 + 同嵌入身份（provider/model/revision/dimension/version）+ 同模板版本且已
completed 则跳过重嵌；rejected/unable 标 excluded（保留记录）。重复运行不产生重复行。
脱敏统计（仅计数，不输出业务文本/密钥）。支持 --dry-run（回滚不落库）。

用法：
    DATABASE_URL=postgresql+asyncpg://... EMBEDDING_PROVIDER=fake \\
        python scripts/backfill_search_documents.py --dry-run
    # 模型升级全量重嵌（目标版本 != 现有版本的行）：
    python scripts/backfill_search_documents.py --force-reembed
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from time import perf_counter

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from clipmind_shared.models import Shot, ShotSearchDocument
from clipmind_shared.models.enums import SearchEmbeddingStatus, ShotStatus
from clipmind_worker.config import get_settings
from clipmind_worker.search.indexer import build_embedding_provider, rebuild_shot_document


def _candidate_shot_ids(s: Session, args: argparse.Namespace) -> list[int]:
    stmt = select(Shot.id).where(Shot.status == ShotStatus.READY)
    if args.shot_id:
        stmt = stmt.where(Shot.id == args.shot_id)
    elif args.asset_id:
        stmt = stmt.where(Shot.asset_id == args.asset_id)
    stmt = stmt.order_by(Shot.id.asc())
    ids = list(s.execute(stmt).scalars().all())

    if not (args.only_failed or args.model_version or args.resume):
        return ids

    # 读现有文档状态做筛选（按 shot_id）
    docs = {
        d.shot_id: d
        for d in s.execute(
            select(ShotSearchDocument).where(ShotSearchDocument.shot_id.in_(ids))
        ).scalars().all()
    }
    out: list[int] = []
    for sid in ids:
        d = docs.get(sid)
        if args.only_failed and (d is None or d.embedding_status != SearchEmbeddingStatus.FAILED):
            continue
        if args.model_version and d is not None and d.embedding_version == args.model_version:
            continue  # 已在目标版本
        if args.resume and not args.force_reembed and d is not None and (
            d.embedding_status == SearchEmbeddingStatus.COMPLETED and d.embedding is not None
        ):
            continue  # 已完成，断点续跑跳过
        out.append(sid)
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description="回填检索文档（幂等）")
    ap.add_argument("--dry-run", action="store_true", help="只统计，回滚不落库")
    ap.add_argument("--asset-id", type=int, default=None)
    ap.add_argument("--shot-id", type=int, default=None)
    ap.add_argument("--batch-size", type=int, default=100)
    ap.add_argument("--resume", action="store_true", help="跳过已 completed 的镜头（断点续跑）")
    ap.add_argument("--force-reembed", action="store_true", help="强制重嵌（忽略幂等跳过）")
    ap.add_argument("--model-version", default="", help="目标 embedding_version；仅处理未在该版本的行")
    ap.add_argument("--only-failed", action="store_true", help="仅处理 embedding_status=failed 的行")
    ap.add_argument("--database-url", default=os.environ.get("DATABASE_URL", ""))
    args = ap.parse_args()

    url = (args.database_url or "").replace("+asyncpg", "+psycopg")
    if not url:
        print("需要 DATABASE_URL", file=sys.stderr)
        return 1

    settings = get_settings()
    provider = build_embedding_provider(settings)
    stats: dict[str, int] = {}
    t0 = perf_counter()

    engine = create_engine(url)
    with Session(engine) as s:
        shot_ids = _candidate_shot_ids(s, args)
        for i, sid in enumerate(shot_ids, start=1):
            try:
                status = rebuild_shot_document(
                    s, sid, provider, force_reembed=args.force_reembed
                )
            except Exception as exc:  # noqa: BLE001
                status = "error"
                print(f"回填异常 shot={sid}: {type(exc).__name__}", file=sys.stderr)
            stats[status] = stats.get(status, 0) + 1
            if not args.dry_run and i % args.batch_size == 0:
                s.commit()
        if args.dry_run:
            s.rollback()
            mode = "dry-run（已回滚，未落库）"
        else:
            s.commit()
            mode = "committed"

    engine.dispose()
    elapsed_ms = int((perf_counter() - t0) * 1000)
    print(
        json.dumps(
            {
                "mode": mode,
                "scanned": len(shot_ids),
                "stats": stats,
                "embedding_provider": provider.identity().provider,
                "embedding_version": provider.identity().embedding_version,
                "elapsed_ms": elapsed_ms,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
