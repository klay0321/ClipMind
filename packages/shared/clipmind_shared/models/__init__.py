"""ClipMind ORM 模型聚合。

Alembic 的 target_metadata 使用 `Base.metadata`，因此所有模型都在此 import，
确保 metadata 完整。
"""

from clipmind_shared.db.base import Base
from clipmind_shared.models.ai_analysis import (
    AIAnalysisRun,
    AICallLog,
    AIShotAnalysis,
)
from clipmind_shared.models.asset import Asset
from clipmind_shared.models.bundle_export import BundleExport
from clipmind_shared.models.collection import Collection, CollectionShot
from clipmind_shared.models.download_log import DownloadLog
from clipmind_shared.models.dynamic_collection import DynamicCollection
from clipmind_shared.models.enums import (
    ACTIVE_AI_RUN_STATUSES,
    ACTIVE_MEDIA_RUN_STATUSES,
    ACTIVE_SCAN_RUN_STATUSES,
    CONFIRMABLE_EVIDENCE_METHODS,
    EXCLUDED_FROM_SEARCH_STATUSES,
    HUMAN_EFFECTIVE_STATUSES,
    SEARCHABLE_DOCUMENT_STATUS,
    USAGE_EVENT_ACTIONS,
    USAGE_EVIDENCE_METHODS,
    VECTOR_READY_EMBEDDING_STATUS,
    SCRIPT_EXPORT_FORMATS,
    SHOT_BASED_FAVORITE_TYPES,
    AICallStatus,
    AIRunStatus,
    AIShotAnalysisStatus,
    AssetStatus,
    CatalogStatus,
    ExportStatus,
    FavoriteTargetType,
    FinalVideoStatus,
    FinalVideoUsageStatus,
    MediaRunStatus,
    ProductStatus,
    ProjectStatus,
    ReviewAction,
    ReviewStatus,
    ScanRunStatus,
    ScanStatus,
    ScriptParseStatus,
    ScriptStatus,
    SearchDocumentStatus,
    SearchEmbeddingStatus,
    SearchKind,
    ShotStatus,
    TagSource,
    TagType,
)
from clipmind_shared.models.export import Export
from clipmind_shared.models.final_video import (
    FinalVideo,
    FinalVideoUsage,
    FinalVideoUsageEvent,
    FinalVideoUsageOccurrence,
)
from clipmind_shared.models.favorite import Favorite
from clipmind_shared.models.media_run import MediaProcessingRun
from clipmind_shared.models.product import (
    AssetProduct,
    Product,
    ProductAlias,
    ProductImage,
)
from clipmind_shared.models.product_catalog import (
    ProductCatalogAlias,
    ProductCategory,
    ProductFamily,
    ProductSKU,
    ProductVariant,
)
from clipmind_shared.models.product_attributes import (
    ProductAttributeDefinition,
    ProductAttributeValue,
)
from clipmind_shared.models.product_governance import (
    CatalogRevision,
    ProductConfusionPair,
    ProductOnboardingReview,
    ProductReadinessPolicy,
)
from clipmind_shared.models.product_reference import ProductReferenceAsset
from clipmind_shared.models.project import (
    Project,
    ProjectAsset,
    ProjectProduct,
    ProjectShot,
)
from clipmind_shared.models.review import (
    ReviewEvent,
    ShotReviewState,
    ShotTag,
    Tag,
)
from clipmind_shared.models.scan_run import ScanRun
from clipmind_shared.models.script import (
    ScriptProject,
    ScriptSegment,
    ScriptShotCandidate,
)
from clipmind_shared.models.saved_search import SavedSearch
from clipmind_shared.models.script_export import ScriptExport
from clipmind_shared.models.search import EMBEDDING_DIM, ShotSearchDocument
from clipmind_shared.models.shot import Shot
from clipmind_shared.models.source_directory import SourceDirectory

__all__ = [
    "Base",
    "Asset",
    "ScanRun",
    "SourceDirectory",
    "Shot",
    "MediaProcessingRun",
    "Export",
    "AIAnalysisRun",
    "AIShotAnalysis",
    "AICallLog",
    "AssetStatus",
    "ScanStatus",
    "ScanRunStatus",
    "ShotStatus",
    "MediaRunStatus",
    "ExportStatus",
    "AIRunStatus",
    "AIShotAnalysisStatus",
    "AICallStatus",
    "ACTIVE_SCAN_RUN_STATUSES",
    "ACTIVE_MEDIA_RUN_STATUSES",
    "ACTIVE_AI_RUN_STATUSES",
    # PR-03B 产品库
    "Product",
    "ProductAlias",
    "ProductImage",
    "AssetProduct",
    "ProductStatus",
    # PR-A1 通用产品目录
    "ProductCategory",
    "ProductFamily",
    "ProductVariant",
    "ProductSKU",
    "ProductCatalogAlias",
    "ProductAttributeDefinition",
    "ProductAttributeValue",
    "ProductReferenceAsset",
    "ProductReadinessPolicy",
    "ProductOnboardingReview",
    "ProductConfusionPair",
    "CatalogRevision",
    "CatalogStatus",
    # PR-03B 标签/审核
    "Tag",
    "ShotTag",
    "ShotReviewState",
    "ReviewEvent",
    "ReviewStatus",
    "TagType",
    "TagSource",
    "ReviewAction",
    "HUMAN_EFFECTIVE_STATUSES",
    "EXCLUDED_FROM_SEARCH_STATUSES",
    # PR-04 检索文档
    "ShotSearchDocument",
    "SearchDocumentStatus",
    "SearchEmbeddingStatus",
    "SEARCHABLE_DOCUMENT_STATUS",
    "VECTOR_READY_EMBEDDING_STATUS",
    "EMBEDDING_DIM",
    # PR-05 脚本匹配
    "ScriptProject",
    "ScriptSegment",
    "ScriptShotCandidate",
    "ScriptExport",
    "ScriptStatus",
    "ScriptParseStatus",
    # PR-06A 项目 / 收藏 / 素材集合
    "Project",
    "ProjectAsset",
    "ProjectShot",
    "ProjectProduct",
    "Collection",
    "CollectionShot",
    "ProjectStatus",
    # PR-06B 导出中心 / 保存搜索 / 收藏 / 动态集合 / Bundle
    "BundleExport",
    "DownloadLog",
    "SavedSearch",
    "Favorite",
    "DynamicCollection",
    "SearchKind",
    "FavoriteTargetType",
    "SHOT_BASED_FAVORITE_TYPES",
    "SCRIPT_EXPORT_FORMATS",
    # PR-B 最终成片 / 使用血缘
    "FinalVideo",
    "FinalVideoUsage",
    "FinalVideoUsageOccurrence",
    "FinalVideoUsageEvent",
    "FinalVideoStatus",
    "FinalVideoUsageStatus",
    "USAGE_EVIDENCE_METHODS",
    "CONFIRMABLE_EVIDENCE_METHODS",
    "USAGE_EVENT_ACTIONS",
]
