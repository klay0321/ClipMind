# UI 参考图映射（UI_REFERENCE_MAP）

> 4 张 UI 参考图（`docs/ui-reference/`）是**开发与验收依据**，不是普通灵感图。本文把每张图的页面区域逐项映射到：功能、路由、React 组件、后端 API、数据表、所属 PR、状态、验收步骤、实际截图。
> 参考图**仅作设计/交互参考，不作为运行时前端资源**。不实现的功能在前端不显示假状态、不伪造 AI 结果。

## 状态枚举（仅允许使用）

`未开始` / `计划中` / `开发中` / `已实现` / `已验证` / `后续阶段`

> 约束：占位 UI **不得**标记为"已实现"。"已实现"指真实 API 闭环且可交互；"已验证"指有自动化或人工验收证据（截图/测试）。

## 所有前端 PR 的共同要求

1. 页面结构接近 UI 参考图；2. 保留绿色主操作色；3. 桌面信息密度高但不拥挤；4. 不允许重叠/越界/横向失控；5. 真实 API 数据，不用 Mock 伪造完成状态；6. 未实现功能显示真实状态；7. AI 原始结果与人工结果视觉区分；8. 风险用黄/红；9. 加载/空/处理中/成功/失败/重试状态齐全；10. 调试信息默认收起；11. 保留已有上传/封面/海报/预览/关键帧/下载能力；12. 每个前端 PR 提供真实运行截图（建议 1440×900 与 1600×900）；13. PR 描述逐项对照本表；14. 不得只改外观而无后端闭环。

---

## 参考图 01 — `01-shot-splitting-and-tagging.jpg`（拆镜头与打标）

对应：PR-02（镜头/关键帧/预览/下载，已实现）+ PR-03A（真实 AI 状态/只读描述）+ PR-03B（AI 标签/风险/质量/详情编辑/人工审核）。

| 区域 | 功能 | 路由 | 组件 | 后端 API | 数据表 | PR | 状态 | 验收步骤 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 中间 | 镜头卡网格（序号/时长/缩略图） | `/shots` | `ShotCard` | `GET /shots` | shot | 02 | 已实现 | 打开 /shots 看到镜头网格 |
| 右侧 | 代理视频播放（Range seek） | `/shots` | `ShotDetail` | `GET /shots/{id}/preview` | shot | 02 | 已实现 | 详情拖动播放代理视频 |
| 右侧 | 多关键帧条（沿镜头采样） | `/shots` | `ShotDetail` | `GET /shots/{id}/keyframe/{i}` | shot | 02 | 已实现 | 点击帧切换主关键帧 |
| 右侧 | 片段导出下载 | `/shots` | `ShotDetail` | `POST /shots/{id}/export`,`GET /exports/{id}/download` | export | 02 | 已实现 | 导出后下载片段 |
| 左侧 | 筛选栏（产品/场景/画面/口播） | `/shots` | `FilterSidebar`（现占位"待AI"） | `GET /tags`,`POST /search` | tag/shot_tag | 03B/04 | 后续阶段 | 标签筛选返回结果 |
| 右侧 | **AI 分析状态/只读一句话描述** | `/shots` | `ShotDetail`（扩展） | `GET /shots/{id}/ai` | ai_shot_analysis | **03A** | 计划中 | 已分析镜头显示真实状态+描述 |
| 右侧 | **AI 标签/风险/质量/置信度** | `/shots` | `ShotDetail`（扩展） | `GET /shots/{id}` + 标签 | shot_tag | 03B | 后续阶段 | 显示结构化标签、风险黄/红 |
| 右侧 | **审核：确认/修改/驳回/无法判断** | `/shots` | 新 `ReviewPanel` | `POST /shots/{id}/review`,`PUT /shots/{id}` | review | 03B | 后续阶段 | 人工修改后再分析不被覆盖 |

## 参考图 02 — `02-asset-management.jpg`（素材统一管理）

对应：素材统一管理（上传/封面/预览/产品/镜头数/AI状态/待审核数/风险数/继续分析）。

| 区域 | 功能 | 路由 | 组件 | 后端 API | 数据表 | PR | 状态 | 验收步骤 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 表格 | 素材列表（分页/搜索/状态筛选） | `/assets` | `AssetsView`,`Toolbar` | `GET /assets` | asset | 01 | 已实现 | 分页/按名/状态筛选 |
| 表格 | 上传素材 | `/assets` | `AssetsView` | `POST /uploads` | asset | 02 | 已实现 | 上传视频后自动索引 |
| 表格 | 封面（已分析镜头帧） | `/assets` | `AssetTable.Cover` | `GET /shots/{id}/thumbnail` | shot | 02 | 已实现 | 有镜头的素材显示帧封面 |
| 表格 | **素材海报（未分析也有封面）** | `/assets` | `AssetTable.Cover` | `GET /assets/{id}/poster` | asset.poster_path | Gate0.5 | 开发中 | 未分析素材显示 FFmpeg 海报 |
| 表格 | 预览（首镜头代理） | `/assets` | `PreviewModal` | `GET /shots/{id}/preview` | shot | 02 | 已实现 | 点预览播放首镜头 |
| 表格 | 镜头数 + 拆镜头状态 | `/assets` | `AnalysisCell` | `GET /assets/{id}/shot-analysis` | media_processing_run | 02 | 已实现 | 显示镜头数与分析状态 |
| 表格 | **AI 分析状态/继续分析** | `/assets` | `AnalysisCell`（扩展） | `GET/POST /assets/{id}/ai-analysis` | ai_analysis_run | **03A** | 计划中 | 显示真实 AI 状态、可发起分析 |
| 表格 | **待审核数 / 风险数** | `/assets` | `AnalysisCell`（扩展） | `GET /assets/{id}`（聚合） | shot_tag/review | 03B | 后续阶段 | 显示待审核与风险计数 |
| 表格 | **产品归属** | `/assets` | `AssetTable`（现"未识别"） | `GET/PUT /assets/{id}`（product_id） | product | 03B | 后续阶段 | 显示/编辑产品归属 |

## 参考图 03 — `03-script-matching.jpg`（脚本匹配与剪辑清单）

对应：PR-05。当前 0%，后续阶段。

| 区域 | 功能 | 路由 | 组件 | 后端 API | 数据表 | PR | 状态 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 左侧 | 脚本输入（粘贴/上传 TXT/MD/Word） | `/script`（新） | 新建 | `POST /scripts` | script_project | 05 | 后续阶段 |
| 左侧 | 段落拆分 + 画面需求 | `/script` | 新建 | `POST /scripts/{id}/parse` | script_segment | 05 | 后续阶段 |
| 右侧 | 每段候选镜头 + 匹配度 + 推荐理由 | `/script` | 新建 | `POST /scripts/{id}/match` | shot_recommendation | 05 | 后续阶段 |
| 右侧 | 补拍建议 / 无素材提示 | `/script` | 新建 | （match 返回） | script_segment | 05 | 后续阶段 |
| 底部 | 剪辑清单导出（CSV 起） | `/script` | 新建 | `POST /scripts/{id}/export` | export | 05 | 后续阶段 |

## 参考图 04 — `04-description-matching.jpg`（画面描述匹配）

对应：PR-04。当前占位，后续阶段。

| 区域 | 功能 | 路由 | 组件 | 后端 API | 数据表 | PR | 状态 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 左侧 | 画面描述输入 + 产品条件 + 风险条件 | `/match`（新） | 新建 | `POST /search` | — | 04 | 后续阶段 |
| 右侧 | 候选镜头 + 匹配度 + 匹配理由 | `/match` | 新建 | `POST /search` | shot/shot_tag | 04 | 后续阶段 |
| 右侧 | 预览 + 下载 | `/match` | 复用 `ShotDetail` | `/shots/{id}/preview`,`/exports/...` | shot/export | 04 | 后续阶段 |
| — | 搜索历史 | `/match` | 新建 | `GET /search/history` | search_history | 04 | 后续阶段 |

---

## 截图归档约定

每个前端 PR 合并前，把真实运行截图（1440×900 / 1600×900）放入 `docs/ui-reference/screenshots/<pr>/`，并在 PR 描述与本表"实际截图"列回填链接。截图为开发产物，**不得伪造**未实现功能的界面。
