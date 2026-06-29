"""PR-06B 多镜头 ZIP 打包导出 schema。"""

from __future__ import annotations

from clipmind_shared.models.enums import ExportStatus
from pydantic import BaseModel, Field

# 打包上限（防御超大请求；总时长上限 = 体积的安全代理）
MAX_BUNDLE_SHOTS = 50
MAX_BUNDLE_TOTAL_DURATION = 1800.0  # 秒（约 30 分钟源时长）


class BundleCreateRequest(BaseModel):
    shot_ids: list[int] = Field(min_length=1)
    mode: str = Field("reencode", pattern="^(reencode|copy)$")
    project_id: int | None = None


class BundleAcceptedOut(BaseModel):
    export_id: int
    status: ExportStatus
    celery_task_id: str | None = None
    shot_count: int
    detail: str = "已入队打包导出"
