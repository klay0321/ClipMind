"""Gate B：API 侧查询解析器 / 查询向量化 provider 的装配。

- 查询解析器：默认按 ``SEARCH_QUERY_PARSER`` 选择；``auto``/空 时，若 AI(mimo) 已配置则用 mimo，
  否则规则解析。mimo 失败会在解析器内部降级，本层不抛错。
- 查询向量化：复用 Gate A 的 ``get_embedding_provider``（API 仅查询期 embed_query，回填在 worker）。

两者构造均无网络副作用（mimo/openai 仅在 parse/embed 时才发请求），故每请求构造成本可忽略。
"""

from __future__ import annotations

from clipmind_shared.ai import get_embedding_provider
from clipmind_shared.ai.embedding import EmbeddingProvider
from clipmind_shared.search.parser import (
    FakeQueryParser,
    RuleBasedQueryParser,
    SearchQueryParser,
    get_query_parser,
)

from app.config import Settings


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
        return get_query_parser(
            "mimo",
            base_url=settings.ai_base_url,
            api_key=settings.ai_api_key,
            model=settings.search_parser_model or None,
            timeout=settings.search_parser_timeout,
            api_key_header=settings.ai_api_key_header,
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
