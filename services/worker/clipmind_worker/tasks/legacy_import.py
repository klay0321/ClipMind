"""PR-C Gate B：历史证据导入任务（幂等；只读 AssetLocation，零文件 IO）。

- 输入只来源于 asset_location.relative_path（不递归文件系统、不读媒体、
  不改文件名、不移动文件、不修改 AssetLocation 状态）；
- evidence_key 唯一 ⇒ 幂等：存在则只更新 last_observed_at / observation_count /
  import_run_id，**绝不覆盖人工 review_status**；
- dry_run=true 时只统计不写 evidence；
- 单条错误不中止任务（error_count 累计，error_summary 截断且不含绝对路径）；
- run 级 advisory lock（经 session 执行——裸连接执行会使后续 commit 退化为
  savepoint 并在连接关闭时回滚）；
- 绝不创建 FinalVideoUsage、绝不改变 confirmed 使用次数。
"""

from __future__ import annotations

from typing import Any

from clipmind_shared.constants import ERROR_MESSAGE_MAX_LEN, TASK_LEGACY_IMPORT
from clipmind_shared.db.base import utcnow
from clipmind_shared.legacy_rules import RuleSpec, compute_evidence_key, match_rule
from clipmind_shared.models import (
    AssetLocation,
    LegacyUsageEvidence,
    LegacyUsageEvidenceEvent,
    LegacyUsageImportRun,
    LegacyUsageRule,
)
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from clipmind_worker.celery_app import celery_app
from clipmind_worker.db import engine

# run 级互斥（namespace "LU" legacy usage）
ADVISORY_LOCK_NAMESPACE = 0x4C55

COMMIT_BATCH = 200


def _truncate(message: str) -> str:
    return message[:ERROR_MESSAGE_MAX_LEN]


def _location_statuses_for(rule: LegacyUsageRule) -> set[str]:
    scope = set()
    if rule.include_present_locations:
        scope.add("present")
    if rule.include_missing_locations:
        scope.add("missing")
    if rule.include_historical_locations:
        scope.add("historical")
    return scope


def _rule_snapshot(rule: LegacyUsageRule) -> dict[str, Any]:
    return {
        "rule_id": rule.id,
        "name": rule.name,
        "match_target": rule.match_target,
        "match_operator": rule.match_operator,
        "pattern": rule.pattern,
        "case_sensitive": rule.case_sensitive,
    }


@celery_app.task(name=TASK_LEGACY_IMPORT, bind=True, acks_late=True)
def legacy_import_run(self, run_id: int) -> dict[str, Any]:  # noqa: ANN001
    with engine.connect() as conn:
        session = Session(bind=conn)
        try:
            run = session.get(LegacyUsageImportRun, run_id)
            if run is None:
                return {"error": "run_not_found", "run_id": run_id}
            if run.status not in ("pending",):
                return {"skipped": True, "reason": f"status={run.status}"}

            run.status = "running"
            run.started_at = utcnow()
            session.commit()

            locked = session.execute(
                text("SELECT pg_try_advisory_lock(:ns, :key)"),
                {"ns": ADVISORY_LOCK_NAMESPACE, "key": run_id},
            ).scalar()
            if not locked:
                run.status = "failed"
                run.error_summary = "另一导入任务持有锁"
                run.completed_at = utcnow()
                session.commit()
                return {"skipped": True, "reason": "locked"}

            try:
                return _execute(session, run)
            finally:
                session.execute(
                    text("SELECT pg_advisory_unlock(:ns, :key)"),
                    {"ns": ADVISORY_LOCK_NAMESPACE, "key": run_id},
                )
                session.commit()
        except Exception as exc:  # noqa: BLE001
            session.rollback()
            run = session.get(LegacyUsageImportRun, run_id)
            if run is not None:
                run.status = "failed"
                run.error_summary = _truncate(str(exc))
                run.completed_at = utcnow()
                session.commit()
            raise
        finally:
            session.close()


def _execute(session: Session, run: LegacyUsageImportRun) -> dict[str, Any]:
    # 规则集：以 run.rule_snapshot 的 rule_id 为准（当前仍启用的行）；
    # 规则快照冻结当次语义 —— run 创建后的规则修改不影响本次匹配吗?
    # 保守：按快照重建 RuleSpec（快照即事实），location scope 用行上的开关快照。
    snapshot = run.rule_snapshot or []
    rule_ids = [s["rule_id"] for s in snapshot]
    rules = {
        r.id: r
        for r in session.execute(
            select(LegacyUsageRule).where(LegacyUsageRule.id.in_(rule_ids))
        ).scalars()
    }

    loc_q = select(AssetLocation)
    if run.source_directory_id is not None:
        loc_q = loc_q.where(AssetLocation.source_root_id == run.source_directory_id)
    locations = list(session.execute(loc_q.order_by(AssetLocation.id)).scalars())
    run.scanned_location_count = len(locations)
    session.commit()

    matched: dict[str, dict[str, Any]] = {}
    matched_assets: set[int] = set()
    matched_locations = 0
    errors: list[str] = []

    for loc in locations:
        for snap in snapshot:
            rule = rules.get(snap["rule_id"])
            if rule is None:
                continue
            if (
                rule.source_directory_id is not None
                and loc.source_root_id != rule.source_directory_id
            ):
                continue
            if loc.location_status not in _location_statuses_for(rule):
                continue
            spec = RuleSpec(
                rule_id=rule.id,
                match_target=snap["match_target"],
                match_operator=snap["match_operator"],
                normalized_pattern=rule.normalized_pattern,
                case_sensitive=snap.get("case_sensitive", False),
            )
            try:
                hits = match_rule(loc.relative_path, spec)
            except Exception as exc:  # noqa: BLE001 - 单条错误不中止
                errors.append(_truncate(f"location {loc.id}: {exc}"))
                continue
            for hit in hits:
                key = compute_evidence_key(
                    rule.id, loc.asset_id, hit.match_target, hit.matched_component
                )
                matched_locations += 1
                matched_assets.add(loc.asset_id)
                if key not in matched:
                    matched[key] = {
                        "asset_id": loc.asset_id,
                        "rule": rule,
                        "location": loc,
                        "hit": hit,
                        "snapshot": snap,
                    }

    run.matched_location_count = matched_locations
    run.matched_asset_count = len(matched_assets)
    session.commit()

    created = existing = 0
    if not run.dry_run:
        batch = 0
        for key, m in matched.items():
            try:
                ev = (
                    session.execute(
                        select(LegacyUsageEvidence).where(
                            LegacyUsageEvidence.evidence_key == key
                        )
                    )
                    .scalars()
                    .first()
                )
                if ev is None:
                    ev = LegacyUsageEvidence(
                        asset_id=m["asset_id"],
                        asset_location_id=m["location"].id,
                        rule_id=m["rule"].id,
                        import_run_id=run.id,
                        evidence_key=key,
                        evidence_type=m["hit"].evidence_type,
                        matched_target=m["hit"].match_target,
                        matched_component=m["hit"].matched_component,
                        rule_snapshot=m["snapshot"],
                        review_status="pending",
                    )
                    session.add(ev)
                    session.flush()
                    session.add(
                        LegacyUsageEvidenceEvent(
                            evidence_id=ev.id,
                            action="detected",
                            before_status=None,
                            after_status="pending",
                        )
                    )
                    created += 1
                else:
                    # 幂等重复观察：只更新观察信息，绝不覆盖人工 review_status
                    ev.last_observed_at = utcnow()
                    ev.observation_count += 1
                    ev.import_run_id = run.id
                    session.add(
                        LegacyUsageEvidenceEvent(
                            evidence_id=ev.id,
                            action="observed_again",
                            before_status=ev.review_status,
                            after_status=ev.review_status,
                        )
                    )
                    existing += 1
            except IntegrityError:
                # 并发下唯一约束兜底：按已存在处理
                session.rollback()
                existing += 1
                continue
            except Exception as exc:  # noqa: BLE001
                session.rollback()
                errors.append(_truncate(f"evidence {key[:12]}: {exc}"))
                continue
            batch += 1
            if batch >= COMMIT_BATCH:
                run.created_evidence_count = created
                run.existing_evidence_count = existing
                session.commit()
                batch = 0
        session.commit()
    else:
        # dry-run：只统计
        existing_keys = set(
            session.execute(
                select(LegacyUsageEvidence.evidence_key).where(
                    LegacyUsageEvidence.evidence_key.in_(list(matched.keys()))
                )
            ).scalars()
        ) if matched else set()
        created = len([k for k in matched if k not in existing_keys])
        existing = len(existing_keys)

    run.created_evidence_count = created
    run.existing_evidence_count = existing
    run.error_count = len(errors)
    run.error_summary = "; ".join(errors[:10]) or None
    run.completed_at = utcnow()
    run.status = "completed_with_errors" if errors else "completed"
    session.commit()
    return {
        "run_id": run.id,
        "status": run.status,
        "created": created,
        "existing": existing,
        "errors": len(errors),
        "dry_run": run.dry_run,
    }
