# 使用感知检索与可解释排序（Usage-Aware Search）

> PR-E。让"这个镜头有没有用过、用了几次、多久没用"参与搜索的**过滤与排序**，
> 并对每个结果给出可解释的分数分解。使用信息只能**调整**候选的过滤和排序，
> 不能伪造语义相关性，也不能把历史弱证据等同于正式使用事实。
> 正式血缘语义见 `docs/FINAL_VIDEO_USAGE.md`；弱证据语义见
> `docs/LEGACY_USAGE_EVIDENCE.md`；检索链路见 `docs/SEMANTIC_SEARCH.md`。

## 1. 冻结原则

- **default 模式与旧行为逐位一致**：不传新参数（或 `usage_mode=default`）时，
  召回、排序、分数、总数与 PR-E 之前完全相同；usage 排序分支整体跳过，
  `usage_adjustment` 恒为 0，原 `score` 字段永不改变。
- **正式次数只来自 confirmed FinalVideoUsage**，且按**不同成片去重**计数
  （同一成片多次 occurrence 不增加次数）。
- **proposed / suspected 只展示、绝不参与排序**（不加分不减分）。
- **legacy 弱证据**只有 `review_status=accepted` 才产生一个**固定的弱提示项**
  （不随证据条数放大），且其权重上限（0.05）显著低于 confirmed 信号；
  pending / rejected / conflict 的调整恒为 0。
- 使用调整有**硬上限**：单结果 `|usage_adjustment| ≤ 0.35`；调整只作用于
  排序，不改写语义相关度 `base_score`。
- 排序解释**绝不只显示一个"推荐分"**：始终给出 base + 各调整项 + 最终分。

## 2. 使用特征投影（UsageFeatureService）

`batch_features(db, shot_ids)` 用 4 条固定聚合 SQL 一次拉取整页/整候选池特征
（与候选数量无关，无 per-result 查询）：

| 特征 | 口径 |
| --- | --- |
| `shot_confirmed_usage_count` | 该镜头 confirmed usage 的**去重成片数** |
| `shot_last_confirmed_used_at` | 最近一次 confirmed 的 `confirmed_at` |
| `asset_confirmed_usage_count` / `asset_distinct_final_video_count` | 同素材（当前代次）聚合 |
| `asset_used_shot_count` / `asset_total_current_shot_count` | 区分"当前镜头没用过但同素材其他镜头用过" |
| `accepted_legacy_evidence_count` | 仅 accepted 的弱证据条数 |
| `pending_formal_count` | proposed + suspected 的待审数量（仅展示） |

`usage_state` 优先级：`confirmed_used` > `legacy_used_unknown` >
`usage_needs_review` > `never_confirmed_used`。

只统计当前代次镜头（`retired_at IS NULL`）；历史代次不进入检索也不进入特征。

## 3. 请求参数（`POST /api/search/shots` 新增，全部可选）

| 参数 | 默认 | 说明 |
| --- | --- | --- |
| `usage_mode` | `default` | `default` / `prefer_unused` / `only_never_confirmed` / `exclude_high_frequency` / `least_recently_used` |
| `usage_scope` | `combined` | `shot`（仅镜头）/ `asset`（仅素材）/ `combined`（Shot 主信号 + Asset 轻量辅助）。硬过滤永远按 Shot 口径 |
| `max_confirmed_usage_count` | null | 硬过滤：正式次数上限（`exclude_high_frequency` 必须显式给出） |
| `min_days_since_last_use` / `exclude_recently_used_days` | null | 硬过滤：最近 N 天用过的排除；两者同给取更严（max） |
| `include_legacy_unknown` | true | false 时 legacy 弱提示不参与排序也不出 reason |
| `usage_preset` | `balanced` | `balanced` / `strong_unused` / `relevance_first` |
| `usage_weights` | null | 请求级受约束覆盖；越权（NaN/Inf/超上限/未知字段/legacy>0.05/decay∉[1,365]）返回 422 |
| `include_usage_explanation` | true | false 时省略 `usage` 块与 `usage_reasons`（瘦身响应） |

## 4. 排序公式

```
final_score = base_score
            + unused_bonus                        # 从未正式使用
            − count_penalty   × log1p(count)       # 次数越多惩罚越大（对数饱和）
            − recency_penalty × exp(−days/decay)   # 越近惩罚越大（指数衰减）
            − asset_penalty   × log1p(asset_uses)  # 同素材其他镜头被用过（轻量）
            − legacy_penalty                       # accepted 弱证据固定弱提示
            (+ lru_bonus × (1 − exp(−days/decay))  # 仅 least_recently_used 模式)
```

- 总调整钳制在 `±0.35`；各权重服务端上限 0.20，legacy 上限 0.05。
- 并列分确定性 tie-break：`final ↓ → base ↓ → shot_id ↑`。
- 预设：`balanced`（默认）、`strong_unused`（强未使用优先）、
  `relevance_first`（相关性优先，几乎不动排序）。

## 5. 硬过滤与候选饥饿防护

- `only_never_confirmed`：`shot_confirmed_usage_count == 0`（accepted legacy
  **不**被排除——它不是正式使用事实）。
- 硬过滤在候选池上执行；若"截断的召回池 + 过滤"导致结果不足页大小，服务端
  自动**扩大召回池重试**（池 ×2，至多 3 轮，上限 `SEARCH_CANDIDATE_POOL_MAX`，
  默认 1000）。
- 响应 `usage_stats` 记录：`requested_top_k` / `candidate_pool_size` /
  `filtered_count` / `returned_count` / `expansion_rounds` /
  `candidate_limit_reached`——"前 50 全被用过"的压力场景不会静默返回空。

## 6. 响应可解释字段

每个结果新增（default + `include_usage_explanation=false` 时省略 usage 块）：

- `base_score`（原融合相关性）/ `usage_adjustment` / `final_score`
  （default 模式 `final == base == score`）。
- `usage`：第 2 节全部特征 + `usage_state`。
- `usage_reasons[]`：`{code, adjustment, message}`，如 `shot_never_used` /
  `shot_used_multiple_times` / `shot_recently_used` /
  `least_recently_used_bonus` / `asset_reused_across_videos` /
  `legacy_used_unknown_hint`。

## 7. Search UI（/search）

- 搜索框下方五档快捷模式 pills（默认排序 / 优先未使用 / 只看从未正式使用 /
  排除高频素材 / 优先久未使用）；使用条件本身是合法搜索信号（无查询词也可浏览）。
- 高级筛选内：次数阈值 / 最近 N 天 / 统计范围 / 排序预设 / 弱证据开关 /
  解释开关。
- 结果卡徽标（冻结文案）：confirmed → "正式使用 N 次"（可跳转 /usage-review）；
  accepted legacy → "历史上可能使用过（次数未知）"（**绝不带数字**，可跳转
  /usage-evidence）；proposed → "存在待确认使用记录"（**绝不显示为已使用**）。
- 排序解释展开块：语义相关度 + 各调整项 + 最终分数三段齐全。
- default 模式下 UI 请求体**不携带任何 usage 字段**（前端侧 parity 保证）。

## 8. Saved Search 兼容（零迁移）

`SavedSearch.query` 是 JSONB 原文，经 `ShotSearchRequest.model_validate` 反序列化：
新 usage 字段自动随保存/恢复流转；**老数据缺字段一律回退 default**（行为与
保存时完全一致）。无新表、无迁移。

## 9. 验证与已知边界

- 后端 `apps/api/tests/test_usage_aware_search.py`（权重校验 / 调整方向与 cap /
  作用域隔离 / legacy 弱隔离 / 批量投影口径 / default 逐位 parity / 硬过滤 /
  候选扩张 / 422 / Saved Search 往返）；前端
  `apps/web/__tests__/search/usage-aware.test.tsx`。
- 中性排名基准 E2E `scripts/ci_pr_e_usage_search_e2e.py`：空查询浏览模式 +
  `created_from` 隔离 → **base 全 0**，排序差异 100% 来自 usage 调整，对
  FakeProvider 与真实 Provider 都成立；UI E2E `e2e/pr-e-usage-search.spec.ts`。
- **已知边界**：真实素材库当前尚无足量 confirmed 血缘，"使用感知排序在真实
  业务分布上的质量"**未验证**（不声称 `PR_E_REAL_RANKING_QUALITY_PROVEN_OK`）；
  真实验收仅覆盖特征可见性 / default parity / 只读安全范围。
