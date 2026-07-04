"""PR-F：产品视觉识别实验 API 契约（实验能力；候选 ≠ 确认）。"""

from __future__ import annotations

from pydantic import BaseModel, Field


class VisualStatusOut(BaseModel):
    enabled: bool
    provider: str
    model_id: str
    device: str
    ready: bool
    unavailable_reason: str | None = None
    eligible_family_count: int
    eligible_reference_count: int
    total_family_count: int
    thresholds: dict
    experimental: bool = True  # 恒 true：本能力为实验性，阈值未经生产校准


class VisualModelOut(BaseModel):
    provider: str
    model_id: str
    dimension: int
    device: str
    license: str | None = None
    notes: str | None = None


class ReferenceCoverageItem(BaseModel):
    family_id: int
    family_code: str
    family_name: str
    onboarding_status: str
    eligible: bool
    ineligible_reason: str | None = None
    reference_count: int
    angle_coverage: list[str]
    source_levels: list[str]


class ReferenceCoverageOut(BaseModel):
    items: list[ReferenceCoverageItem]
    eligible_count: int
    total_count: int
    min_references: int


class CandidateRequest(BaseModel):
    top_k: int | None = Field(default=None, ge=1, le=20)
    target_level: str = "family"      # 本阶段仅 family
    min_score: float | None = Field(default=None, ge=0.0, le=1.0)
    min_margin: float | None = Field(default=None, ge=0.0, le=1.0)
    aggregation: str = "top_k_mean"   # max | top_k_mean | weighted_top_k_mean
    include_explanation: bool = True


class FamilyCandidateOut(BaseModel):
    target_level: str
    target_id: int
    family_code: str
    family_name: str
    score: float
    best_reference_id: int | None
    matched_angles: list[str]
    reference_count: int
    embedded_reference_count: int
    aggregation: str
    source_levels: list[str]


class CandidateResponse(BaseModel):
    decision: str
    candidates: list[FamilyCandidateOut]
    top1_score: float | None
    top2_score: float | None
    margin: float | None
    thresholds: dict
    aggregation: str
    model: str
    provider: str
    device: str
    reference_snapshot: dict          # eligible_family_count / reference_count
    confusion_warning: dict | None = None
    unavailable_reason: str | None = None
    query: dict = {}                  # shot_id/generation 或 upload 元信息（无路径）
    experimental_notice: str = (
        "这是实验性视觉候选，不会自动修改产品归属。候选结果必须由人工核对。"
    )


class BenchmarkSampleIn(BaseModel):
    kind: str = "reference"           # reference | shot
    reference_id: int | None = None
    shot_id: int | None = None
    ground_truth_family_id: int | None = None
    is_unknown: bool = False
    sample_type: str = ""
    source: str = ""


class BenchmarkRequest(BaseModel):
    samples: list[BenchmarkSampleIn] = Field(min_length=1, max_length=500)
    aggregation: str = "top_k_mean"
    include_outcomes: bool = False


class BenchmarkResponse(BaseModel):
    total_samples: int
    evaluated: int
    skipped: int
    product_samples: int
    unknown_samples: int
    family_count: int
    metrics: dict
    per_family: dict
    groups: dict
    confusion_matrix: dict
    curves: dict
    data_gaps: list
    outcomes: list = []
    model: str
    provider: str
    experimental_notice: str = (
        "Benchmark 为实验性离线评测；样本不足时结论不具统计意义，不代表生产精度。"
    )
