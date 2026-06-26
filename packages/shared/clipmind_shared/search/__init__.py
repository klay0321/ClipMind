"""PR-04 检索：检索文档构建 + Gate B 查询解析/融合/解释（纯逻辑，供 API/worker 共用，可单测）。"""

from clipmind_shared.search.document import (
    SearchDocumentContent,
    build_search_document,
    compute_document_hash,
)
from clipmind_shared.search.explain import (
    MatchFacts,
    build_explanations,
    build_matched_reasons,
    build_risk_warnings,
    build_unmatched_requirements,
)
from clipmind_shared.search.parser import (
    FakeQueryParser,
    RuleBasedQueryParser,
    SearchQueryParser,
    get_query_parser,
)
from clipmind_shared.search.query import (
    ASPECT_RATIO_TOLERANCE,
    ASPECT_RATIO_VALUES,
    AspectRatio,
    ParsedSearchQuery,
    ParserStatus,
    SearchMode,
)
from clipmind_shared.search.scoring import (
    CHANNEL_WEIGHTS,
    RRF_K,
    Candidate,
    order_candidates,
    paginate,
    score_candidates,
)

__all__ = [
    # 检索文档（Gate A）
    "SearchDocumentContent",
    "build_search_document",
    "compute_document_hash",
    # 查询模型 / 枚举（Gate B）
    "ParsedSearchQuery",
    "ParserStatus",
    "SearchMode",
    "AspectRatio",
    "ASPECT_RATIO_VALUES",
    "ASPECT_RATIO_TOLERANCE",
    # 解析器
    "SearchQueryParser",
    "RuleBasedQueryParser",
    "FakeQueryParser",
    "get_query_parser",
    # 融合评分
    "Candidate",
    "score_candidates",
    "order_candidates",
    "paginate",
    "RRF_K",
    "CHANNEL_WEIGHTS",
    # 解释
    "MatchFacts",
    "build_explanations",
    "build_matched_reasons",
    "build_unmatched_requirements",
    "build_risk_warnings",
]
