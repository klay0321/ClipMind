# ClipMind API 镜像（也用于一次性 migrate 服务）
FROM python:3.13-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# ffmpeg/ffprobe 用于视频信息探测；curl 用于 healthcheck
RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /code

# 先安装共享包（依赖较稳定，利用 Docker 层缓存）
COPY packages/shared /code/packages/shared
RUN pip install /code/packages/shared

# 再安装 API（含 FastAPI / SQLAlchemy / Alembic 等）
COPY apps/api /code/apps/api
RUN pip install /code/apps/api

# Alembic 与应用以 apps/api 为工作目录
WORKDIR /code/apps/api

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
