"""PR-C Gate B：历史证据导入任务（不可变快照 / upsert 幂等 / 全局串行 / 可取消）。

加固语义（docs/LEGACY_USAGE_EVIDENCE.md）：
- **纯快照执行**：匹配语义（pattern / 大小写 / 位置范围 / 来源范围）完全来自
  ``run.rule_snapshot`` 经 ``frozen_rule_from_snapshot`` 校验重建 ——
  **零依赖实时 LegacyUsageRule 行**；run 创建后规则被修改/禁用/归档均不影响
  本次运行；快照校验失败计入 error（绝不静默跳过）。
- **事务安全**：PostgreSQL ``INSERT .. ON CONFLICT (evidence_key)`` upsert ——
  新建 pending 证据 + detected 事件；已存在只原子累加 observation_count /
  刷新 last_observed_at / import_run_id + observed_again 事件（同事务），
  **绝不触碰 review_status / review_note / reviewed_at / actor_label /
  rule_snapshot**；单条错误经 savepoint 隔离，不回滚批内已成功行。
- **真实串行**：全局单任务 advisory lock（namespace 0x4C55, key 0）——
  任意两个导入任务互斥；锁被占时任务保持 pending 并重试（不伪装业务失败、
  不产生部分证据）。锁经 session 执行（裸连接锁会使后续 commit 退化为
  savepoint 并在连接关闭时回滚）。
- **真实取消**：位置扫描批间与证据写入批间检查 run 状态；cancelled 则停止
  后续处理、保留已提交数据、不覆盖为 completed。
- **统计口径（distinct）**：matched_location_count = 命中的不同 AssetLocation
  数；existing_evidence_count = 本次命中的不同既有证据数；计数来自真实
  数据库写入结果。
- 隔离铁律不变：绝不创建 FinalVideoUsage、绝不改变 confirmed 使用次数、
  零文件 IO（输入只来源于 asset_location.relative_path）。
"""

from __future__ import annotations

from typing import Any

from celery.exceptions import Retry
from clipmind_shared.constants import ERROR_MESSAGE_MAX_LEN, TASK_LEGACY_IMPORT
from clipmind_shared.db.base import utcnow
from clipmind_shared.legacy_rules import (
    FrozenRule,
    RuleValidationError,
    compute_evidence_key,
    frozen_rule_from_snapshot,
    match_rule,
)
from clipmind_shared.models import (
    AssetLocation,
    LegacyUsageEvidence,
    LegacyUsageEvidenceEvent,
    LegacyUsageImportRun,
)
from sqlalchemy import select, text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from clipmind_worker.celery_app import celery_app
from clipmind_worker.db import engine

# 全局单任务锁（namespace "LU"；key 0 = 所有导入任务互斥 —— 第一版最安全方案：
# 全目录任务与任何单目录任务天然互斥，无读写锁复杂度）
ADVISORY_LOCK_NAMESPACE = 0x4C55
GLOBAL_LOCK_KEY = 0

COMMIT_BATCH = 200          # 证据写入批大小（批间提交 + 取消检查）
LOCATION_SCAN_BATCH = 500   # 位置扫描批大小（批间取消检查）
LOCK_RETRY_COUNTDOWN = 10   # 锁被占时的重试间隔（秒）
LOCK_MAX_RETRIES = 60       # 最多等待 ~10 分钟后 failed（错误信息准确）


def _truncate(message: str) -> str:
    return message[:ERROR_MESSAGE_MAX_LEN]


def _fresh_run_status(session: Session, run_id: int) -> str | None:
    """最新状态（列查询不走 identity map；取消检查用）。"""
    return session.execute(
        select(LegacyUsageImportRun.status).where(LegacyUsageImportRun.id == run_id)
    ).scalar_one_or_none()


def _after_batch(session: Session, run: LegacyUsageImportRun) -> None:
    """批间 hook（生产为 no-op；测试用它注入'运行中取消'时序）。"""


@celery_app.task(
    name=TASK_LEGACY_IMPORT, bind=True, acks_late=True, max_retries=LOCK_MAX_RETRIES
)
def legacy_import_run(self, run_id: int) -> dict[str, Any]:  # noqa: ANN001
    with engine.connect() as conn:
        session = Session(bind=conn)
        locked = False
        try:
            run = session.get(LegacyUsageImportRun, run_id)
            if run is None:
                return {"error": "run_not_found", "run_id": run_id}
            if run.status != "pending":
                # cancelled/completed/failed/running：不重复执行、不覆盖状态
                return {"skipped": True, "reason": f"status={run.status}"}

            # 先取全局锁，再置 running —— 锁被占时 run 保持 pending 并重试，
            # 不伪装业务失败、不产生部分证据
            locked = bool(
                session.execute(
                    text("SELECT pg_try_advisory_lock(:ns, :key)"),
                    {"ns": ADVISORY_LOCK_NAMESPACE, "key": GLOBAL_LOCK_KEY},
                ).scalar()
            )
            if not locked:
                session.rollback()
                try:
                    raise self.retry(countdown=LOCK_RETRY_COUNTDOWN)
                except Retry:
                    raise
                except Exception:  # noqa: BLE001 - MaxRetriesExceededError
                    run.status = "failed"
                    run.error_summary = "导入并发锁等待超时（另一导入任务长时间持锁）"
                    run.completed_at = utcnow()
                    session.commit()
                    return {"error": "lock_timeout", "run_id": run_id}

            run.status = "running"
            run.started_at = utcnow()
            session.commit()

            return _execute(session, run)
        except Retry:
            raise
        except Exception as exc:  # noqa: BLE001
            session.rollback()
            run = session.get(LegacyUsageImportRun, run_id)
            if run is not None and run.status == "running":
                run.status = "failed"
                run.error_summary = _truncate(str(exc))
                run.completed_at = utcnow()
                session.commit()
            raise
        finally:
            if locked:
                # 无论成功/失败/取消都释放锁（经 session 执行）
                session.rollback()
                session.execute(
                    text("SELECT pg_advisory_unlock(:ns, :key)"),
                    {"ns": ADVISORY_LOCK_NAMESPACE, "key": GLOBAL_LOCK_KEY},
                )
                session.commit()
            session.close()


def _load_frozen_rules(
    run: LegacyUsageImportRun, errors: list[str]
) -> list[FrozenRule]:
    """完全从 run.rule_snapshot 重建规则；校验失败计入 error，不静默跳过。"""
    rules: list[FrozenRule] = []
    for idx, snap in enumerate(run.rule_snapshot or []):
        try:
            rules.append(frozen_rule_from_snapshot(snap))
        except RuleValidationError as exc:
            rid = snap.get("rule_id") if isinstance(snap, dict) else None
            errors.append(_truncate(f"snapshot[{idx}] rule={rid}: {exc}"))
    return rules


def _cancelled(session: Session, run: LegacyUsageImportRun) -> bool:
    return _fresh_run_status(session, run.id) == "cancelled"


def _finish_cancelled(
    session: Session, run: LegacyUsageImportRun, counts: dict[str, int],
    errors: list[str],
) -> dict[str, Any]:
    """取消收尾：保留已提交数据与统计；不覆盖 status/completed_at（cancel API 已写）。"""
    session.rollback()
    for field, value in counts.items():
        setattr(run, field, value)
    run.error_count = len(errors)
    run.error_summary = "; ".join(errors[:10]) or None
    session.commit()
    return {"run_id": run.id, "status": "cancelled", **counts, "errors": len(errors)}


def _execute(session: Session, run: LegacyUsageImportRun) -> dict[str, Any]:
    errors: list[str] = []
    rules = _load_frozen_rules(run, errors)

    # 位置集合：run 范围（创建时冻结在行上）+ 规则快照范围双重过滤
    loc_q = select(AssetLocation)
    if run.source_directory_id is not None:
        loc_q = loc_q.where(AssetLocation.source_root_id == run.source_directory_id)
    locations = list(session.execute(loc_q.order_by(AssetLocation.id)).scalars())
    run.scanned_location_count = len(locations)
    session.commit()

    # ---- 匹配（distinct 口径；批间取消检查）----
    matched: dict[str, dict[str, Any]] = {}
    matched_location_ids: set[int] = set()
    matched_assets: set[int] = set()
    for start in range(0, len(locations), LOCATION_SCAN_BATCH):
        if _cancelled(session, run):
            return _finish_cancelled(
                session, run,
                {
                    "matched_location_count": len(matched_location_ids),
                    "matched_asset_count": len(matched_assets),
                },
                errors,
            )
        for loc in locations[start:start + LOCATION_SCAN_BATCH]:
            for frule in rules:
                # 范围过滤只用快照字段（绝不读实时 Rule 行）
                if (
                    frule.source_directory_id is not None
                    and loc.source_root_id != frule.source_directory_id
                ):
                    continue
                if loc.location_status not in frule.location_statuses():
                    continue
                try:
                    hits = match_rule(loc.relative_path, frule.spec)
                except Exception as exc:  # noqa: BLE001 - 单条错误不中止
                    errors.append(_truncate(f"location {loc.id}: {exc}"))
                    continue
                for hit in hits:
                    key = compute_evidence_key(
                        frule.snapshot_hash, loc.asset_id,
                        hit.match_target, hit.matched_component,
                    )
                    matched_location_ids.add(loc.id)
                    matched_assets.add(loc.asset_id)
                    if key not in matched:
                        matched[key] = {
                            "asset_id": loc.asset_id,
                            "location_id": loc.id,
                            "rule": frule,
                            "hit": hit,
                        }

    run.matched_location_count = len(matched_location_ids)
    run.matched_asset_count = len(matched_assets)
    session.commit()

    # ---- 写入（upsert 幂等 + savepoint 隔离 + 批间取消检查）----
    created = 0
    existing_ids: set[int] = set()
    if run.dry_run:
        existing_keys = set(
            session.execute(
                select(LegacyUsageEvidence.evidence_key).where(
                    LegacyUsageEvidence.evidence_key.in_(list(matched.keys()))
                )
            ).scalars()
        ) if matched else set()
        created = len([k for k in matched if k not in existing_keys])
        existing_count = len(existing_keys)
    else:
        items = list(matched.items())
        for start in range(0, len(items), COMMIT_BATCH):
            if _cancelled(session, run):
                return _finish_cancelled(
                    session, run,
                    {
                        "matched_location_count": len(matched_location_ids),
                        "matched_asset_count": len(matched_assets),
                        "created_evidence_count": created,
                        "existing_evidence_count": len(existing_ids),
                    },
                    errors,
                )
            for key, m in items[start:start + COMMIT_BATCH]:
                frule: FrozenRule = m["rule"]
                hit = m["hit"]
                now = utcnow()
                try:
                    # savepoint：单条意外错误只回滚本条，绝不回滚批内已成功行
                    with session.begin_nested():
                        stmt = (
                            pg_insert(LegacyUsageEvidence)
                            .values(
                                asset_id=m["asset_id"],
                                asset_location_id=m["location_id"],
                                rule_id=frule.rule_id,
                                import_run_id=run.id,
                                evidence_key=key,
                                rule_version=frule.rule_version,
                                evidence_type=hit.evidence_type,
                                matched_target=hit.match_target,
                                matched_component=hit.matched_component,
                                rule_snapshot=_snapshot_dict(run, frule),
                                review_status="pending",
                                observation_count=1,
                                first_observed_at=now,
                                last_observed_at=now,
                                created_at=now,
                                updated_at=now,
                            )
                            .on_conflict_do_update(
                                constraint="uq_legacy_evidence_key",
                                # 已存在：只原子累加观察信息 —— 绝不触碰
                                # review_status/review_note/reviewed_at/
                                # actor_label/rule_snapshot
                                set_={
                                    "observation_count":
                                        LegacyUsageEvidence.observation_count + 1,
                                    "last_observed_at": now,
                                    "import_run_id": run.id,
                                    "updated_at": now,
                                },
                            )
                            .returning(
                                LegacyUsageEvidence.id,
                                LegacyUsageEvidence.review_status,
                                text("(xmax = 0) AS inserted"),
                            )
                        )
                        ev_id, review_status, inserted = session.execute(stmt).one()
                        session.add(
                            LegacyUsageEvidenceEvent(
                                evidence_id=ev_id,
                                action="detected" if inserted else "observed_again",
                                # observed_again 前后均为当前人工状态（未被触碰）
                                before_status=None if inserted else review_status,
                                after_status=review_status,
                            )
                        )
                    if inserted:
                        created += 1
                    else:
                        existing_ids.add(ev_id)
                except Exception as exc:  # noqa: BLE001 - savepoint 已回滚本条
                    errors.append(_truncate(f"evidence {key[:12]}: {exc}"))
            # 批提交（真实落库后再更新计数）
            run.created_evidence_count = created
            run.existing_evidence_count = len(existing_ids)
            session.commit()
            _after_batch(session, run)
        existing_count = len(existing_ids)

    if _cancelled(session, run):
        return _finish_cancelled(
            session, run,
            {
                "matched_location_count": len(matched_location_ids),
                "matched_asset_count": len(matched_assets),
                "created_evidence_count": created,
                "existing_evidence_count": existing_count,
            },
            errors,
        )

    run.created_evidence_count = created
    run.existing_evidence_count = existing_count
    run.error_count = len(errors)
    run.error_summary = "; ".join(errors[:10]) or None
    run.completed_at = utcnow()
    run.status = "completed_with_errors" if errors else "completed"
    session.commit()
    return {
        "run_id": run.id,
        "status": run.status,
        "created": created,
        "existing": existing_count,
        "errors": len(errors),
        "dry_run": run.dry_run,
    }


def _snapshot_dict(run: LegacyUsageImportRun, frule: FrozenRule) -> dict[str, Any]:
    """证据上的规则快照 = run 快照中该规则的原样条目（含展示名，冻结不再解释）。"""
    for snap in run.rule_snapshot or []:
        if isinstance(snap, dict) and snap.get("snapshot_hash") == frule.snapshot_hash:
            return snap
    # 理论不可达（frule 即由 run 快照重建）；兜底存语义字段
    return {
        "rule_id": frule.rule_id,
        "rule_version": frule.rule_version,
        "match_target": frule.match_target,
        "match_operator": frule.match_operator,
        "normalized_pattern": frule.normalized_pattern,
        "case_sensitive": frule.case_sensitive,
        "source_directory_id": frule.source_directory_id,
        "include_present_locations": frule.include_present_locations,
        "include_missing_locations": frule.include_missing_locations,
        "include_historical_locations": frule.include_historical_locations,
        "snapshot_hash": frule.snapshot_hash,
    }
