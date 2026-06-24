"""ClipMind 共享层。

被 API（async）与 worker（sync）共同依赖，提供统一的：
- SQLAlchemy 模型与同一份 metadata（`clipmind_shared.db`、`clipmind_shared.models`）
- FFprobe 视频信息封装（`clipmind_shared.ffprobe`）
- 路径安全/白名单校验（`clipmind_shared.security.paths`）
- AI Provider 接口骨架（`clipmind_shared.ai.provider`，PR-03 实现）
"""

__version__ = "0.1.0"
