# 拆镜头与派生文件（PR-02）

> 本文档描述 ClipMind PR-02（`feat/shot-processing`）的镜头切分、派生文件生成、
> 重新分析原子替换、失败恢复、资源限制、浏览器播放与下载策略。
>
> **再次声明**：本文中"生成关键帧 / 缩略图 / 代理 / 片段"一律指用 **FFmpeg 对源视频提取、
> 裁剪、转码出派生文件**，是确定性媒体处理，**不是生成式 AI 能力**。ClipMind 不做文生视频 /
> 图生视频 / 数字人 / 声音克隆 / 视频复刻 / 自动成片。PR-02 **不调用任何 AI**。

---

## 1. 总览

在 PR-01 已索引的 `Asset` 之上，PR-02 增加：

```
素材（已索引）
   ↓ 发起镜头分析（API 创建 MediaProcessingRun，入队 media 队列）
media-worker
   ↓ FFprobe 取时长 → 检测镜头边界（PySceneDetect，兜底固定切分）
   ↓ 逐镜头派生：主关键帧(webp) + 缩略图(webp) + 代理视频(mp4, H.264)
   ↓ 原子代次替换：落库 Shot + 搬运文件到 active
镜头库（前端：网格 + 详情 + 代理播放 + 片段导出下载）
```

源视频始终**只读**，所有派生文件写入独立可写数据目录 `/app/data`。

---

## 2. 镜头检测算法

检测封装在**可替换的 `ShotDetector` 接口**之后（`services/worker/clipmind_worker/media/detector.py`），
业务代码不绑定单一算法。

- **主检测器：PySceneDetect `ContentDetector`**（内容感知场景边界检测）。
  选择理由：成熟、内容感知阈值稳定、直接产出有序不重叠的场景列表，相比解析 FFmpeg
  `select='gt(scene,...)'`+`showinfo` 的 stderr 更可测、跨版本更稳。解码后端用
  `opencv-python-headless`（容器友好，无 GUI 依赖）。
- **兜底检测器：固定时长切分**（`FixedDurationDetector`）。无明显转场、检测器异常或导入失败时
  自动回退（lazy import，缺库不影响其余流程）。
- **后处理（纯函数 `postprocess_boundaries`，无 ffmpeg/DB，便于单测）**：
  1. 首尾安全余量裁剪（`head_padding` / `tail_padding`）；
  2. clamp 到 `[0, duration]`；
  3. 过短镜头合并（`min_shot_duration`）；
  4. 过长镜头继续等分拆分（`max_shot_duration`）；
  5. 重排 `sequence_no`。

**结果保证**：顺序稳定、不重叠、不超过源时长、无零时长、无明显转场仍有结果、
单镜头短视频得到一个有效镜头；横/竖屏、中文与特殊字符路径均支持。

### 2.1 可配置参数（环境变量，初始默认值，非写死业务规则）

| 变量 | 默认 | 说明 |
| --- | --- | --- |
| `SHOT_DETECTOR_TYPE` | `pyscenedetect` | `pyscenedetect` \| `fixed` |
| `SCENE_THRESHOLD` | `27.0` | ContentDetector 阈值（越小越敏感） |
| `MIN_SHOT_DURATION` | `1.0` | 最短镜头（秒），更短则合并 |
| `MAX_SHOT_DURATION` | `12.0` | 最长镜头（秒），更长则拆分 |
| `FALLBACK_SEGMENT_DURATION` | `5.0` | 兜底固定切分时长（秒） |
| `HEAD_PADDING` / `TAIL_PADDING` | `0` | 首尾安全余量（秒） |

每次运行的检测参数会快照存入 `MediaProcessingRun.config_snapshot`（便于追溯）。

---

## 3. 派生文件目录结构

所有派生文件写入命名卷 `clipmind-data`（容器内 `/app/data`，env `DATA_DIR`），**绝不回写源目录**。

```
data/
  assets/{asset_id}/
    active/shots/{shot_id}/        # 当前生效代次（对外服务）
      keyframe.webp                # 主关键帧（镜头中点）
      thumbnail.webp               # 缩略图（由关键帧缩放）
      proxy.mp4                    # 代理视频（H.264 + faststart）
    runs/{run_uuid}/staging/       # 处理中临时区，成功后清理
  exports/{export_uuid}/clip.mp4   # 导出片段
```

**路径安全**：`shot_id` / `asset_id` 为服务端自增整数（无分隔符/`..`），但每个路径仍经
`safe_join_within_root(data_dir_real, ...)` 做 realpath 包含校验，确保落在 `data_dir` 之内；
数据库只保存**相对路径**，绝不保存服务器绝对路径，文件接口绝不接受前端传入的任意路径。

### 3.1 FFmpeg 命令策略

所有 FFmpeg/FFprobe 调用：**参数数组、无 shell、`--` 阻断文件名选项注入、显式超时、
检查退出码、stderr 截断保存、输出经 ffprobe 校验**（`media/ffmpeg.py`，与 `clipmind_shared.ffprobe` 同风格）。

- **主关键帧**：镜头中点抽 1 帧，`scale='min(iw,640)':-2`（按 `KEYFRAME_MAX_WIDTH` 等比、不放大），WebP；极短镜头中点安全收敛。
- **缩略图**：由关键帧缩放到 `THUMBNAIL_MAX_WIDTH`（默认 320），WebP，体积可控、可缓存。
- **代理视频**：H.264 / `yuv420p` / `+faststart`；高度上限 `PROXY_MAX_HEIGHT`（默认 720）、**不放大**低分辨率源；宽高强制偶数；音频按 `PROXY_KEEP_AUDIO` 保留（AAC）或丢弃；`PROXY_CRF`/`PROXY_PRESET` 可配。

---

## 4. 数据模型

新增三表（Alembic `0002_shot_processing`，不修改 0001、不建 pgvector）：

- **`Shot`**：`id, asset_id, processing_run_id, generation, sequence_no, start_time, end_time,
  duration, detector_type, detector_confidence, status(pending/processing/ready/failed),
  error_message, keyframe_path, thumbnail_path, proxy_path, created_at, updated_at`。
  约束：`(asset_id, generation, sequence_no)` 唯一；`start_time>=0`、`end_time>start_time`、`duration>=0`。
- **`MediaProcessingRun`**：`id, run_uuid, asset_id, celery_task_id, status, progress, current_step,
  total_shots, completed_shots, error_message, generation, config_snapshot, queued_at, started_at,
  heartbeat_at, finished_at, worker_name, ...`。**部分唯一索引 `uq_active_media_run`**：同一素材
  同一时刻至多一个活动运行（queued/running）。
- **`Export`**：`id, export_uuid, asset_id`(可空 FK, SET NULL, 有索引)`, shot_id`(可空 FK, SET NULL)`,
  status, mode, output_path, filename, error_message, ...` + **来源快照（均不为空，创建时写入，
  永久可追溯）**：`source_asset_id, source_shot_id, source_generation, source_sequence_no,
  source_start_time, source_end_time, source_filename, source_relative_path`。
  `asset_id`/`shot_id` 仅作 Asset/Shot 仍存在时的便利关联，删除后置 NULL；**导出的下载与追溯一律
  以来源快照为准**，不依赖 Asset/Shot 仍然存在（重分析删除旧镜头、甚至 Asset 被删除后，导出记录
  仍可查询、文件仍可下载、来源时间码/文件名/相对路径仍完整）。

镜头分析成功后 `Asset.status` 置 `shot_split`。AI 字段（描述/标签/风险/审核）**不在 PR-02**，留待 PR-03。
`Asset.full_hash` 仍为 PR-01 预留的可空列，**PR-02 不计算、不依赖**（避免范围漂移），留待后续 PR 启用。

---

## 5. 重新分析（原子代次替换）

镜头分析以 **PostgreSQL 为事实来源**。重新分析采用**原子代次切换**，保证"旧的有效镜头在新分析
完整成功前持续可用"：

1. API 创建 `MediaProcessingRun(queued)`（部分唯一索引兜底并发）→ commit → 入队 → 写回 `celery_task_id`。
2. worker 取**素材级 advisory lock**（命名空间 `0x4D44`，绑定单连接跨多次 commit）。
3. 分配单调递增 `generation`；全部派生先写 `runs/{run_uuid}/staging`；逐镜头校验输出。
4. 事务 T1：插入新 `Shot`（`PROCESSING`，按 `shot_id` 算最终路径）→ commit（**新镜头隐藏，旧 READY 仍对外**）。
5. 原子搬运 staging 文件 → `active/shots/{shot_id}/`（同一文件系统 `os.replace`）。
6. 事务 T2：新镜头置 `READY` + 删除旧代次 `Shot`（**一次事务完成原子切换**）。
7. 提交后清理旧派生目录与 staging。

**禁止**：分析开始即删旧镜头、边生成边覆盖 active、失败后留下"DB 成功但文件不完整"的状态。
仅 `status=ready` 的镜头对外可见、可预览/下载。

---

## 6. 失败与恢复

- 任一步失败 → `MediaProcessingRun` 标 `FAILED` 并保留 `error_message`；旧 READY 镜头与文件**保持可用**；
  `Asset.status` 按是否仍有 ready 镜头回到 `shot_split` 或 `indexed`。
- 源文件缺失 → 标记 `source_missing`（不抛异常，避免 Celery 重试风暴）。
- 崩溃残留（非 ready 镜头、孤儿 active 目录、陈旧 staging）在**下次运行启动时回收**。
- 重试：API 的 `analyze-shots` / `shot-analysis/retry` 幂等——已有活动运行则返回该运行，否则新建（新代次）。
- `acks_late` + advisory lock：worker 崩溃后任务可重投，锁随连接释放，可安全重入。
- 服务重启后：DB 记录与已落地派生文件（命名卷）持久保留。

---

## 7. 资源限制（media-worker）

FFmpeg 属 CPU/磁盘/IO 密集型，PR-02 用**专用 `media-worker`**（仅消费 `media` 队列），与扫描
worker 隔离，默认并发 **1**（`MEDIA_WORKER_CONCURRENCY`）。

- 单次 ffmpeg 调用超时 `FFMPEG_TIMEOUT`（默认 300s），超时杀进程、检查返回码、stderr 截断。
- 写派生前磁盘空间预检 `DISK_MIN_FREE_MB`（默认 500MiB），不足则失败并提示。
- 临时文件用 staging，成功后清理；同一文件系统保证原子 rename。
- 逐镜头 commit 心跳（`heartbeat_at`）；无 Celery meta，进度只看 DB 行。

---

## 8. API

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| POST | `/api/assets/{id}/analyze-shots` | 发起分析（202，幂等） |
| GET | `/api/assets/{id}/shot-analysis` | 最近运行状态/进度（`no-store`） |
| POST | `/api/assets/{id}/shot-analysis/retry` | 重试（202，幂等） |
| GET | `/api/assets/{id}/shots` | 该素材的 ready 镜头（分页） |
| GET | `/api/shots` | 全部 ready 镜头（分页，可按 asset_id/status） |
| GET | `/api/shots/{id}` | 镜头详情（含来源素材信息） |
| GET | `/api/shots/{id}/thumbnail` \| `/keyframe` | 缩略图/关键帧（webp，长缓存） |
| GET | `/api/shots/{id}/preview` | 代理视频（支持 Range） |
| POST | `/api/shots/{id}/export` | 发起片段导出（202） |
| GET | `/api/exports/{id}` | 导出状态 |
| GET | `/api/exports/{id}/download` | 下载片段（附件） |

---

## 9. 浏览器播放与下载

- **原视频不直接暴露给浏览器**；浏览器只播放**代理视频**（`/api/shots/{id}/preview`）。
- **HTTP Range（必做）**：代理预览接口由 Starlette `FileResponse` 原生支持 Range：无 Range 返回完整文件，
  `Range: bytes=start-end` 返回 `206` + `Content-Range` + `Accept-Ranges: bytes` + `Content-Length`，
  非法范围返回 `416`。同源代理（`apps/web/app/api/[...path]/route.ts`）转发 Range 请求头并保留
  `content-length`/`content-range`/`accept-ranges`，确保浏览器**可拖动进度条 seek**。
- **缓存**：不可变派生文件（关键帧/缩略图/代理/导出）`Cache-Control: public, max-age=31536000, immutable`；
  任务状态接口 `no-store`。
- **下载片段**：按镜头起止时间从源视频导出。默认 `reencode`（H.264 + yuv420p + AAC + faststart，
  精确 seek，保证时间边界准确与浏览器/剪辑软件兼容）；`copy`（stream copy）为可选快速路径（非关键帧
  切点可能不准，非默认）。下载文件名经 `Content-Disposition` RFC5987 编码，**支持中文名**；磁盘文件名
  固定 ASCII（`clip.mp4`，置于唯一 `export_uuid` 目录，不覆盖已有导出）；导出异步、有状态、可重试、可追溯到 Shot 与源 Asset。

---

## 10. NAS 性能注意事项

- 视频并发转码占用大量 CPU/IO；NAS 上线建议保持 `MEDIA_WORKER_CONCURRENCY=1` 或按机器核数谨慎放大，
  必要时把 media-worker 放到独立算力更强的主机。
- 代理视频用于降低 NAS 预览带宽压力；缩略图体积小、可缓存、懒加载。
- 派生数据目录建议放 SSD；数据库与派生文件分目录。
- 4K / 大文件处理慢，建议夜间批量；磁盘空间需为派生文件预留（约源容量的 0.5~1 倍）。
- 源目录只读挂载（`:ro`），media-worker 仅 `open(rb)` 读源、只写 `/app/data`。

---

## 11. 测试

- 后端纯逻辑：边界后处理（合并/拆分/clamp/首尾余量/无转场兜底/单镜头/各时长）。
- 后端 ffmpeg（合成视频，`make_test_video` / `make_multi_scene_video`，无真实素材）：PySceneDetect 检出多场景、
  关键帧/缩略图/代理生成、代理 H.264/≤720/不放大/偶数尺寸、导出精确时长、损坏输入报错。
- 后端 DB+ffmpeg：拆镜头落库、原子代次替换（重分析不重复/不留孤儿）、单镜头、源缺失。
- 后端 API：分析触发/状态/重试、镜头列表/详情、文件服务（Range 206/416）、路径穿越→422、
  导出 202/状态/下载（中文名 RFC5987）、并发防重幂等、`shot_count` 富化。
- 前端（`vi.mock('@/lib/hooks')`）：素材分析入口、处理中/重试、镜头空态、镜头网格、镜头详情、预览、导出下载、错误态。

运行：`pytest`（仓库根，需 `TEST_DATABASE_URL` + ffmpeg）；`cd apps/web && npm run lint && npm run typecheck && npm test && npm run build`。
