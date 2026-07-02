"""领域枚举。

枚举一次性建全（前向兼容），PR-01 只使用其中部分值；
PG 枚举后续追加 value 较麻烦，故先定义完整集合。
"""

from __future__ import annotations

from enum import StrEnum


class AssetStatus(StrEnum):
    """素材处理状态。"""

    # ---- PR-01 实际使用 ----
    DISCOVERED = "discovered"        # 已发现，待探测
    INDEXED = "indexed"              # FFprobe 成功，已索引
    ERROR = "error"                  # 探测失败
    SOURCE_MISSING = "source_missing"  # 源文件缺失

    # ---- 后续 PR 预留 ----
    PENDING = "pending"
    PROCESSING = "processing"
    SHOT_SPLIT = "shot_split"
    AI_ANALYZING = "ai_analyzing"
    PENDING_REVIEW = "pending_review"
    SEARCHABLE = "searchable"
    PAUSED = "paused"
    ARCHIVED = "archived"


class ScanStatus(StrEnum):
    """SourceDirectory.scan_status —— 目录维度的扫描状态。"""

    NEVER_SCANNED = "never_scanned"
    QUEUED = "queued"
    SCANNING = "scanning"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class ScanRunStatus(StrEnum):
    """ScanRun.status —— 单次扫描运行的状态。"""

    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


# 视为"活动中"的扫描运行状态（用于部分唯一索引与并发判断）
ACTIVE_SCAN_RUN_STATUSES: tuple[ScanRunStatus, ...] = (
    ScanRunStatus.QUEUED,
    ScanRunStatus.RUNNING,
)


# ============================================================
# PR-02 拆镜头 / 派生文件相关枚举
# ============================================================


class ShotStatus(StrEnum):
    """Shot.status —— 单个镜头的派生状态。

    只有 READY 的镜头才对外可见、可预览/下载；其余为过程态或失败态，
    由下次分析在启动时回收。
    """

    PENDING = "pending"        # 已落库，派生文件尚未就绪
    PROCESSING = "processing"  # 文件生成/搬运中（对外隐藏）
    READY = "ready"            # 派生文件齐备，可对外
    FAILED = "failed"          # 该镜头派生失败


class MediaRunStatus(StrEnum):
    """MediaProcessingRun.status —— 单次镜头分析运行的状态。"""

    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class ExportStatus(StrEnum):
    """Export.status —— 单次片段导出的状态。"""

    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


# 视为"活动中"的镜头分析运行状态（用于部分唯一索引与并发判断）
ACTIVE_MEDIA_RUN_STATUSES: tuple[MediaRunStatus, ...] = (
    MediaRunStatus.QUEUED,
    MediaRunStatus.RUNNING,
)

# MediaProcessingRun.current_step 的取值（仅作进度展示，存为字符串而非枚举类型）
STEP_PROBING = "probing"
STEP_DETECTING = "detecting"
STEP_DERIVING = "deriving"
STEP_FINALIZING = "finalizing"


# ============================================================
# PR-03A AI 分析相关枚举
# ============================================================


class AIRunStatus(StrEnum):
    """AIAnalysisRun.status —— 素材级 AI 分析运行的状态。"""

    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    PARTIAL = "partial"      # 运行完成，但部分镜头失败/降级
    FAILED = "failed"
    CANCELLED = "cancelled"


class AIShotAnalysisStatus(StrEnum):
    """AIShotAnalysis.status —— 单镜头 AI 分析当前结果的状态。"""

    PENDING = "pending"
    COMPLETED = "completed"
    DEGRADED = "degraded"    # 能力不足（如无图）降级，未做完整视觉分析
    FAILED = "failed"
    SKIPPED = "skipped"      # 输入指纹命中缓存，跳过（不重复计费）


class AICallStatus(StrEnum):
    """AICallLog.status —— 单次外部 provider 调用的结果。"""

    SUCCESS = "success"
    RETRY = "retry"
    FAILED = "failed"
    TIMEOUT = "timeout"
    RATE_LIMITED = "rate_limited"
    DEGRADED = "degraded"


# 视为"活动中"的 AI 分析运行状态（用于部分唯一索引与并发判断）
ACTIVE_AI_RUN_STATUSES: tuple[AIRunStatus, ...] = (
    AIRunStatus.QUEUED,
    AIRunStatus.RUNNING,
)


# ============================================================
# PR-03B 标签体系 / 产品库 / 人工审核相关枚举
# ============================================================


class ReviewStatus(StrEnum):
    """ShotReviewState.review_status —— 镜头人工审核当前状态。"""

    UNREVIEWED = "unreviewed"          # 未审核（用 AI 结果作临时有效结果）
    PENDING_REVIEW = "pending_review"  # 待审核（AI 标记需人工确认）
    CONFIRMED = "confirmed"            # 已确认（采用 AI 结果）
    MODIFIED = "modified"              # 已修改并确认（采用人工编辑结果）
    REJECTED = "rejected"             # 已驳回（AI 结果仅留审计，不进搜索/推荐）
    UNABLE = "unable"                 # 无法判断（不计高置信，不进推荐）


class TagType(StrEnum):
    """Tag.tag_type —— 标签维度（PRD 7.7）。"""

    PRODUCT = "product"
    SCENE = "scene"
    ACTION = "action"
    SHOT_TYPE = "shot_type"
    MARKETING = "marketing"
    QUALITY = "quality"
    RISK = "risk"


class TagSource(StrEnum):
    """ShotTag.source / AssetProduct.source —— 标签/关联来源。"""

    AI = "ai"
    HUMAN = "human"


class ReviewAction(StrEnum):
    """ReviewEvent.action —— 审核动作（append-only 审计）。"""

    CONFIRM = "confirm"
    MODIFY = "modify"
    REJECT = "reject"
    UNABLE = "unable"
    REOPEN = "reopen"


class ProductStatus(StrEnum):
    """Product.status。"""

    ACTIVE = "active"
    ARCHIVED = "archived"


# 视为"已人工确认有效结果"的审核状态（有效结果优先采用人工）
HUMAN_EFFECTIVE_STATUSES: tuple[ReviewStatus, ...] = (
    ReviewStatus.CONFIRMED,
    ReviewStatus.MODIFIED,
)
# 默认不进入搜索/推荐的审核状态
EXCLUDED_FROM_SEARCH_STATUSES: tuple[ReviewStatus, ...] = (
    ReviewStatus.REJECTED,
    ReviewStatus.UNABLE,
)


# ============================================================
# PR-04 语义检索（检索文档 / 嵌入 / 索引）相关枚举
# ============================================================
#
# 文档状态与嵌入状态**正交**，分两列承载，避免单状态条件混乱：
# - document_status 决定一条镜头检索文档是否"可被检索"（is_searchable）；
# - embedding_status 决定它是否"可参与向量召回"。
# 关键语义（PR-04 Gate A.1）：embedding 不可用/为空/过期/Provider 暂不可用时，文档仍
# document_status=indexed、is_searchable=true，**继续参与词法/pg_trgm/标签/产品/结构化召回**，
# 仅 embedding_status=degraded、不参与向量召回。绝不因 Embedding 缺失而让镜头完全无法被搜索。


class SearchDocumentStatus(StrEnum):
    """ShotSearchDocument.document_status —— 检索文档（文本层）状态。"""

    PENDING = "pending"    # 文档待构建
    INDEXED = "indexed"    # 文档已构建且为当前有效；is_searchable=true，参与非向量召回
    EXCLUDED = "excluded"  # rejected/unable/非当前代次/业务排除；is_searchable=false，默认不返回


class SearchEmbeddingStatus(StrEnum):
    """ShotSearchDocument.embedding_status —— 嵌入（向量层）状态。"""

    PENDING = "pending"      # 待嵌入
    EMBEDDING = "embedding"  # 嵌入中
    COMPLETED = "completed"  # 向量就绪且身份匹配；可参与向量召回
    DEGRADED = "degraded"    # 嵌入不可用/为空/Provider 暂不可用；不参与向量召回（文本仍可检索）
    FAILED = "failed"        # 嵌入失败（待重试/sweeper 修复）


# 文档可被检索（任一非向量召回路径）的文档状态
SEARCHABLE_DOCUMENT_STATUS: SearchDocumentStatus = SearchDocumentStatus.INDEXED
# 可参与向量召回的嵌入状态（还须 embedding 非空且 embedding_version 与当前 Provider 一致）
VECTOR_READY_EMBEDDING_STATUS: SearchEmbeddingStatus = SearchEmbeddingStatus.COMPLETED


# ============================================================
# PR-05 脚本匹配 / 剪辑清单相关枚举
# ============================================================


class ScriptStatus(StrEnum):
    """ScriptProject.status —— 脚本项目生命周期（Gate A 到 PARSED；MATCHED 留 Gate B）。"""

    DRAFT = "draft"        # 已创建并存脚本，尚未拆段
    PARSING = "parsing"    # 拆段进行中
    PARSED = "parsed"      # 已拆段，段落就绪
    MATCHED = "matched"    # 已完成镜头匹配（Gate B）
    FAILED = "failed"      # 拆段失败


class ScriptParseStatus(StrEnum):
    """ScriptProject.parse_status —— 拆段解析状态（对外可见，绝不假装成功）。"""

    PENDING = "pending"      # 尚未解析
    OK = "ok"                # 解析成功（规则或 LLM）
    DEGRADED = "degraded"    # LLM 解析失败/超时/非法，已降级规则解析
    FAILED = "failed"        # 解析彻底失败


# ============================================================
# PR-06A 项目 / 收藏 / 素材集合 相关枚举
# ============================================================


class ProjectStatus(StrEnum):
    """Project.status —— 业务项目生命周期（PR-06A 只实现 active/archived）。

    archived 后项目只读：可查看/预览/恢复，禁止新增/删除/重排成员（service 层统一保护）。
    completed 等更多状态留待后续，不在 PR-06A 实现。
    """

    ACTIVE = "active"
    ARCHIVED = "archived"


# ============================================================
# PR-06B 导出中心 / 保存搜索 / 收藏 / 动态集合 相关枚举
# ============================================================


class SearchKind(StrEnum):
    """SavedSearch.search_kind / DynamicCollection.search_kind —— 保存的查询类型。

    决定 ``query`` JSONB 用哪个请求模型反序列化、re-run 时走哪个搜索服务。
    """

    SHOT_SEARCH = "shot_search"              # ShotSearchRequest（自然语言 + 结构化搜索）
    DESCRIPTION_MATCH = "description_match"  # DescriptionMatchRequest（画面描述匹配）


class FavoriteTargetType(StrEnum):
    """Favorite.target_type —— 可收藏对象类型（PRD §7.14.2 四类）。

    asset 关联 ``asset_id``；shot / search_result / script_match_result 最终都引用真实
    ``shot_id``（搜索结果/脚本候选解析到底层镜头），context 仅存安全来源快照。
    """

    ASSET = "asset"
    SHOT = "shot"
    SEARCH_RESULT = "search_result"
    SCRIPT_MATCH_RESULT = "script_match_result"


# 以 shot_id 为底层引用的收藏类型（asset 例外，用 asset_id）
SHOT_BASED_FAVORITE_TYPES: tuple[FavoriteTargetType, ...] = (
    FavoriteTargetType.SHOT,
    FavoriteTargetType.SEARCH_RESULT,
    FavoriteTargetType.SCRIPT_MATCH_RESULT,
)


# 统一导出中心的导出种类（kind 判别）
EXPORT_KIND_CLIP = "clip"      # Export（片段 MP4）
EXPORT_KIND_SCRIPT = "script"  # ScriptExport（剪辑清单多格式）
EXPORT_KIND_BUNDLE = "bundle"  # BundleExport（多镜头 ZIP）
EXPORT_KINDS: tuple[str, ...] = (EXPORT_KIND_CLIP, EXPORT_KIND_SCRIPT, EXPORT_KIND_BUNDLE)

# 脚本导出支持的格式（PRD §7.12.7）
SCRIPT_EXPORT_FORMATS: tuple[str, ...] = ("csv", "xlsx", "json", "markdown", "printable")


# ============================================================
# PR-A1 通用产品目录（Category → Family → Variant → SKU）
# ============================================================


class CatalogStatus(StrEnum):
    """通用产品目录节点生命周期（Category/Family/Variant/SKU 共用）。

    这是**节点状态**枚举（系统能力，稳定），**不是产品名称枚举**——
    新增任意产品只是插入数据行，绝不改动此枚举。
    """

    DRAFT = "draft"          # 草稿：运营录入中，不参与业务消费
    ACTIVE = "active"        # 已启用
    PAUSED = "paused"        # 暂停使用（保留关系）
    ARCHIVED = "archived"    # 归档（默认不出现在 active 列表，可恢复）
    MERGED = "merged"        # 已合并到另一节点（merged_into_id 指向 canonical，原节点保留）


# 默认从 active 列表中隐藏的目录状态
CATALOG_HIDDEN_STATUSES: tuple[CatalogStatus, ...] = (
    CatalogStatus.ARCHIVED,
    CatalogStatus.MERGED,
)
# 通用产品目录别名类型（受控业务集合）。存 String 列而非 pg_enum，
# 便于将来新增别名类型时免迁移；service 层按此集合校验。
CATALOG_ALIAS_TYPES: tuple[str, ...] = (
    "zh_name",         # 中文别名
    "en_name",         # 英文别名
    "short_name",      # 运营简称
    "folder_alias",    # 文件夹别名（仅候选线索，绝不作判定真值）
    "historical_name", # 历史名称（更名保留）
    "sku_alias",       # SKU 别名
)

# ---------------------------------------------------------------------------
# PR-A2 Gate A：动态属性与产品参考图（均存 String 列 + service 白名单，免迁移扩展）
# 这些是**系统能力集合**（稳定），绝不是产品名称/属性值本身——
# 新增任意产品的属性与图片只是插入数据行，不改这些常量、不加产品枚举。
# ---------------------------------------------------------------------------

# 动态属性定义支持的取值类型（§四）。具体属性由运营在 Category 下动态定义，
# value_type 只能取此白名单；每种类型落到对应 typed column（见 ProductAttributeValue）。
ATTRIBUTE_VALUE_TYPES: tuple[str, ...] = (
    "text",        # 文本 → value_text
    "number",      # 数值（整数/小数）→ value_number
    "boolean",     # 布尔 → value_boolean
    "enum",        # 单选（值须命中 definition.allowed_values）→ value_text
    "multi_enum",  # 多选（值数组，均须命中 allowed_values）→ value_json
    "measurement", # 度量（数值 + 单位，单位取 definition.unit）→ value_number
    "date",        # 日期 → value_date
)
# 需要 allowed_values 约束的类型
ATTRIBUTE_ENUM_TYPES: tuple[str, ...] = ("enum", "multi_enum")

# 产品参考图角度（§六：参考图**视角**，非产品名称，稳定业务词表）
REFERENCE_ANGLES: tuple[str, ...] = (
    "front", "back", "left", "right", "top", "bottom",
    "interface", "package", "installed", "powered_on", "powered_off",
    "detail", "other",
)
# 参考图状态（§六）
REFERENCE_ASSET_STATES: tuple[str, ...] = ("draft", "active", "rejected", "archived")
# 参考图默认从 active 列表隐藏的状态
REFERENCE_HIDDEN_STATES: tuple[str, ...] = ("rejected", "archived")
# 参考图质量状态（§六：本阶段**人工标记**，不接视觉模型、不伪造 AI 检测）
REFERENCE_QUALITY_STATUSES: tuple[str, ...] = (
    "unchecked", "qualified", "blurred", "occluded",
    "wrong_product", "duplicate", "low_resolution",
)
# 参考图允许的媒体类型（扩展名/后端魔数校验）
REFERENCE_MEDIA_TYPES: tuple[str, ...] = ("jpg", "jpeg", "png", "webp")

# ---------------------------------------------------------------------------
# PR-A2 Gate B：入驻治理（完整度策略 / 入驻审核 / 混淆关系 / 目录变更历史）。
# 均为**系统能力集合**（稳定白名单，String 列 + service 校验，免迁移扩展），
# 绝不是产品名称枚举。生命周期（CatalogStatus）与入驻审核（ONBOARDING）是两条独立轴：
# active 不自动等于 approved；approved 不绕过生命周期。
# ---------------------------------------------------------------------------

# 入驻审核状态（§四：资料是否准备充分，独立于 Catalog 生命周期）
ONBOARDING_STATUSES: tuple[str, ...] = (
    "incomplete",        # 资料不满足当前 Category 策略
    "ready_for_review",  # 系统检查完整，等待人工审核
    "approved",          # 人工已确认可用于后续识别与检索
    "needs_changes",     # 审核退回，需要补资料
    "blocked",           # 资料存在明确错误，暂不可使用
)

# 混淆关系严重程度（人工判定）
CONFUSION_SEVERITIES: tuple[str, ...] = ("low", "medium", "high")

# 目录变更历史允许记录的动作（append-only；查询侧筛选用）
CATALOG_REVISION_ACTIONS: tuple[str, ...] = (
    "create", "update", "status", "archive", "restore", "merge",
    "delete", "set_primary", "activate",
    "submit_review", "approve", "request_changes", "block",
)


# ============================================================
# PR-B 最终成片 / Shot 使用血缘 相关枚举
# ============================================================


class FinalVideoStatus(StrEnum):
    """FinalVideo.status —— 最终成片生命周期。

    archived 为归档（保留记录与血缘，不物理删除，历史 confirmed usage 继续计数）；
    删除接口不存在——"删除"一律指归档。
    """

    DRAFT = "draft"          # 创建中，资料未齐
    READY = "ready"          # 资料齐备，可开始确认血缘
    COMPLETED = "completed"  # 成片已交付/发布
    ARCHIVED = "archived"    # 归档（只读；不允许确认新 Usage）


class FinalVideoUsageStatus(StrEnum):
    """FinalVideoUsage.status —— 成片↔Shot 引用关系状态。

    **只有 confirmed 计入正式使用次数**；proposed/suspected/rejected/revoked 均不计数。
    状态迁移：proposed→confirmed / proposed→rejected / confirmed→revoked /
    rejected|revoked→(restore)→proposed。suspected 本阶段仅预留值，不由任何流程产生。
    """

    PROPOSED = "proposed"    # 候选（人工手加或从项目生成），待人工确认
    SUSPECTED = "suspected"  # 疑似（预留给后续自动反查，本阶段不产生）
    CONFIRMED = "confirmed"  # 人工确认的正式引用（唯一计数状态）
    REJECTED = "rejected"    # 人工驳回（重新确认须先恢复为 proposed）
    REVOKED = "revoked"      # 确认后撤销（立即从计数中移除）


# 引用证据方式（受控业务集合）。存 String 列而非 pg_enum，便于后续 PR 新增
# 证据来源时免迁移；service 层按此集合校验。
USAGE_EVIDENCE_METHODS: tuple[str, ...] = (
    "manual",            # 人工手动添加
    "clipmind_project",  # 从 ClipMind 项目的已选择/锁定镜头生成（仍需人工确认）
    "editor_project",    # 剪辑工程文件解析（PR 预留，本阶段不实现）
    "visual_match",      # 视觉反查（PR-H 预留，本阶段不实现）
    "audio_match",       # 音频指纹（预留，本阶段不实现）
    "legacy_path_rule",  # 历史"已使用"目录规则（PR-C 预留；永不自动 confirmed）
)
# 本阶段真正实现且允许进入 confirmed 的证据来源
CONFIRMABLE_EVIDENCE_METHODS: tuple[str, ...] = ("manual", "clipmind_project")

# 使用血缘审计事件动作（append-only；与业务变更同事务写入）
USAGE_EVENT_ACTIONS: tuple[str, ...] = (
    "create_proposal",    # propose-from-project 生成候选
    "manual_add",         # 人工手动添加候选
    "confirm",            # 人工确认
    "reject",             # 人工驳回
    "revoke",             # 撤销已确认引用
    "restore_proposal",   # rejected/revoked 恢复为 proposed
    "occurrence_add",     # 新增出现时间段
    "occurrence_update",  # 修改出现时间段
    "occurrence_delete",  # 删除出现时间段
)
