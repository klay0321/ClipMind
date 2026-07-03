"""PR-C 扫描移动/复制识别（场景 A–E，docs/ASSET_IDENTITY.md）。

场景语义（对齐冻结的内容身份规则）：
- A 路径不变、内容不变：touch 位置与投影，继续用原 Asset，不重新分析；
- B 路径不变、内容变化（quick_hash 变）：位置标 conflict + 指纹标 stale，
  **不静默覆盖原 Asset 身份**、不迁移血缘；人工经单素材重扫（rescan）显式接受替换；
- C 旧路径消失、新路径出现、**完整 SHA256 相同**：同一 Asset 移动/改名——
  旧位置转 historical、新位置成为 present primary，Asset ID 与全部业务数据保留；
- D 旧路径仍在、新路径出现、完整 SHA256 相同：复制/多位置——同一 Asset 增加
  第二个非 primary 位置，不重复分析；
- E 只有 quick fingerprint 相同：仅候选，**不自动认定同一 Asset**——新建 Asset
  并记 ambiguous（等待完整校验/人工处理），绝不自动合并有业务数据的 Asset。

约束：
- 移动识别只信 full SHA256（权威字节身份）；quick fingerprint 只筛候选；
- 单次扫描的现场 full hash 计算受总字节预算限制（超出转 ambiguous）；
- 明细只记录 asset/location id 与 root 下安全相对路径，绝不记录绝对路径。
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from clipmind_shared.db.base import utcnow
from clipmind_shared.fingerprint import (
    FileChangedDuringHashing,
    compute_full_sha256,
    compute_quick_fingerprint,
)
from clipmind_shared.models import Asset, AssetLocation, Shot
from clipmind_shared.models.enums import AssetStatus, ShotStatus
from sqlalchemy import select
from sqlalchemy.orm import Session


@dataclass
class ReconcileStats:
    """单次扫描的移动/复制识别结果（八类计数 + 脱敏明细）。"""

    new_assets: int = 0
    existing_assets: int = 0
    moved_locations: int = 0
    additional_locations: int = 0
    missing_locations: int = 0
    content_conflicts: int = 0
    ambiguous_candidates: int = 0
    errors: int = 0

    moved: list[dict[str, Any]] = field(default_factory=list)
    copied: list[dict[str, Any]] = field(default_factory=list)
    conflicts: list[dict[str, Any]] = field(default_factory=list)
    ambiguous: list[dict[str, Any]] = field(default_factory=list)

    # 现场 full hash 预算（字节）
    full_hash_budget: int = 0
    full_hash_spent: int = 0

    def counts(self) -> dict[str, int]:
        return {
            "new_assets": self.new_assets,
            "existing_assets": self.existing_assets,
            "moved_locations": self.moved_locations,
            "additional_locations": self.additional_locations,
            "missing_locations": self.missing_locations,
            "content_conflicts": self.content_conflicts,
            "ambiguous_candidates": self.ambiguous_candidates,
            "errors": self.errors,
        }

    def to_jsonb(self) -> dict[str, Any]:
        return {
            "counts": self.counts(),
            "moved": self.moved[:200],
            "copied": self.copied[:200],
            "conflicts": self.conflicts[:200],
            "ambiguous": self.ambiguous[:200],
        }


def find_active_location(
    session: Session, source_root_id: int, normalized_path: str
) -> AssetLocation | None:
    """按 (root, normalized_path) 查活动（非 historical）位置。"""
    return (
        session.execute(
            select(AssetLocation).where(
                AssetLocation.source_root_id == source_root_id,
                AssetLocation.normalized_path == normalized_path,
                AssetLocation.location_status != "historical",
            )
        )
        .scalars()
        .first()
    )


def touch_location(loc: AssetLocation, st: os.stat_result) -> None:
    loc.last_seen_at = utcnow()
    loc.file_size = st.st_size
    loc.mtime_ns = st.st_mtime_ns
    if loc.location_status == "missing":
        loc.location_status = "present"
        loc.missing_at = None


def mark_content_conflict(
    session: Session, loc: AssetLocation, asset: Asset, stats: ReconcileStats
) -> None:
    """场景 B：同路径内容被替换——不静默覆盖身份，等待人工确认（rescan=显式接受）。"""
    loc.location_status = "conflict"
    loc.last_seen_at = utcnow()
    asset.fingerprint_state = "stale"
    stats.content_conflicts += 1
    stats.conflicts.append(
        {"asset_id": asset.id, "location_id": loc.id, "path": loc.relative_path}
    )


def add_primary_location(
    session: Session,
    asset: Asset,
    *,
    source_root_id: int,
    relative_path: str,
    normalized_path: str,
    st: os.stat_result,
    is_primary: bool = True,
) -> AssetLocation:
    loc = AssetLocation(
        asset_id=asset.id,
        source_root_id=source_root_id,
        relative_path=relative_path,
        normalized_path=normalized_path,
        location_status="present",
        is_primary=is_primary,
        file_size=st.st_size,
        mtime_ns=st.st_mtime_ns,
    )
    session.add(loc)
    return loc


def _project_asset_to_location(
    asset: Asset, *, source_root_id: int, relative_path: str, normalized_path: str,
    st: os.stat_result,
) -> None:
    """把 Asset 的兼容投影字段切到新 primary 位置（旧 API/前端继续可用）。"""
    asset.source_directory_id = source_root_id
    asset.relative_path = relative_path
    asset.normalized_relative_path = normalized_path
    asset.filename = os.path.basename(relative_path)
    asset.file_size = st.st_size
    asset.modified_at = datetime.fromtimestamp(st.st_mtime, tz=UTC)
    asset.last_seen_at = utcnow()


def relink_moved_asset(
    session: Session,
    asset: Asset,
    *,
    source_root_id: int,
    relative_path: str,
    normalized_path: str,
    st: os.stat_result,
    scan_quick_hash: str,
    stats: ReconcileStats,
) -> AssetLocation:
    """场景 C：full SHA256 相同且旧位置全部缺失——同一 Asset 移动/改名。

    Asset ID、产品归属、分析、收藏、项目与使用血缘全部保留；旧位置转 historical。
    """
    old_paths: list[str] = []
    active = (
        session.execute(
            select(AssetLocation).where(
                AssetLocation.asset_id == asset.id,
                AssetLocation.location_status != "historical",
            )
        )
        .scalars()
        .all()
    )
    for old in active:
        old_paths.append(old.relative_path)
        old.location_status = "historical"
        old.is_primary = False
        if old.missing_at is None:
            old.missing_at = utcnow()
    session.flush()  # 先释放 primary/活动路径唯一槽位

    loc = add_primary_location(
        session,
        asset,
        source_root_id=source_root_id,
        relative_path=relative_path,
        normalized_path=normalized_path,
        st=st,
        is_primary=True,
    )
    loc.verified_at = utcnow()
    _project_asset_to_location(
        asset,
        source_root_id=source_root_id,
        relative_path=relative_path,
        normalized_path=normalized_path,
        st=st,
    )
    asset.quick_hash = scan_quick_hash
    if asset.status == AssetStatus.SOURCE_MISSING:
        # 文件已找回（内容经完整哈希验证未变）：按是否已有当前代次 ready 镜头恢复状态
        has_ready = (
            session.execute(
                select(Shot.id).where(
                    Shot.asset_id == asset.id,
                    Shot.status == ShotStatus.READY,
                    Shot.retired_at.is_(None),
                ).limit(1)
            ).first()
            is not None
        )
        asset.status = AssetStatus.SHOT_SPLIT if has_ready else AssetStatus.INDEXED
    stats.moved_locations += 1
    stats.moved.append(
        {"asset_id": asset.id, "from": old_paths, "to": relative_path}
    )
    return loc


def add_copy_location(
    session: Session,
    asset: Asset,
    *,
    source_root_id: int,
    relative_path: str,
    normalized_path: str,
    st: os.stat_result,
    stats: ReconcileStats,
) -> AssetLocation:
    """场景 D：full SHA256 相同且旧位置仍在——复制/多位置，不重复分析。"""
    loc = add_primary_location(
        session,
        asset,
        source_root_id=source_root_id,
        relative_path=relative_path,
        normalized_path=normalized_path,
        st=st,
        is_primary=False,
    )
    loc.verified_at = utcnow()
    stats.additional_locations += 1
    stats.copied.append(
        {"asset_id": asset.id, "path": relative_path}
    )
    return loc


def match_by_content(
    session: Session,
    *,
    abs_path: str,
    st: os.stat_result,
    stats: ReconcileStats,
) -> tuple[Asset | None, bool, str | None, list[int]]:
    """新路径的内容身份匹配。

    返回 (matched_asset, matched_has_present_location, quick_fp_value, ambiguous_ids)：
    - matched_asset 非 None：full SHA256 已验证相同（权威）；
    - ambiguous_ids：quick fingerprint 命中但无法当场用完整哈希验证的候选。
    """
    try:
        qfp = compute_quick_fingerprint(abs_path)
    except (FileChangedDuringHashing, OSError):
        stats.errors += 1
        return None, False, None, []

    candidates = (
        session.execute(
            select(Asset).where(
                Asset.quick_fingerprint == qfp.value,
                Asset.quick_fingerprint.is_not(None),
            ).order_by(Asset.id)
        )
        .scalars()
        .all()
    )
    if not candidates:
        return None, False, qfp.value, []

    ambiguous_ids: list[int] = []
    new_full: str | None = None
    for cand in candidates:
        if not cand.full_hash or cand.fingerprint_state == "stale":
            ambiguous_ids.append(cand.id)
            continue
        # 需要现场完整哈希验证：受单次扫描字节预算限制
        if new_full is None:
            if stats.full_hash_spent + st.st_size > stats.full_hash_budget:
                ambiguous_ids.append(cand.id)
                continue
            try:
                new_full = compute_full_sha256(abs_path).value
                stats.full_hash_spent += st.st_size
            except (FileChangedDuringHashing, OSError):
                stats.errors += 1
                ambiguous_ids.append(cand.id)
                continue
        if new_full == cand.full_hash:
            has_present = (
                session.execute(
                    select(AssetLocation.id).where(
                        AssetLocation.asset_id == cand.id,
                        AssetLocation.location_status == "present",
                    ).limit(1)
                ).first()
                is not None
            )
            return cand, has_present, qfp.value, []
        # full 不同：确证不同内容，不是候选
    return None, False, qfp.value, ambiguous_ids
