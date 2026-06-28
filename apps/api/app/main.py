"""ClipMind FastAPI 应用入口。"""

from __future__ import annotations

import logging

from clipmind_shared.security import PathSecurityError
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.config import get_settings
from app.routers import (
    ai,
    assets,
    collections,
    dynamic_collections,
    export_center,
    exports,
    favorites,
    health,
    products,
    projects,
    review,
    saved_searches,
    scripts,
    search,
    shots,
    source_directories,
    system,
    tags,
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
# export_center 须在 exports 之前注册：/exports/bundle/* 字面路由优先于 /exports/{export_id}
app.include_router(export_center.router, prefix="/api")
app.include_router(exports.router, prefix="/api")
app.include_router(uploads.router, prefix="/api")
app.include_router(ai.router, prefix="/api")
app.include_router(review.router, prefix="/api")
app.include_router(products.router, prefix="/api")
app.include_router(tags.router, prefix="/api")
app.include_router(search.router, prefix="/api")
app.include_router(scripts.router, prefix="/api")
app.include_router(projects.router, prefix="/api")
app.include_router(collections.router, prefix="/api")
app.include_router(dynamic_collections.router, prefix="/api")
app.include_router(saved_searches.router, prefix="/api")
app.include_router(favorites.router, prefix="/api")
