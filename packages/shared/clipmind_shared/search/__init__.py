"""PR-04 检索：检索文档构建等纯逻辑（供 API/worker 共用，可单测）。"""

from clipmind_shared.search.document import (
    SearchDocumentContent,
    build_search_document,
    compute_document_hash,
)

__all__ = [
    "SearchDocumentContent",
    "build_search_document",
    "compute_document_hash",
]
