# 自动分析管线（AAP）：素材进来自动变可搜索

> 目标：运营不再手动逐条点"分析"。文件进入源目录后，系统自动完成
> 扫描 → 海报 → 拆镜头 → AI 理解 → 检索索引 全链路；搜索时一切就绪。

## 1. 链路与触发方式

```
NAS 新文件
  → 扫描（beat 定时 SCAN_INTERVAL_MINUTES / 手动点扫描）
  → 海报生成（原有自动）
  → 拆镜头（AUTO_ANALYZE_ON_SCAN=true 时自动入队；含补漏：上次遗漏的下次扫描自动补）
  → AI 理解（AUTO_AI_AFTER_SHOTS=true 时拆完自动入队；受日预算护栏）
  → 检索文档 + 向量（原有自动：AI 完成即重建）
```

- 所有衔接均为 commit 后 best-effort 入队（失败只记日志，绝不影响宿主任务），
  与既有 `_enqueue_search_rebuild` 同一模式。
- 幂等三保险：活动 run 幂等返回 + 部分唯一索引兜底 + 任务级 advisory lock；
  重复扫描/重复触发绝对安全，不重复计费（AI 输入指纹缓存仍生效）。

## 2. 配置（全部 env，零迁移；默认全关，逐项显式开启）

| 变量 | 默认 | 说明 |
|---|---|---|
| `AUTO_ANALYZE_ON_SCAN` | false | 扫描完成后自动为"无可用镜头"的视频入队拆镜头 |
| `AUTO_AI_AFTER_SHOTS` | false | 拆镜头完成后自动入队 AI 理解 |
| `AUTO_ANALYZE_MAX_PER_SCAN` | 200 | 单次扫描最多自动入队数（防任务风暴） |
| `AI_DAILY_BUDGET` | 0 | AI 日预算（ai_call_log.est_cost 口径，UTC 日；<=0 不限）。**只限自动路径，手动分析永不受限**；超限自动跳过并记日志，次日恢复 |
| `SCAN_INTERVAL_MINUTES` | 0 | beat 定时扫描全部源目录的间隔（<=0 禁用） |

beat 为独立 compose 服务（`beat`），schedule 状态存 `/app/data/beat/`。

## 3. 守卫（P0 假成功修复）

- 图片发起 AI 镜头分析 → **422**（图片没有镜头概念）。
- 无可用镜头的视频发起 AI → **409**（提示先拆镜头）。
- worker 防御线：AI run 若查不到任何 READY 镜头 → run **FAILED**（错误信息
  明确），素材状态按是否仍有可用镜头恢复为 SHOT_SPLIT / INDEXED——
  修复此前"空镜头假成功 + 状态被污染为 SHOT_SPLIT"的缺陷。

## 4. 批量分析 API（自动化之外的手动兜底）

`POST /api/assets/batch-analyze`：`{asset_ids | source_directory_id, stages:[shots|ai], max_items<=500}`
——**必须显式给范围，绝不隐式全库**；stage 语义：shots 只对"无可用镜头的
INDEXED 视频"，ai 只对"存在未打标可用镜头"的视频；活动 run 幂等跳过；
返回 matched/enqueued/skipped 明细与 truncated 标记。前端素材库
「一键补齐分析」逐目录调用该接口。

## 5. 全局处理概览

`GET /api/processing/overview`：scan/shots/ai 三队列 queued/running 计数、
全库 totals（已拆视频/已打标镜头/可搜索文档等）、配置回显（自动开关、
日预算与今日已花费）。素材库页顶常驻展示；有活动任务时前端 5s 轮询。

## 6. 验证

后端 `apps/api/tests/test_auto_pipeline.py`（守卫/筛选/批量/概览）+
`services/worker/tests/test_auto_chain.py`（空镜头 FAILED/幂等/预算口径）；
E2E `scripts/ci_auto_pipeline_e2e.py`（8 标志：上传→全程零点击→可搜索）；
UI `e2e/pr-auto-pipeline.spec.ts`；CI 中自动开关按步骤临时开启、跑完关回，
不影响其他 E2E 的手动断言。
