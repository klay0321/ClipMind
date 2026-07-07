"""Gate B：搜索 / 画面描述匹配 / 建议 / 索引状态 的 API schema。

设计：请求体的枚举字段（``aspect_ratios`` / ``review_statuses`` / ``search_mode``）直接用受控枚举，
非法值由 FastAPI/pydantic 在入口拒绝（422），从源头杜绝注入。响应里每个 item 暴露分项分数与
规则派生解释，便于 Gate C 渲染与人工核对，绝不伪造 AI 文案。
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from clipmind_shared.models.enums import ReviewStatus
from clipmind_shared.search.query import AspectRatio, ParsedSearchQuery, SearchMode
from pydantic import BaseModel, Field

# 页大小硬上限（防御超大分页）
MAX_PAGE_SIZE = 100


# ============================ 请求 ============================


class ShotSearchRequest(BaseModel):
    query: str = ""
    # 结构化召回/过滤（与解析结果合并；显式条件优先）
    product_ids: list[int] = []
    brands: list[str] = []
    models: list[str] = []
    skus: list[str] = []
    scenes: list[str] = []
    actions: list[str] = []
    shot_types: list[str] = []
    marketing_uses: list[str] = []
    quality_levels: list[str] = []
    include_risks: list[str] = []
    exclude_risks: list[str] = []
    duration_min: float | None = Field(default=None, ge=0)
    duration_max: float | None = Field(default=None, ge=0)
    aspect_ratios: list[AspectRatio] = []
    review_statuses: list[ReviewStatus] = []
    confirmed_only: bool = False
    include_excluded: bool = False
    stale: bool | None = None
    source_directory_id: int | None = None
    created_from: datetime | None = None
    created_to: datetime | None = None
    # PM：产品素材关系过滤（hard filter，不参与相关性分数；Shot 继承语义）
    product_family_id: int | None = None
    product_variant_id: int | None = None
    has_product_assignment: bool | None = None
    unassigned_only: bool = False
    search_mode: SearchMode = SearchMode.HYBRID
    # 固定方向（brief 允许）：relevance/quality/latest 降序，duration 升序；latest 兼容旧名 newest。
    sort: str = "relevance"  # relevance | latest | duration | quality
    page: int = Field(default=1, ge=1)
    page_size: int = Field(default=24, ge=1, le=MAX_PAGE_SIZE)

    # ---- PR-E 使用感知（向后兼容；default 模式与旧行为逐位一致）----
    # default | prefer_unused | only_never_confirmed | exclude_high_frequency
    # | least_recently_used
    usage_mode: str = "default"
    usage_scope: str = "combined"  # shot | asset | combined（Shot 主信号，Asset 轻量辅助）
    max_confirmed_usage_count: int | None = Field(default=None, ge=0, le=1000)
    min_days_since_last_use: int | None = Field(default=None, ge=0, le=3650)
    exclude_recently_used_days: int | None = Field(default=None, ge=0, le=3650)
    include_legacy_unknown: bool = True   # 展示历史弱证据提示；default 模式不参与排序
    usage_preset: str = "balanced"        # balanced | strong_unused | relevance_first
    usage_weights: dict[str, float] | None = None  # 受约束的请求级 override（越权 422）
    include_usage_explanation: bool = True  # false 时省略 usage 块与 reasons


class DescriptionMatchRequest(BaseModel):
    target_description: str = Field(..., min_length=1)
    product_id: int | None = None
    limit: int = Field(default=20, ge=1, le=MAX_PAGE_SIZE)
    minimum_score: float = Field(default=0.0, ge=0.0, le=1.0)
    exclude_risks: list[str] = []
    confirmed_only: bool = False
    allow_similar_scene: bool = True
    allow_similar_action: bool = True
    duration_min: float | None = Field(default=None, ge=0)
    duration_max: float | None = Field(default=None, ge=0)
    aspect_ratios: list[AspectRatio] = []
    # 脚本匹配（Gate B）置 True：忽略从 target_description 文本中解析出的时长（如"不超过3秒"），
    # 不据此硬过滤镜头——时长是软偏好，由剪辑清单时长建议单独处理。默认 False 保持 PR-04 行为。
    suppress_parsed_duration: bool = False
    # 显式结构化软信号（默认空 → 行为同既有，仅靠解析器抽取）。供脚本匹配（Gate B）把段落
    # structured_requirements 精确注入软召回/解释，避免依赖脆弱的文本解析；allow_similar_*=False
    # 时场景/动作会被升格为硬过滤（既有 require_scene/require_action 机制），不静默放宽硬约束。
    scenes: list[str] = []
    actions: list[str] = []
    shot_types: list[str] = []
    marketing_uses: list[str] = []
    quality_levels: list[str] = []
    negative_terms: list[str] = []   # 否定关键词 → 词法硬排除（含该词的镜头被剔除）
    brands: list[str] = []
    models: list[str] = []
    skus: list[str] = []


# ============================ 响应：item ============================


class AssetBrief(BaseModel):
    id: int
    filename: str
    duration: float | None = None
    width: int | None = None
    height: int | None = None
    orientation: str | None = None
    source_directory_id: int | None = None


class ProductBrief(BaseModel):
    id: int
    name: str
    brand: str | None = None
    model: str | None = None
    sku: str | None = None
    match_kind: str | None = None  # sku | model | brand | name | alias | associated


class SearchResultItem(BaseModel):
    shot_id: int
    asset_id: int
    sequence_no: int
    start_time: float
    end_time: float
    duration: float
    status: str

    asset: AssetBrief
    preview_url: str | None = None
    thumbnail_url: str | None = None
    keyframe_url: str | None = None
    download_url: str | None = None

    product: ProductBrief | None = None

    # 综合分与分项分（[0,1]；缺失通道为 null，绝不伪造 0）
    score: float
    match_percent: float  # 对外可读匹配度（一位小数）
    semantic_score: float | None = None
    lexical_score: float | None = None
    tag_score: float | None = None
    product_score: float | None = None
    quality_score: float = 0.0
    review_bonus: float = 0.0
    risk_penalty: float = 0.0

    # 规则派生解释
    matched_reasons: list[str] = []
    unmatched_requirements: list[str] = []

    # ---- PR-E 使用感知（可选；不覆盖原始相似度字段）----
    # base_score=原融合相关性分；usage_adjustment∈[-0.35,0.35]；
    # final_score=base+adjustment（default 模式 adjustment=0，final==base==score）
    base_score: float | None = None
    usage_adjustment: float | None = None
    final_score: float | None = None
    usage: UsageInfoOut | None = None
    usage_reasons: list[UsageReasonOut] = []
    risk_warnings: list[str] = []

    review_status: str | None = None
    review_is_stale: bool = False
    embedding_degraded: bool = False


class DescriptionMatchItem(SearchResultItem):
    """画面描述匹配 item：在搜索 item 基础上增加描述匹配维度。

    复用父类 ``matched_reasons`` / ``unmatched_requirements`` / ``risk_warnings``；
    ``matched_requirements`` 为面向"目标描述要求"的命中视图（= matched_reasons）。
    """

    target_requirements: list[str] = []
    matched_requirements: list[str] = []
    requires_human_confirmation: bool = False
    recommendation_level: str = "low"  # high | medium | low | not_recommended


# ============================ 响应：包裹 ============================


class UsageInfoOut(BaseModel):
    """使用特征展示块（正式=confirmed 去重成片数；legacy 绝不显示成正式次数）。"""

    shot_confirmed_usage_count: int = 0
    shot_distinct_final_video_count: int = 0
    asset_confirmed_usage_count: int = 0
    asset_distinct_final_video_count: int = 0
    asset_used_shot_count: int = 0
    asset_total_current_shot_count: int = 0
    last_confirmed_used_at: datetime | None = None
    days_since_last_confirmed_use: float | None = None
    accepted_legacy_evidence_count: int = 0
    pending_formal_count: int = 0
    usage_state: str = "never_confirmed_used"


class UsageReasonOut(BaseModel):
    code: str
    adjustment: float
    message: str


class UsageSearchStatsOut(BaseModel):
    """候选池与过滤可观测性（防饥饿证据；不含真实查询内容）。"""

    requested_top_k: int = 0
    candidate_pool_size: int = 0
    filtered_count: int = 0
    returned_count: int = 0
    candidate_limit_reached: bool = False
    expansion_rounds: int = 0
    usage_projection_ms: int = 0


class ShotSearchResponse(BaseModel):
    items: list[SearchResultItem]
    # total = 进入融合排序、可分页的候选数。truncated=false 时即满足召回的精确匹配数；
    # truncated=true 时为候选池上界下的下界（候选被截断，存在更多匹配未进池）。
    total: int
    # filtered_total = 满足硬结构化过滤的精确总数（"可检索宇宙"，独立于软召回），供前端展示参考。
    filtered_total: int
    truncated: bool
    page: int
    page_size: int
    search_mode_used: str
    parser_status: str
    parser_provider: str
    embedding_status: str  # ok | degraded | unavailable
    degraded: bool
    degradation_reasons: list[str]
    elapsed_ms: int
    query_plan_summary: dict
    usage_stats: UsageSearchStatsOut | None = None
    parsed_query: ParsedSearchQuery


class DescriptionMatchResponse(BaseModel):
    items: list[DescriptionMatchItem]
    # total = 满足硬过滤条件的候选总数（不含 minimum_score 过滤；minimum_score 仅作用于 items）
    total: int
    filtered_total: int
    truncated: bool
    minimum_score: float
    target_requirements: list[str]
    search_mode_used: str
    parser_status: str
    embedding_status: str
    degraded: bool
    degradation_reasons: list[str]
    elapsed_ms: int


class SearchSuggestion(BaseModel):
    value: str
    type: str  # product | brand | scene | action | marketing | shot_type | tag


class SuggestionsResponse(BaseModel):
    items: list[SearchSuggestion]


class IndexStatusResponse(BaseModel):
    total_shots: int
    indexed_documents: int
    excluded_documents: int
    completed_embeddings: int
    degraded_embeddings: int
    failed_embeddings: int
    pending_embeddings: int
    current_embedding_version: str
    embedding_version_matched: int       # completed 且版本与当前 provider 一致
    embedding_version_mismatched: int    # completed 但版本不一致（需重嵌）
    stale_documents: int
    last_indexed_at: datetime | None = None
    provider_healthy: bool
    provider_detail: str = ""


class ShotCompletenessResponse(BaseModel):
    """全库镜头拆解完整度聚合（只读）。供镜头工作台顶部展示真实处理进度。

    所有计数均来自真实表统计，前端不再估算/伪造。
    """

    total_assets: int          # 已入库素材数
    total_shots: int           # READY 镜头总数
    ai_analyzed_shots: int     # 已完成 AI 分析的镜头数（去重）
    ai_failed_shots: int       # AI 分析失败的镜头数（去重）
    pending_review_shots: int  # 待人工确认（review_status=pending_review）
    confirmed_shots: int       # 已确认（confirmed/modified）
    searchable_shots: int      # 已建立语义索引、可检索（is_searchable）
    risk_shots: int            # 命中风险标签的镜头数


class RebuildAcceptedResponse(BaseModel):
    accepted: bool
    scope: str               # shot | asset | sweep | backfill
    target_id: int | None = None
    force_reembed: bool = False
    only_failed: bool = False
    celery_task_id: str | None = None
    detail: str = ""


# ============================ P2a：素材级检索（整视频 / 图片） ============================


class AssetSearchRequest(BaseModel):
    query: str = Field(default="", max_length=500)
    media_kind: Literal["video", "image"] | None = None
    source_directory_id: int | None = None
    # 目录产品过滤（product_media_link 素材级关联）
    product_family_id: int | None = None
    page: int = Field(default=1, ge=1)
    page_size: int = Field(default=20, ge=1, le=MAX_PAGE_SIZE)


class AssetSearchResultItem(BaseModel):
    asset_id: int
    filename: str
    media_kind: str
    duration: float | None
    source_directory_id: int
    has_poster: bool
    score: float
    semantic_score: float | None = None
    lexical_score: float | None = None
    document_excerpt: str | None = None
    effective_source: str | None = None  # ai（图片）| aggregate（视频聚合）
    product_names: list[str] = []


class AssetSearchResponse(BaseModel):
    items: list[AssetSearchResultItem]
    total: int
    page: int
    page_size: int
    embedding_status: str
    elapsed_ms: int
