"""上传路由：网页上传视频到独立可写区并触发索引。"""

from __future__ import annotations

from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile, status
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.db import get_db
from app.services import upload_service
from app.services.upload_service import UploadError

router = APIRouter(prefix="/uploads", tags=["uploads"])

# Content-Length 预检放宽量：multipart 边界/头开销远小于此，避免误拒合法文件
_PRECHECK_SLACK_BYTES = 16 * 1024 * 1024


class UploadAcceptedOut(BaseModel):
    filename: str
    bytes: int
    source_directory_id: int
    scan_run_id: int
    celery_task_id: str | None = None
    detail: str = "已上传并入队索引"


@router.post("", response_model=UploadAcceptedOut, status_code=status.HTTP_202_ACCEPTED)
async def upload_asset(
    request: Request,
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
) -> UploadAcceptedOut:
    if not file.filename:
        raise HTTPException(status_code=422, detail="缺少文件名")
    # 廉价预检：声明的请求体远超上限时直接 413，避免先流式落盘约 upload_max_mb 再删
    settings = get_settings()
    max_bytes = settings.upload_max_mb * 1024 * 1024
    cl = request.headers.get("content-length")
    if cl is not None:
        try:
            if int(cl) > max_bytes + _PRECHECK_SLACK_BYTES:
                raise HTTPException(
                    status_code=413, detail=f"文件过大（上限 {settings.upload_max_mb}MB）"
                )
        except ValueError:
            pass  # 非法头忽略，交给流式上限把关
    try:
        res = await upload_service.save_upload(db, filename=file.filename, stream=file)
    except UploadError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=503, detail=f"上传失败: {exc}") from exc
    return UploadAcceptedOut(**res)
