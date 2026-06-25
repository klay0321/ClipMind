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
from clipmind_shared.models.enums import (
    ACTIVE_AI_RUN_STATUSES,
    ACTIVE_MEDIA_RUN_STATUSES,
    ACTIVE_SCAN_RUN_STATUSES,
    EXCLUDED_FROM_SEARCH_STATUSES,
    HUMAN_EFFECTIVE_STATUSES,
    AICallStatus,
    AIRunStatus,
    AIShotAnalysisStatus,
    AssetStatus,
    ExportStatus,
    MediaRunStatus,
    ProductStatus,
    ReviewAction,
    ReviewStatus,
    ScanRunStatus,
    ScanStatus,
    ShotStatus,
    TagSource,
    TagType,
)
from clipmind_shared.models.export import Export
from clipmind_shared.models.media_run import MediaProcessingRun
from clipmind_shared.models.product import (
    AssetProduct,
    Product,
    ProductAlias,
    ProductImage,
)
from clipmind_shared.models.review import (
    ReviewEvent,
    ShotReviewState,
    ShotTag,
    Tag,
)
from clipmind_shared.models.scan_run import ScanRun
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
]
