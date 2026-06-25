#!/usr/bin/env python3
"""回填 shot_tag 投影（PR-03B.1）：把既有 AI 分析与人工确认结果投影为 active ShotTag。

幂等：每次都先把同来源旧 active 投影置 inactive 再写新，重复运行结果一致、不产生重复 active。
覆盖：所有 completed AIShotAnalysis（AI 投影）+ confirmed/modified ShotReviewState（human 投影）；
跳过 rejected/unable。脱敏统计（仅计数）。支持 --dry-run（回滚不落库）。

用法：
    DATABASE_URL=postgresql+asyncpg://... python scripts/backfill_shot_tag_projections.py --dry-run
    DATABASE_URL=postgresql+asyncpg://... python scripts/backfill_shot_tag_projections.py
"""

from __future__ import annotations

import argparse
import json
import os
import sys

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from clipmind_shared.models import AIShotAnalysis, ShotReviewState
from clipmind_shared.models.enums import AIShotAnalysisStatus, ReviewStatus
from clipmind_worker.ai.projection import project_ai_tags, project_human_tags


def main() -> int:
    ap = argparse.ArgumentParser(description="回填 shot_tag 投影（幂等）")
    ap.add_argument("--dry-run", action="store_true", help="只统计，回滚不落库")
    ap.add_argument("--database-url", default=os.environ.get("DATABASE_URL", ""))
    args = ap.parse_args()

    url = (args.database_url or "").replace("+asyncpg", "+psycopg")
    if not url:
        print("需要 DATABASE_URL", file=sys.stderr)
        return 1

    stats = {
        "ai_analyses_scanned": 0,
        "ai_tags_written": 0,
        "ai_projection_errors": 0,
        "human_reviews_scanned": 0,
        "human_tags_written": 0,
        "human_projection_errors": 0,
    }
    engine = create_engine(url)
    with Session(engine) as s:
        ais = (
            s.execute(
                select(AIShotAnalysis).where(
                    AIShotAnalysis.status == AIShotAnalysisStatus.COMPLETED
                )
            )
            .scalars()
            .all()
        )
        for ai in ais:
            stats["ai_analyses_scanned"] += 1
            try:
                stats["ai_tags_written"] += project_ai_tags(
                    s, shot_id=ai.shot_id, parsed=ai.parsed_result,
                    ai_analysis_id=ai.id, confidence=ai.confidence,
                )
                ai.projection_status = "ok"
            except Exception as exc:  # noqa: BLE001
                stats["ai_projection_errors"] += 1
                ai.projection_status = "error"
                print(f"AI 投影失败 shot={ai.shot_id}: {type(exc).__name__}", file=sys.stderr)

        revs = (
            s.execute(
                select(ShotReviewState).where(
                    ShotReviewState.review_status.in_(
                        [ReviewStatus.CONFIRMED, ReviewStatus.MODIFIED]
                    )
                )
            )
            .scalars()
            .all()
        )
        for r in revs:
            stats["human_reviews_scanned"] += 1
            try:
                stats["human_tags_written"] += project_human_tags(
                    s, shot_id=r.shot_id, confirmed_result=r.confirmed_result,
                    reviewer_label=r.reviewer_label,
                    source_ai_analysis_id=r.source_ai_analysis_id,
                )
            except Exception as exc:  # noqa: BLE001
                stats["human_projection_errors"] += 1
                print(f"human 投影失败 shot={r.shot_id}: {type(exc).__name__}", file=sys.stderr)

        if args.dry_run:
            s.rollback()
            mode = "dry-run（已回滚，未落库）"
        else:
            s.commit()
            mode = "committed"

    engine.dispose()
    print(json.dumps({"mode": mode, **stats}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
