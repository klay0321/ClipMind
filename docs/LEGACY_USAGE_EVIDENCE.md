# 历史"已使用"路径证据（Legacy Usage Evidence）

> PR-C Gate B。把历史遗留的"已使用"目录/文件名标记，转化为**受控的弱证据**并交给人工审核。
> 正式使用血缘见 `docs/FINAL_VIDEO_USAGE.md`；素材身份与路径历史见 `docs/ASSET_IDENTITY.md`。

## 1. 冻结语义（本阶段不可扩大解释）

1. **证据绑定 Asset，不绑定 Shot**。历史标记只能说明"这个素材文件曾被用过"，无法定位到具体镜头，也无法定位到具体成片。
2. **接受（accept）一条证据 = 承认"该素材很可能曾被使用过"**——使用次数未知、来源 Shot 未知、对应成片未知。
3. **证据与正式血缘零关联**：
   - 不创建任何 `FinalVideoUsage` / `FinalVideoUsageOccurrence`；
   - 不创建任何"未知成片 / 历史成片 / 默认成片"占位 `FinalVideo`；
   - **绝不改变 `confirmed_usage_count`**（正式次数只来自 confirmed FinalVideoUsage，见 FINAL_VIDEO_USAGE.md）；
   - 系统不存在任何手工输入使用次数的入口。
4. 派生状态 `legacy_used_unknown` 的展示语义是"历史上用过（次数未知）"，**绝不允许显示成"已使用 1 次"**。
5. 规则修改/禁用/归档**不重解释历史证据**：run 与 evidence 都保存创建时的 `rule_snapshot`（快照冻结）。
6. 导入与预览的输入只来自 `asset_location.relative_path`（数据库中已索引的路径历史），**不做文件系统 IO、不读媒体、不改文件**。

## 2. 数据模型（迁移 `0018_legacy_usage_evidence`）

| 表 | 作用 | 关键约束 |
| --- | --- | --- |
| `legacy_usage_rule` | 受控匹配规则 | pattern 非空 CheckConstraint；`archived_at` 软归档 |
| `legacy_usage_import_run` | 预览/导入运行记录 | `rule_snapshot` JSONB 冻结当次规则集；8 个计数列 |
| `legacy_usage_evidence` | 弱证据本体 | `evidence_key` 全局唯一（幂等锚）；`asset_id` CASCADE 必填 |
| `legacy_usage_evidence_event` | 审核事件 | **append-only**，与状态变更同事务 |

`evidence_key = sha256(rule_id|asset_id|match_target|归一化匹配片段)`：同规则 + 同素材 + 同匹配事实全局唯一。同一事实在多个位置出现只算一条证据，`observation_count` 累加。

外键策略：`asset_id` CASCADE（素材删除连带证据）；`asset_location_id` / `rule_id` / `import_run_id` 均 SET NULL（位置/规则/运行删除不破坏证据，靠快照留痕）。

## 3. 规则引擎（`packages/shared/clipmind_shared/legacy_rules.py`）

**不支持任意正则**（无回溯引擎 ⇒ 无 ReDoS 面）。只允许白名单组合：

- `match_target`：`directory_segment` / `filename` / `filename_stem` / `extension` / `relative_path`
- `match_operator`：`equals` / `contains` / `starts_with` / `ends_with`

归一化管线：Unicode **NFKC** → 分隔符统一 `/` →（大小写无关时）**casefold**。全半角、大小写、混合分隔符的历史命名差异都能命中。

pattern 校验：非空、≤256 字符、不含 `..` 路径成分与 NUL。规则可限定 `source_directory_id`（只匹配某个源根）与位置状态范围（present / missing / historical——历史位置也可作为证据来源，因为"曾经在'已使用'目录里"本身就是历史事实）。

真实规则（例如 `directory_segment equals "已使用"`）**不写死在迁移或代码里**，一律通过 UI/API 创建。

## 4. 预览与导入

- `POST /api/legacy-usage-imports/preview`：**零写入**（不建 run、不建证据、不改任何状态），返回扫描/命中/将新建/已存在计数、按规则与按位置状态分布、≤20 条样例。
- `POST /api/legacy-usage-imports`：创建 run（冻结 `rule_snapshot`）→ Celery `clipmind.legacy_usage_import`（default 队列）异步执行；`dry_run=true` 时任务只统计不写证据。
- **幂等**：`evidence_key` 命中已存在证据时，只更新 `last_observed_at` / `observation_count` / `import_run_id` 并记 `observed_again` 事件——**绝不覆盖人工 `review_status`**，重复导入不产生新证据。
- 单条错误不中止任务（`error_count` 累计，`error_summary` 截断且不含绝对路径）；run 级 advisory lock 防并发重复执行。

## 5. 人工审核

状态机（单条 `accept` / `reject` / `mark-conflict` / `reset` + 批量 `bulk-accept` / `bulk-reject`，批量只作用于显式 `evidence_ids` 列表，**没有"一键全部接受"**）：

```
pending  --accept-->  accepted      accepted/rejected/conflict --reset--> pending
pending  --reject-->  rejected      pending/accepted/rejected --mark-conflict--> conflict
```

状态不符返回 409（批量则跳过并回报 `skipped_ids`）。每次动作行锁 + `LegacyUsageEvidenceEvent` 同事务写入（append-only，含 before/after 状态、操作人标签、备注）；`reset` 不删除任何事件历史。

## 6. Asset 派生状态与 usage-summary 扩展

按证据状态计数派生（优先级 conflict > accepted > pending > rejected > none）：

| `legacy_usage_state` | 含义 |
| --- | --- |
| `no_legacy_evidence` | 无任何证据 |
| `legacy_evidence_pending` | 有待审证据（无 accepted） |
| `legacy_used_unknown` | 有 accepted 证据——**历史上用过，次数未知** |
| `legacy_evidence_rejected` | 证据全部被驳回 |
| `legacy_evidence_conflict` | 存在标记冲突的证据 |

`GET /api/assets/{id}/usage-summary` 追加并列字段（confirmed 统计逻辑一行未动）：
`confirmed_usage_count`、`accepted/pending/rejected/conflict_legacy_evidence_count`、`legacy_usage_state`、
`usage_count_known`（= confirmed_usage_count > 0）、`final_video_known`（= distinct_final_video_count > 0）。
有 confirmed 使用时正式次数优先展示，legacy 仅作附加历史信息。Shot 的 usage-summary **不继承** Asset 证据（不均摊）；搜索/匹配排序不受证据影响（留待后续 PR 决策）。

`GET /api/assets/{id}/legacy-usage-summary` 返回该素材的证据明细（只读面板用）。

## 7. API 一览（前缀 `/api`）

| 方法/路径 | 说明 |
| --- | --- |
| GET/POST `/legacy-usage-rules`，GET/PATCH `/legacy-usage-rules/{id}` | 规则 CRUD（422=配置非法） |
| POST `/legacy-usage-rules/{id}/enable|disable|archive|restore` | 启停/归档（归档不删证据） |
| POST `/legacy-usage-imports/preview` | 只读预览（零写入） |
| POST/GET `/legacy-usage-imports`，GET `/legacy-usage-imports/{id}`，POST `/{id}/cancel` | 导入运行 |
| GET `/legacy-usage-evidence`（status/asset/rule 筛选 + 分页） | 证据列表（含 confirmed 对照列） |
| GET `/legacy-usage-evidence/{id}`，POST `/{id}/accept|reject|mark-conflict|reset` | 单条审核 |
| POST `/legacy-usage-evidence/bulk-accept|bulk-reject` | 批量审核（显式 id 列表 ≤500） |
| GET `/legacy-usage-evidence/{id}/events` | 审核事件（append-only） |
| GET `/assets/{id}/legacy-usage-summary` | 素材证据汇总（只读） |

## 8. 测试锁定的隔离保证

- accept 证据后：`FinalVideoUsage` 行数不变、`confirmed_usage_count` 不变、Shot usage-summary 不变；
- preview 前后：四张 legacy 表行数不变（零写入）；
- 重复导入：证据行数不变、`observation_count` 递增、人工 review_status 保持；
- 事件表 append-only：无 update/delete 路径，动作与事件同事务。

前端入口：`/usage-evidence` 中心（规则管理 / 导入任务 / 待审核 / 已审核）+ 素材详情只读"历史使用证据"面板。所有接受入口旁固定提示：**"接受历史证据不等于确认使用次数，也不等于确认对应成片或具体镜头。"**
