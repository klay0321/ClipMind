# ClipMind Celery worker 镜像
FROM python:3.13-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# ffmpeg/ffprobe 用于视频信息探测
RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /code

# 先安装共享包
COPY packages/shared /code/packages/shared
RUN pip install /code/packages/shared

# 再安装 worker
COPY services/worker /code/services/worker
RUN pip install /code/services/worker

WORKDIR /code/services/worker

# 默认只消费 default,scan 队列（PR-01 不启用 media/ai/export worker）
CMD ["celery", "-A", "clipmind_worker.celery_app", "worker", "-Q", "default,scan", "-c", "2", "-l", "INFO"]
