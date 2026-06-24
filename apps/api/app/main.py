"""ClipMind FastAPI 应用入口。"""

from __future__ import annotations

import logging

from clipmind_shared.security import PathSecurityError
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.config import get_settings
from app.routers import (
    assets,
    exports,
    health,
    shots,
    source_directories,
    system,
    uploads,
)

settings = get_settings()
logging.basicConfig(level=settings.log_level.upper())

app = FastAPI(title="ClipMind API", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=[settings.web_origin],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.exception_handler(PathSecurityError)
async def _path_security_handler(request: Request, exc: PathSecurityError) -> JSONResponse:
    """白名单/路径穿越错误 -> 422，文案安全（不泄漏内部路径细节）。"""
    return JSONResponse(status_code=422, content={"detail": str(exc)})


app.include_router(health.router)
app.include_router(system.router, prefix="/api")
app.include_router(source_directories.router, prefix="/api")
app.include_router(assets.router, prefix="/api")
app.include_router(shots.router, prefix="/api")
app.include_router(exports.router, prefix="/api")
app.include_router(uploads.router, prefix="/api")
