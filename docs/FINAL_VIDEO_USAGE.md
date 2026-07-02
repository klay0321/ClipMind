# 最终成片与 Shot 使用血缘(PR-B Gate A)

本文档是**正式使用次数语义的事实来源**,由后端测试锁定
(`apps/api/tests/test_final_video_usage.py`)。UI 与 API 展示的所有使用次数都是
本文规则的派生值。

## 数据链路

```
Final Video ──(asset_id)──> Asset(成片媒体文件,经上传或 NAS 只读扫描索引)
Final Video ──< Final Video Usage >── Source Shot ──> Source Asset
                     │
                     └──< Usage Occurrence(出现时间段,毫秒)
                     └──< Usage Event(append-only 审计)
```

- FinalVideo **引用已有 Asset**,不重复保存视频文件;归档不物理删除,也绝不删除
  Asset 文件。成片文件导入走现有上传流程(`POST /api/uploads`)。
- 同一 Asset 至多一个未归档 FinalVideo(部分唯一索引)。
- FinalVideo 不是 Product;可经项目/素材关联产品,产品绑定不是创建成片的条件。

## 正式使用次数(冻结语义)

```
Shot 正式使用次数
= 引用该 Shot 的 confirmed FinalVideoUsage 数量
= 按不同 Final Video 去重(UNIQUE(final_video_id, source_shot_id) 天然保证)
```

1. 同一 Shot 在同一成片出现多次,只计 1 次(多次出现记为 occurrence);
2. 每个出现位置单独记录 occurrence(源/成片双侧毫秒时间段);
3. 同一 Shot 被不同成片使用,分别计数;
4. `proposed` 不计数;
5. `suspected` 不计数(本阶段仅预留值,不由任何流程产生);
6. `rejected` 不计数;
7. `revoked` 不计数;
8. legacy path evidence(`legacy_path_rule`)不计数且**永不自动 confirmed**;
9. 项目**选择**镜头不计数(只会生成 proposed 候选);
10. 项目**锁定**镜头不计数(同上);
11. 导出剪辑清单/片段/ZIP 不计数(导出只证明"请求过导出");
12. 只有人工确认(confirm)后的成片引用计数;
13. 撤销(revoke)confirmed 引用后,次数**立即**重新计算;
14. 使用次数是血缘记录的**派生值**——系统中不存在任何可手工输入
    `usage_count = N` 的字段或接口;
15. Asset 使用统计 = 该素材全部 Shot 的 confirmed usage 聚合。

归档语义:FinalVideo 归档后历史 confirmed usage **继续计数**;只有明确 revoke
才减少次数;archived 成片不允许确认新 Usage(409)。

## 状态机

```
proposed ──confirm──> confirmed ──revoke──> revoked
proposed ──reject──> rejected
rejected / revoked ──restore-proposal──> proposed
```

- rejected/revoked 重新确认前必须先恢复为 proposed;
- confirmed 不会被 propose-from-project 重跑覆盖(幂等:已存在关系一律跳过);
- 所有状态转换加行锁(SELECT ... FOR UPDATE)并与事件写入同事务。

## 证据方式(evidence_method,受控 String 白名单)

| 值 | 本阶段 | 允许 confirmed |
|---|---|---|
| `manual` | ✅ 已实现(手工添加) | ✅ |
| `clipmind_project` | ✅ 已实现(从项目选择/锁定生成 proposed) | ✅(仍需人工确认) |
| `editor_project` | 预留(剪辑工程解析未实现) | ❌ |
| `visual_match` | 预留(PR-H) | ❌ |
| `audio_match` | 预留 | ❌ |
| `legacy_path_rule` | 预留(PR-C;永不自动 confirmed) | ❌ |

- `clipmind_project` 只读取 `script_segment.locked_shot_id / selected_shot_id`
  (明确人工动作);项目成员镜头、搜索结果、导出历史一律不生成候选;
- confidence 可空且只能 0–1;人工确认不伪造 confidence=1;
- evidence_summary / evidence_refs 只存脱敏受控信息(ID 与受控枚举),
  不存 API Key、绝对路径或图片二进制。

## 业务保护

- 自引用守卫:Source Shot 所属 Asset 与成片 Asset 相同 → 409;
- Source Shot 必须存在、READY 且源素材未缺失才能建立/确认引用;
- Project 删除不影响血缘(`final_video.project_id` SET NULL;Project 本阶段
  也无删除接口);产品更名不影响血缘(只引用 ID);
- 素材路径变化不断开血缘(血缘只引用 asset_id/shot_id;稳定内容身份属 PR-C);
- **镜头重新分析守卫**:素材镜头存在血缘引用时,`POST /api/assets/{id}/analyze-shots`
  返回 409(代次替换会物理删除旧镜头);DB 层 `source_shot_id` RESTRICT 兜底,
  worker 即使绕过也会因外键失败保留旧代次,绝不静默断血缘;
- 事件表 append-only:无更新/删除接口;actor_label 为非可信显示名(无鉴权)。

## API 一览

- 成片:`GET/POST /api/final-videos`,`GET/PATCH /api/final-videos/{id}`,
  `POST /api/final-videos/{id}/archive|restore`
- 血缘:`GET/POST /api/final-videos/{id}/usages`,
  `POST /api/final-videos/{id}/propose-from-project`,
  `GET /api/final-videos/{id}/lineage`
- 引用:`GET/PATCH /api/final-video-usages/{id}`,
  `POST /api/final-video-usages/{id}/confirm|reject|revoke|restore-proposal`,
  `GET /api/final-video-usages/{id}/events`
- 时间段:`GET/POST /api/final-video-usages/{id}/occurrences`,
  `PATCH/DELETE /api/final-video-usage-occurrences/{id}`
- 统计:`GET /api/shots/{id}/usage-summary`,`GET /api/assets/{id}/usage-summary`,
  `GET /api/shot-usage-summaries?shot_ids=...`(批量徽标)

## 本阶段明确不做

最终成片自动视觉/音频反查(PR-H)、剪辑工程文件解析、历史"已使用"目录导入(PR-C)、
full_hash 补算(PR-C)、使用感知搜索排序(PR-E)、用户登录与真实审核权限。
UI 必须如实显示:项目中已选择/锁定的镜头只会生成候选引用,人工确认后才计入
正式使用次数。
