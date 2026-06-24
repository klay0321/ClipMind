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
    AICallStatus,
    AIRunStatus,
    AIShotAnalysisStatus,
    AssetStatus,
    ExportStatus,
    MediaRunStatus,
    ScanRunStatus,
    ScanStatus,
    ShotStatus,
)
from clipmind_shared.models.export import Export
from clipmind_shared.models.media_run import MediaProcessingRun
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
]
