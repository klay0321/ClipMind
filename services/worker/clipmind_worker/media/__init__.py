"""PR-02 媒体处理：镜头检测、派生文件（关键帧/缩略图/代理）、片段导出。

- detector：可替换的 ShotDetector 接口（PySceneDetect 主 + 固定切分兜底）+ 纯函数后处理。
- ffmpeg：FFmpeg 子进程封装（参数数组、无 shell、超时、输出校验）。
- derive：单镜头派生编排。
- storage：data_dir 目录布局、磁盘预检、原子移动、清理。
"""
