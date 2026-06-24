# ClipMind Celery worker / media-worker 镜像
# 固定 bookworm 标签（不用随时间漂移到 trixie 的 -slim），bookworm 上 libglib2.0-0 /
# libgl1 未做 t64 改名，包名稳定。项目 requires-python>=3.13，故用 3.13-slim-bookworm。
FROM python:3.13-slim-bookworm

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# ffmpeg/ffprobe：视频探测与派生（拆镜头/关键帧/缩略图/代理/导出）。
# libglib2.0-0 + libgl1：PySceneDetect 依赖的 opencv-python-headless 运行时显式依赖
# （不依赖 ffmpeg 的传递依赖来提供 OpenCV 所需动态库）。apt 安装最小化并清理缓存。
RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg libglib2.0-0 libgl1 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /code

# 先安装共享包
COPY packages/shared /code/packages/shared
RUN pip install /code/packages/shared

# 再安装 worker（含 PySceneDetect / opencv-python-headless）
COPY services/worker /code/services/worker
RUN pip install /code/services/worker

# 构建期硬校验：PySceneDetect 主检测器的运行环境必须真实可用，
# 导入失败立即让镜像构建失败（不以"固定切分兜底"掩盖镜像依赖错误）。
RUN python -c "import cv2, scenedetect; print('cv2', cv2.__version__, 'scenedetect', scenedetect.__version__)"

WORKDIR /code/services/worker

# 默认只消费 default,scan 队列（PR-01 不启用 media/ai/export worker）
CMD ["celery", "-A", "clipmind_worker.celery_app", "worker", "-Q", "default,scan", "-c", "2", "-l", "INFO"]
