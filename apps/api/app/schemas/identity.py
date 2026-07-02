"""PR-C 素材身份 / 位置历史 / 指纹任务 / 分析代次 schema。

安全：绝不向前端返回绝对路径——位置只暴露 source root 显示名 + 相对路径 + 状态；
哈希默认只给缩短形式（完整哈希不进列表/日志）。
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class AssetLocationOut(BaseModel):
    id: int
    source_root_id: int
    source_root_name: str | None = None
    relative_path: str
    location_status: str
    is_primary: bool
    file_size: int | None
    first_seen_at: datetime
    last_seen_at: datetime
    missing_at: datetime | None
    verified_at: datetime | None

    model_config = {"from_attributes": True}


class AssetIdentityOut(BaseModel):
    """素材身份汇总（全部为只读派生值）。"""

    asset_id: int
    fingerprint_state: str
    quick_fingerprint_short: str | None = None
    quick_fingerprint_version: str | None = None
    full_hash_short: str | None = None
    full_hash_algorithm: str | None = None
    full_hash_available: bool = False
    content_size: int | None = None
    fingerprinted_at: datetime | None = None
    fingerprint_error: str | None = None

    location_count: int = 0
    present_location_count: int = 0
    missing_location_count: int = 0
    conflict_location_count: int = 0
    primary_location: AssetLocationOut | None = None
    locations: list[AssetLocationOut] = []

    current_generation: int | None = None
    historical_generation_count: int = 0


class FingerprintRequest(BaseModel):
    kind: str = Field(default="full", pattern="^(quick|full)$")


class BatchFingerprintRequest(BaseModel):
    asset_ids: list[int] = Field(min_length=1, max_length=500)
    kind: str = Field(default="full", pattern="^(quick|full)$")


class FingerprintJobOut(BaseModel):
    id: int
    kind: str
    status: str
    total_count: int
    completed_count: int
    skipped_count: int
    failed_count: int
    progress: int
    error_message: str | None
    results: dict[str, str] | None = None
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None

    model_config = {"from_attributes": True}


class AnalysisGenerationOut(BaseModel):
    """一次镜头分析代次（数据来源 MediaProcessingRun + Shot 聚合）。"""

    generation: int
    run_id: int
    status: str
    is_current: bool = False
    shot_count: int = 0
    usage_referenced_count: int = 0  # 被 FinalVideoUsage 引用的镜头数（历史审计事实）
    created_at: datetime | None = None
    finished_at: datetime | None = None


class AnalysisGenerationsOut(BaseModel):
    asset_id: int
    current_generation: int | None
    items: list[AnalysisGenerationOut]
