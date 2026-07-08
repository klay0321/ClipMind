# 状态语义总表（State Semantics）

本文档回答一类反复出现的问题："某个状态下，结果到底算不算生效、能不能被搜索到？"
审核状态机在**镜头、图片、使用记录**三个域复用，但各域的 effective（有效结果）与可搜性
细节不同。以下为唯一权威口径（与代码同步维护；代码为准的源文件在每节标注）。

## 1. 审核状态机（三域共用）

源：`packages/shared/clipmind_shared/review/state_machine.py`

| 动作 | 允许的起始状态 | 目标状态 |
|---|---|---|
| confirm | unreviewed, pending_review | confirmed |
| modify | unreviewed, pending_review, confirmed, modified | modified |
| reject | unreviewed, pending_review, confirmed, modified | rejected |
| unable | unreviewed, pending_review | unable |
| reopen | unreviewed, confirmed, modified, rejected, unable | **总是 pending_review** |

要点：
- reject/modify 可以从 confirmed/modified 再次发起（人工可以改主意）；
- unable 只能从未定态发起（已有人工结论就不该"无法判断"）；
- **reopen 的目标永远是 pending_review**，不回到 unreviewed。

## 2. 有效结果（effective）与可搜性 —— 镜头域（权威定义）

源：`packages/shared/clipmind_shared/review/effective.py`（`effective_result`）

| review_status | effective source | 生效结果 | 可搜 |
|---|---|---|---|
| confirmed / modified | human | confirmed_result | ✅ |
| rejected | rejected | 无 | ❌ |
| unable | unable | 无 | ❌ |
| unreviewed / **pending_review** | ai | AI parsed_result（临时） | ✅（有 AI 结果时） |
| （无 AI、无人工） | none | 无 | ❌ |

**常见疑问直接回答：reopen 之后（pending_review）AI 结果算生效吗？——算。**
pending_review 与 unreviewed 同样回退到 AI 临时结果、可被搜索；区别只是它明确
标记"需要人工再看"。三个域一致。

### 镜头域附加轴：stale（人工结果失效）

源：`apps/api/app/services/review_service.py`（`compute_effective`）

- **generation 变化**（重新拆镜头，帧变了）→ 人工结果 stale（`generation_changed`），
  effective 降级为 AI 临时结果；
- **同代 fingerprint 变化**（换模型/提示重打，帧没变）→ 人工结果**仍有效**，
  仅标记 `has_newer_ai_result=True` 提示有新 AI 结果可参考。

## 3. 图片域（与镜头同款，减去代次）

源：`apps/api/app/services/image_review_service.py`；
索引侧 `services/worker/clipmind_worker/search/asset_indexer.py`（`_image_result`）

- 图片无 generation、无 tag 投影；审核落地后由 asset 文档重建让 effective 进索引。
- rejected / unable → 索引器将 asset 检索文档置 **excluded**（不可搜，这是决定不是故障）。
- confirmed / modified 需 `confirmed_result` 非空才按 human 生效。
- 视频类型的 asset 检索文档由镜头 effective 聚合而来，没有独立的"视频级审核轴"。

## 4. 使用记录域（PR-D 统一审核中心）

源：`apps/api/app/services/usage_review_service.py`

| 对象 | 原始状态 | 审核分组 |
|---|---|---|
| 历史证据 evidence | proposed / suspected | needs_review |
| 历史证据 evidence | confirmed | accepted_or_confirmed |
| 使用记录 usage | pending | needs_review |
| 使用记录 usage | accepted | accepted_or_confirmed |

历史弱证据（legacy evidence，PR-C.B）独立一轴：pending / accepted / rejected，
接受后转正式 usage，与检索加权（PR-E usage-aware ranking）解耦。

## 5. 其他状态轴速查

| 轴 | 状态 | 语义 |
|---|---|---|
| 视觉候选 visual_product_candidate | pending | 可被新一轮候选置换 |
| | dismissed | **永不复活**（同一 family 不再自动提示） |
| | confirmed | 已回填正式 product_media_link |
| 产品两轴分离 | family.status=active | 素材库/检索可用的前提 |
| | onboarding_status | 入驻审核进度，独立于上者 |
| AI 镜头/图片分析 | pending/completed/degraded/failed/skipped | degraded=能力不足降级；skipped=指纹命中缓存 |
| 检索文档 | indexed + is_searchable | 唯一可搜门控 |
| | excluded | 按规则排除（驳回/无有效结果/空文档） |
| 文本向量 | completed/degraded/pending | degraded=仅词法可搜，语义召回缺失 |
| 视觉向量 visual_media_embedding | completed/failed | (target,provider,model) 唯一；sha 防重算 |

## 6. 一张图：为什么"这张图搜不到"

按序检查（与 `GET /api/assets/{id}/trace` 六环节一致）：

1. **scan**：asset.status 是否 indexed（error/source_missing 直接止步）
2. **derive**：图片有没有海报（AI 视觉输入依赖）；视频有没有 ready 镜头
3. **ai**：有没有 AI 理解结果（失败/缺失都不可搜）
4. **review**：是否被驳回/无法判断（excluded 是决定，不是故障）
5. **document**：检索文档是否 indexed 且 is_searchable
6. **embedding**：文本向量 degraded 只影响语义召回；视觉向量缺失影响以图搜图/视觉候选

trace 端点把这六步一次性列出并给出下一步动作提示；全局滞后计数见
`GET /api/health/pipeline` 与首页"管线健康"卡片。
