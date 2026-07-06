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

## 8. 验证

后端 `apps/api/tests/test_product_media.py`；前端
`apps/web/__tests__/product-media/`；E2E `scripts/ci_product_media_e2e.py`
（9 标志 + RESTART_PERSIST）；UI `e2e/pr-media-workspace.spec.ts`；
真实素材只读验收（LIBRARY_READONLY 标志）见 `.local` 报告（不入库）。
