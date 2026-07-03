"""Gate B：API 侧查询解析器 / 查询向量化 provider 的装配。

- 查询解析器：默认按 ``SEARCH_QUERY_PARSER`` 选择；``auto``/空 时，若 AI(mimo) 已配置则用 mimo，
  否则规则解析。mimo 失败会在解析器内部降级，本层不抛错。
- 查询向量化：复用 Gate A 的 ``get_embedding_provider``（API 仅查询期 embed_query，回填在 worker）。

两者构造均无网络副作用（mimo/openai 仅在 parse/embed 时才发请求），故每请求构造成本可忽略。
"""

from __future__ import annotations

import hashlib
import logging

import redis as redis_lib
from clipmind_shared.ai import get_embedding_provider
from clipmind_shared.ai.embedding import EmbeddingProvider
from clipmind_shared.search.parser import (
    FakeQueryParser,
    RuleBasedQueryParser,
    SearchQueryParser,
    get_query_parser,
)
from clipmind_shared.search.query import ParsedSearchQuery, ParserStatus

from app.config import Settings

logger = logging.getLogger(__name__)

# 解析缓存 key 版本：ParsedSearchQuery schema 或解析 prompt 变更时升版，避免旧缓存串味。
_PARSE_CACHE_VERSION = "v1"

# 模块级连接池（parser 每请求构造，连接池必须复用；惰性初始化）
_parse_cache_pool: redis_lib.ConnectionPool | None = None


def _parse_cache_client(redis_url: str) -> redis_lib.Redis:
    global _parse_cache_pool
    if _parse_cache_pool is None:
        _parse_cache_pool = redis_lib.ConnectionPool.from_url(
            redis_url, socket_timeout=2, socket_connect_timeout=2
        )
    return redis_lib.Redis(connection_pool=_parse_cache_pool)


class CachedQueryParser:
    """LLM 查询解析结果的确定性缓存（PR-E.1）。

    动机：MiMo 解析同一查询的输出非确定（semantic_text 改写波动、实体识别
    间歇丢失），导致同一请求的召回通道输入不同 → 顺序与分数抖动。以查询文本
    为键缓存首次解析结果后，同一查询在 TTL 内全链路输入确定。

    边界：只缓存 ``parser_status=OK`` 的结果（降级解析不固化）；Redis 任何
    异常都静默降级为直呼内层（可用性优先）；不缓存空查询；不改变任何解析
    逻辑、公式或筛选语义。fake/rulebased 解析器本身确定，工厂不为其包缓存。
    """

    def __init__(
        self, inner: SearchQueryParser, *, redis_url: str, model: str, ttl_seconds: int
    ) -> None:
        self._inner = inner
        self._redis_url = redis_url
        self._model = model
        self._ttl = ttl_seconds

    def _key(self, text: str) -> str:
        digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
        return f"clipmind:qparse:{_PARSE_CACHE_VERSION}:{self._model}:{digest}"

    def parse(self, text: str) -> ParsedSearchQuery:
        if not text.strip():
            return self._inner.parse(text)
        key = self._key(text)
        try:
            cached = _parse_cache_client(self._redis_url).get(key)
            if cached:
                return ParsedSearchQuery.model_validate_json(cached)
        except Exception:  # noqa: BLE001 —— 缓存不可用不阻断搜索；不记录查询内容
            logger.debug("query parse cache read unavailable", exc_info=True)
        parsed = self._inner.parse(text)
        if parsed.parser_status == ParserStatus.OK:
            try:
                _parse_cache_client(self._redis_url).setex(
                    key, self._ttl, parsed.model_dump_json()
                )
            except Exception:  # noqa: BLE001
                logger.debug("query parse cache write unavailable", exc_info=True)
        return parsed


def get_query_parser_for_settings(settings: Settings) -> SearchQueryParser:
    mode = (settings.search_query_parser or "").strip().lower()
    if mode == "fake":
        return FakeQueryParser()
    if mode == "rulebased":
        return RuleBasedQueryParser()
    mimo_ready = bool(settings.ai_base_url and settings.ai_api_key)
    if mode == "mimo" or (
        mode in ("", "auto")
        and (settings.ai_provider or "").strip().lower() == "mimo"
        and mimo_ready
    ):
        mimo = get_query_parser(
            "mimo",
            base_url=settings.ai_base_url,
            api_key=settings.ai_api_key,
            model=settings.search_parser_model or None,
            timeout=settings.search_parser_timeout,
            api_key_header=settings.ai_api_key_header,
        )
        if settings.search_parser_cache_ttl_seconds <= 0:
            return mimo
        return CachedQueryParser(
            mimo,
            redis_url=settings.redis_url,
            model=settings.search_parser_model or "mimo",
            ttl_seconds=settings.search_parser_cache_ttl_seconds,
        )
    return RuleBasedQueryParser()


def get_query_embedding_provider(settings: Settings) -> EmbeddingProvider:
    return get_embedding_provider(
        settings.embedding_provider,
        base_url=settings.embedding_base_url,
        api_key=settings.embedding_api_key,
        model=settings.embedding_model,
        dimension=settings.embedding_dimension,
        model_revision=settings.embedding_model_revision,
        timeout=settings.embedding_timeout,
        api_key_header=settings.embedding_api_key_header,
        prefix_scheme=settings.embedding_prefix_scheme,
        require_pinned_revision=settings.embedding_require_pinned_revision,
    )
