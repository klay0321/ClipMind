"""默认 Embedding 模型/revision 在 API/worker/embedder 三处一致（§2）。

默认即不可变 commit SHA；环境变量可覆盖；空/main/latest/head 在要求 pin 时 fail-closed
（fail-closed 行为见 packages/shared/tests/test_openai_embedding.py）。
"""

from __future__ import annotations

from app.config import Settings as ApiSettings
from clipmind_shared.constants import (
    DEFAULT_EMBEDDING_DIMENSION,
    DEFAULT_EMBEDDING_MODEL,
    DEFAULT_EMBEDDING_MODEL_REVISION,
)
from clipmind_worker.config import WorkerSettings

from embedder.config import EmbedderSettings

_HEX = set("0123456789abcdef")


def test_default_revision_is_immutable_sha():
    sha = DEFAULT_EMBEDDING_MODEL_REVISION
    assert len(sha) == 40 and set(sha) <= _HEX  # 40 位十六进制 commit SHA
    assert sha not in {"", "main", "latest", "head", "HEAD"}


def test_revision_and_model_consistent_across_services():
    rev = DEFAULT_EMBEDDING_MODEL_REVISION
    assert ApiSettings.model_fields["embedding_model_revision"].default == rev
    assert WorkerSettings.model_fields["embedding_model_revision"].default == rev
    assert EmbedderSettings.model_fields["embedder_model_revision"].default == rev

    model = DEFAULT_EMBEDDING_MODEL
    assert ApiSettings.model_fields["embedding_model"].default == model
    assert WorkerSettings.model_fields["embedding_model"].default == model
    assert EmbedderSettings.model_fields["embedder_model"].default == model

    dim = DEFAULT_EMBEDDING_DIMENSION
    assert ApiSettings.model_fields["embedding_dimension"].default == dim
    assert WorkerSettings.model_fields["embedding_dimension"].default == dim
    assert EmbedderSettings.model_fields["embedder_dimension"].default == dim


def test_env_override_works(monkeypatch):
    monkeypatch.setenv("EMBEDDING_MODEL_REVISION", "deadbeefdeadbeef")
    assert WorkerSettings().embedding_model_revision == "deadbeefdeadbeef"
    assert ApiSettings().embedding_model_revision == "deadbeefdeadbeef"
