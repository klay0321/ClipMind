# 统一使用记录中心（Usage Review Center）

> PR-D。为运营提供**统一的人工审核工作台**：正式成片血缘（FinalVideoUsage）与
> 历史路径弱证据（LegacyUsageEvidence）并列审核、typed 批量操作、从弱证据补录
> 正式血缘。正式血缘语义见 `docs/FINAL_VIDEO_USAGE.md`；弱证据语义见
> `docs/LEGACY_USAGE_EVIDENCE.md`。

## 1. 冻结原则：统一展示，但不统一事实

- **零新表零迁移**：`ReviewItemOut` 是纯输出投影；事实仍在 `final_video_usage` /
  `legacy_usage_evidence`（与各自 append-only Event 表）。不存在把两类记录混在
  一起的事实表，也绝不为列表展示复制一份 usage 数据。
- 所有状态转换**继续调用原领域 Service**（原状态机、行锁、事件同事务）；统一
  中心不直写底层状态字段、不绕过既有事件审计。
- **confirmed lineage 永远高于 legacy evidence**；accepted legacy 绝不显示成
  confirmed；proposed 绝不显示成"已使用"。
- legacy 证据**没有 Shot、没有成片**：对应字段恒为 null，不造占位对象。
- 两类计数**并列展示、绝不相加**为"总使用次数"；正式次数仍只来自 confirmed
  FinalVideoUsage（只能被 formal confirm/revoke 改变）。

## 2. 统一 Read Model

`item_type`：`final_video_usage` | `legacy_usage_evidence`。

`review_group`（五组）：

| 组 | formal 状态 | legacy 状态 |
| --- | --- | --- |
| needs_review | proposed / suspected | pending |
| accepted_or_confirmed | confirmed | accepted |
| rejected | rejected | rejected |
| conflict | — | conflict |
| revoked | revoked | — |

`source_strength`（七级可信等级，展示顺序即可信度）：
`confirmed_lineage` > `manual_proposed_lineage`（proposed + evidence_method=manual）
> `project_proposed_lineage`（proposed + 其他 method）> `suspected_lineage`
> `accepted_legacy_evidence` > `pending_legacy_evidence` > `rejected_or_conflict`。

`available_actions` 由原状态机导出（formal：confirm/reject/revoke/restore_proposal；
legacy：accept/reject/mark_conflict/reset），UI 与 bulk 均以此为准。

## 3. 查询 API

- `GET /api/usage-review/summary`：formal 五态 + legacy 四态分组计数 +
  `needs_review_total`（= proposed+suspected+pending，**审核工作量口径**）。
  刻意不存在 `total_used_count`。
- `GET /api/usage-review/items`：筛选 item_type / review_group / source_strength /
  product_family_id / product_variant_id / asset_id / final_video_id /
  source_directory_id / created_from / created_to / q / page / page_size /
  sort(±created_at)。后端分页；确定性排序键 (created_at, item_type, id desc)；
  两表各查后归并切片；装配阶段批量 IN 查询（固定查询数防 N+1）。
  `final_video_id` 筛选天然排除 legacy；product 维度经兼容桥
  `product_family.legacy_product_id → asset.primary_product_id`（variant 退化为
  其 family 的兼容产品——Asset 无 variant 级绑定）。
- `GET /api/usage-review/items/{item_type}/{item_id}`：统一头 + 原始领域数据 +
  各自事件时间线（两类事件结构原样返回，不拼成单一事件对象）。

## 4. typed bulk（POST /api/usage-review/bulk）

- items 显式列出（1..500），**不允许无筛选全库操作**；
- **混合类型批次 422**（第一版拒绝，减少误操作）；action 与 item_type 不匹配 422；
- 逐条调用原领域 Service：**409 → skipped**（幂等策略：已 confirmed 再 confirm、
  已 accepted 再 accept 均 skip，API/UI/测试统一）；404 → failed；
  返回 succeeded/skipped/failed + 逐条明细（一条失败绝不虚报成功条目）；
- 每条成功操作写原领域 Event；actor_label 仍是非可信显示名。

## 5. 从弱证据补录正式血缘（clue → manual proposed）

Legacy 行操作「建立正式成片血缘」：Asset 自动预填 → **人工**选择 Final Video →
**人工**从该 Asset 的 current/historical 代次镜头中选择具体 Shot（**绝不默认
选中第一个**、证据绝不自动决定 Shot/成片）→ 复用既有 manual-add API 创建
`manual proposed` usage → 用户在审核列表**再次明确 confirm** 才计入正式次数。
同一 FinalVideo+Shot 已有关系时返回 409 并展示已有关系；创建后证据本体保留
（可继续 accept 或保持 pending）。本阶段无任何自动匹配算法。

## 6. UI（/usage-review「使用记录中心」）

分区：总览 / 待审核（默认）/ 正式血缘 / 历史证据 / 已处理（分组筛选）+
「规则与导入管理」入口（原 /usage-evidence 保留全部能力）。

- 类型标签颜色图标明显不同：`▶ 正式血缘候选`（蓝）/ `🕘 历史弱证据`（琥珀）；
- 批量：选择当前页 / 清除选择 / typed 动作 + **二次确认** + 成功/跳过/失败结果；
  混选时禁用批量并说明原因；
- 详情抽屉：原始领域数据 + 事件时间线 + 关联对象（legacy 显式说明
  "历史证据无法定位镜头/成片"）；
- 页面固定双提示（测试锁定）：
  **"正式使用次数只来自已确认的成片与镜头血缘。"**
  **"历史路径证据仅表示"可能曾使用，次数和成片未知"。"**

集成：Asset 详情统一摘要（正式次数 / 正式候选 / 历史待审 / 冲突 +
「历史上用过（次数未知）」状态陈述——不带数字）；Shot 页只显示正式
FinalVideoUsage（不继承 Asset 级证据）；Final Video 详情增加
「进入统一审核中心」入口。

## 7. 明确不做（本阶段）

使用感知搜索排序、未使用优先、推荐分数、视觉/音频反查、自动绑定成片或镜头、
自动确认证据、从证据生成 usage count、Asset 合并、用户权限、任务分配、通知。
后续：PR-E 使用感知检索排序 → PR-F 产品视觉识别 → PR-G 多路召回 → PR-H 成片反查。
