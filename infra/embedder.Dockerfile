# ClipMind 本地 Embedding 微服务镜像（PR-04）
# 仅本镜像含 torch / sentence-transformers；api/worker 通过 HTTP 调用，不引入 torch。
# 体积较大（torch CPU + 多语模型权重）；通过 Compose profile "embedding" 单独启用，
# 默认 docker compose up（含 CI）不构建/启动本服务，避免下载模型。
FROM python:3.13-slim-bookworm

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    # HuggingFace/sentence-transformers 缓存目录（挂载为独立 volume，支持离线缓存启动）
    HF_HOME=/models \
    SENTENCE_TRANSFORMERS_HOME=/models \
    EMBEDDER_CACHE_DIR=/models

# curl 用于 healthcheck
RUN apt-get update \
    && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/*

# 先装 CPU 版 torch（不拉 CUDA），再装服务（sentence-transformers 依赖 torch）
RUN pip install --index-url https://download.pytorch.org/whl/cpu "torch>=2.5,<2.9"

WORKDIR /code
COPY services/embedder /code/services/embedder
RUN pip install /code/services/embedder

WORKDIR /code/services/embedder
EXPOSE 8100

# 模型在首次请求/启动后台线程时下载到 /models（挂载卷）。NAS 离线部署需预热该卷。
CMD ["uvicorn", "embedder.app:app", "--host", "0.0.0.0", "--port", "8100"]
