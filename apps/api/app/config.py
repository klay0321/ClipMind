"""应用配置（pydantic-settings，从环境变量/.env 读取）。"""

from __future__ import annotations

from functools import lru_cache

from clipmind_shared.constants import (
    DEFAULT_EMBEDDING_DIMENSION,
    DEFAULT_EMBEDDING_MODEL,
    DEFAULT_EMBEDDING_MODEL_REVISION,
)
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore", case_sensitive=False
    )

    # 数据库（API 使用 async 驱动）
    database_url: str = "postgresql+asyncpg://clipmind:clipmind@postgres:5432/clipmind"

    # Redis / Celery
    redis_url: str = "redis://redis:6379/0"
    celery_broker_url: str = "redis://redis:6379/1"
    celery_result_backend: str = "redis://redis:6379/2"

    # 路径与安全
    allowed_source_roots: str = "/app/source,/app/uploads"  # 逗号分隔的白名单根
    source_mount_path: str = "/app/source"
    data_dir: str = "/app/data"

    # 网页上传：独立可写区（不写只读 NAS 源）
    upload_dir: str = "/app/uploads"
    upload_max_mb: int = 4096

    # FFprobe
    ffprobe_timeout: float = 30.0

    # Web / CORS
    web_origin: str = "http://localhost:3000"
    api_internal_url: str = "http://api:8000"

    # PR-03A AI（API 仅入队 + 读结果 + 回显健康；不在 API 进程调用 provider 网络）
    ai_provider: str = ""
    ai_base_url: str = ""
    ai_api_key: str = ""   # 仅判断是否已配置，绝不回显/记录
    ai_api_key_header: str = ""  # 鉴权头（空=Authorization: Bearer；mimo token-plan 用 api-key）
    ai_model: str = ""
    ai_max_images: int = 8

    # PR-04 Embedding（MiMo 无 embedding，故走独立 provider）。API 仅在搜索期向量化查询
    # （Gate B）与读索引状态；嵌入回填在 search-worker。""=未配置 | fake | openai_compatible
    embedding_provider: str = ""
    embedding_base_url: str = ""
    embedding_api_key: str = ""   # 仅判断是否已配置，绝不回显/记录
    embedding_model: str = DEFAULT_EMBEDDING_MODEL
    embedding_model_revision: str = DEFAULT_EMBEDDING_MODEL_REVISION  # 默认不可变 commit
    embedding_dimension: int = DEFAULT_EMBEDDING_DIMENSION
    embedding_timeout: float = 30.0
    embedding_api_key_header: str = ""
    embedding_prefix_scheme: str = "e5"
    embedding_require_pinned_revision: bool = True

    # Gate B 查询解析与检索调参
    # ""/auto=ai(mimo) 已配置则用 mimo，否则规则解析 | fake | rulebased | mimo
    search_query_parser: str = ""
    search_parser_model: str = ""          # mimo 文本解析模型（默认 mimo-v2.5-pro）
    search_parser_timeout: float = 8.0     # 解析超时（秒），超时降级规则解析，不阻断词法
    search_candidate_pool: int = 200       # 每通道候选池上限（有界融合）

    # PR-05 脚本拆段解析
    # ""/auto=ai(mimo) 已配置则用 mimo，否则规则拆段 | fake | rulebased | mimo
    script_parser: str = ""
    script_parser_model: str = ""          # mimo 文本拆段模型（空=回退 ai_model 或 mimo-v2.5-pro）
    script_parser_timeout: float = 12.0    # 拆段超时（秒），超时降级规则拆段

    # PR-05 Gate B 脚本镜头匹配
    script_match_candidate_limit: int = 10   # 每段默认候选数（上限 50）
    script_match_min_score: float = 0.05     # 候选最低综合分（未达视为该段无匹配/缺口）
    script_match_max_reuse: int = 1          # 全局分配单 shot 默认最多分配段数（超出触发去重）

    # PR-03B：当前无登录体系，审核者用配置的本地标签（不伪造用户，PR-07 接入后平滑替换）
    review_default_reviewer: str = "local-reviewer"
    # 产品参考图上传约束（旧扁平 product 的 product_image）
    product_image_max_mb: int = 10
    product_image_max_count: int = 20
    # PR-A2 Gate A：通用目录参考图（ProductReferenceAsset）上传约束
    reference_asset_max_mb: int = 15
    reference_asset_max_count: int = 50
    reference_asset_max_pixels: int = 60_000_000  # 单图最大像素数（防解压炸弹）
    reference_thumbnail_max_dim: int = 320
    # PR-A2 Gate B：系统默认完整度策略（Category 未配置 active policy 时使用；
    # 可经环境变量调整，不硬编码任何产品名；required_angles 默认为空列表）
    readiness_default_min_references: int = 3
    readiness_default_min_identity_attributes: int = 1
    readiness_default_require_primary: bool = True
    readiness_default_require_alias: bool = False
    readiness_default_require_name_en: bool = False

    log_level: str = "INFO"

    @property
    def allowed_roots_list(self) -> list[str]:
        return [r.strip() for r in self.allowed_source_roots.split(",") if r.strip()]

    @property
    def sync_database_url(self) -> str:
        """供 Alembic 使用的同步连接串（asyncpg -> psycopg）。"""
        return self.database_url.replace("+asyncpg", "+psycopg")


@lru_cache
def get_settings() -> Settings:
    return Settings()
