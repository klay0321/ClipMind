# 产品素材关联与管理工作台（Product Media Workspace）

> PM 主线。让运营在一个页面完成"产品 ↔ 图片/视频/Shot/成片"的日常管理。
> **人工确认的产品素材关系 = 系统正式事实；文件名、路径、文本和视觉模型
> 结果 = 辅助候选**（绝不自动写入）。

## 1. 正式关系模型（product_media_link，迁移 0019）

- 单目标：`asset_id` / `shot_id` 恰好一个非空；目标产品 `family_id` 必填、
  `variant_id` 可选（service 校验归属，绝不从 Family 自动推断 Variant）。
- `role`：`primary`（每目标至多一个，DB 部分唯一；设主自动把旧主降为
  related）| `related`（多条——多产品同框是真实场景）。
- `origin` 六种：manual / bulk_manual / path_or_filename_confirmed /
  visual_suggestion_confirmed / text_suggestion_confirmed /
  migration_or_legacy。`visual_suggestion_confirmed` 仅在
  `VISUAL_EMBEDDING_PROVIDER=local` 时接受（fake 结果禁写，422）。
- 记录 `actor_label`（配置标签，不冒充认证身份）与创建/更新时间。
- 删除 = 物理删链接行；绝不触碰媒体文件。
- **不因素材移动断开**（FK 到稳定 Asset id）；**不因重新分析迁移历史事实**
  （Shot 继承是查询期合成，见下）；历史（retired）Shot 的关系保留可查，
  允许人工修正（响应标记 generation/is_historical）。

## 2. Shot 继承与覆盖（冻结语义）

```
effective(shot) = shot 自身 links        （若非空 → "本镜头独立设置（覆盖视频级）"）
                | asset links（继承）     （否则 → "继承自视频"）
```

视频级产品默认被全部镜头继承；单个镜头可独立覆盖（覆盖后视频级关系仍
可展开查看）。搜索/产品视图/未标注判定全部使用该有效语义。

## 3. 图片素材进入 Asset 管线（asset.media_kind）

- 新列 `media_kind`：'video'|'image'（回填 'video'）；扫描/上传按扩展名判定
  （`SUPPORTED_IMAGE_EXTENSIONS` = jpg/jpeg/png/webp）。
- 图片与视频同管线（只读源、扫描、稳定身份、位置历史、poster 缩略），但
  **无拆镜头/代理派生**（analyze-shots 对图片 422）；ffprobe 对图片返回
  video 流 + 宽高、duration 为空（Asset.duration nullable）。
- 与 ProductReferenceAsset 的区分：参考图 = 精选识别基线（data_dir 存储、
  质量治理）；普通产品图 = 源库素材（可未标注、走工作台管理）。

## 4. API（/api/product-media/*）

links（POST/PATCH/DELETE）/ links/bulk + bulk-delete（≤200，显式选择，
completed/skipped/failed 明细，单条失败绝不虚报整批）/ summary（产品列表
聚合计数）/ families/{id}/items?kind=image|video|shot|final_video（shot 含
继承并标记 source；final_video 经 confirmed usage 的有效产品推导）/
unassigned?kind=image|video|shot（继承语义：asset 已绑则其镜头不算未标注）/
assets/{id}/links / shots/{id}/links（own+inherited+effective）/
suggestions（确定性候选：目录名/文件名/别名/已有 AI 文本命中——只建议，
人工确认才落库）。

## 5. 搜索（Shot 检索 hard filter，排序零改动）

`ShotSearchRequest` 新增 `product_family_id` / `product_variant_id` /
`has_product_assignment` / `unassigned_only`——全部 hard filter（EXISTS
子查询含继承语义），不参与相关性分数，usage-aware 排序不变；Saved Search
JSONB 自动兼容。图片/视频的产品检索走工作台内部 API（不硬塞 Shot 返回
结构）。

## 6. 工作台（/product-media，导航"产品素材库"）

产品列表（family+variant/参考图/图片/视频/Shot/使用次数/入驻状态）→
产品素材详情（Tab 图片/视频/Shot/成片；解除关联/设主；Shot 标记继承或
独立；含历史开关）→ 未标注队列（图片/视频/Shot 切换、多选/全选本页、
批量绑定条、每卡候选建议）。Asset 抽屉与 Shot 详情集成 ProductLinkPanel
（当前关系/手动绑定/候选确认）。产品库（CatalogView）保持参考图管理职责。

## 7. AI 辅助（可选，绝不前置）

全部管理功能在视觉 provider 关闭时完整可用。视觉候选（PR#30）只是
Asset/Shot 页的辅助入口：人工点击"确认关联"才写 origin=
visual_suggestion_confirmed 的正式关系；禁止自动绑定 Top-1、自动批量确认、
从 Family 推断 Variant、把 unknown/ambiguous 显示为已识别。

## 8. 运营批量流程（OPS：分组审核 → 批量确认 → 统计）

面向"大量未标注素材连续整理"的主路径（`/product-media` 顶部
"候选批量审核"区）：

- **批量候选生成**：`suggest_for_assets_batch` 一次拉取词表（family
  中英名/code + family 级别名，排除 merged/archived），对每个未标注素材本地
  匹配目录/文件名，按类型优先级取 Top3——纯确定性、零 AI 调用、无 N+1。
- **分组队列**：`GET /unassigned/groups?kind=&group_by=suggested_family|
  directory|none`。组内给出组级建议产品、预览（≤6）与**显式 targets
  （≤200/组）**；无候选素材单列 "none" 桶，绝不冒充已识别；总量上限 500
  超出明确标记 truncated。
- **整组确认**：预览点击排除异常项 → 显式"绑定 N 项"（走 links/bulk），
  确认建议产品时 origin=path_or_filename_confirmed，改选其他产品时
  bulk_manual。**绝不默认选择全库、绝不自动确认**。
- **覆盖统计**：summary 每产品新增 effective_shot_count /
  final_video_count / coverage_gaps / coverage_status。状态由通用规则派生
  （缺参考图/缺视频/缺可用 Shot/没有最终成片；无任何产品名硬编码），
  全部达标显示"资料较完整"。
- 视觉候选仍只在 Asset/Shot 页显式点击、小批量使用（见 §7）；分组/批量/
  统计在视觉 provider 关闭时完整可用。

## 9. 操作审计与撤销（product_media_operation，迁移 0020）

- **append-only 事件表**：每次 single_link / bulk_link 写一行（kind、
  family、role/origin、requested/completed/skipped/failed 计数、
  created_link_ids、actor_label、detail）；undo 自身也是事件行，绝不改写
  或删除历史事件。
- **撤销语义**：`POST /operations/{id}/undo` 只删除**该操作创建且此后未被
  修改**的 link（判定：`updated_at == created_at`，创建时两者取同一时刻；
  任何 PATCH 触发 onupdate 即视为已修改）。被修改/已删除的条目保留并在
  removed/kept 明细中给出原因。原操作标记 undone_at 后不可重复撤销
  （409）；undo 事件本身不可再撤（422）。
- 撤销只删关系行，**绝不删除媒体、绝不回滚产品目录**。
- `GET /operations` 分页返回历史（undoable 由 kind+undone_at+
  created_link_ids 计算），工作台"操作历史"面板可直接撤销。

## 10. 验证

后端 `apps/api/tests/test_product_media.py` +
`test_product_media_ops.py`（分组/候选注入/审计/撤销/覆盖状态）；前端
`apps/web/__tests__/product-media/`；E2E `scripts/ci_product_media_e2e.py`
（9 标志 + RESTART_PERSIST）+ `scripts/ci_product_media_ops_e2e.py`
（6 标志 + POPS_RESTART_PERSIST_OK）；UI `e2e/pr-media-workspace.spec.ts` +
`e2e/pr-media-ops.spec.ts`；升级路径 `scripts/ci_db_upgrade_e2e.py`（至
0020）；真实素材只读验收（LIBRARY_READONLY / REAL_OPS）见 `.local` 报告
（不入库）。
