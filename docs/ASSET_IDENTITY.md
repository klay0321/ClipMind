# 稳定素材身份、路径历史与 Shot 分析代次(PR-C Gate A)

本文档是**素材内容身份语义的事实来源**,由测试锁定
(`services/worker/tests/test_identity_scan.py`、`apps/api/tests/test_asset_identity_api.py`)。

## 冻结的内容身份语义

```
路径不是 Asset 身份;文件名不是 Asset 身份;mtime 不是 Asset 身份;
文件大小不是 Asset 身份;quick fingerprint 不是最终权威身份;
完整内容 SHA256 才是精确字节身份。
```

分级判断:

| 层 | 内容 | 用途 |
|---|---|---|
| 候选筛选 | size / duration / 容器 / 宽高 / mtime | 只筛候选,不认定同一内容 |
| Quick Fingerprint | sha256(size + 头/中/尾 1MiB),版本 `qfp1` | 快速筛选疑似移动、决定是否算完整哈希;**不能单独自动合并有业务数据的 Asset** |
| Full SHA256 | 完整字节哈希(分块 8MiB,前后 size+mtime_ns 核对) | 权威字节身份:确认移动/改名、精确重复检测、内容替换验证 |

相同视频的转码版/裁剪版/调色版/变速版 SHA256 不同,本阶段视为**不同内容**
(视觉近似识别属 PR-H,不在本阶段猜测)。不依赖 inode/file id(SMB/NAS 下不可靠)。

## 数据模型

```
Asset          = 稳定逻辑内容实体(id 永不因移动改变)
AssetLocation  = 一个或多个物理位置(source root + 安全相对路径;历史不物理删除)
Shot           = 某次分析代次的镜头(retired_at NULL=current)
```

- Asset 旧路径字段保留为**兼容投影**(= primary 位置),旧 API/前端零改动;
- 同一 root + normalized_path 同时只有一个非 historical 位置(部分唯一索引);
- 一个 Asset 至多一个 primary 位置(部分唯一索引);
- `fingerprint_state`:pending / quick_ready / full_ready / failed / stale。

## 扫描移动/复制识别(场景 A–E)

- **A 路径不变、内容不变**:touch,继续用原 Asset,不重新分析;
- **B 同路径内容替换**(quick_hash 变化):位置标 `conflict` + 指纹标 `stale`,
  **不静默覆盖身份、不迁移血缘**;单素材重扫(rescan)= 人工显式接受替换
  (接受时旧内容指纹作废);
- **C 移动/改名**(旧路径消失 + 新路径 full SHA256 相同):同一 Asset relink——
  旧位置转 historical、新位置 present primary,Asset ID 与产品/分析/收藏/项目/
  使用血缘全部保留,不重复创建 Asset;
- **D 复制**(旧路径仍在 + full 相同):同一 Asset 增加非 primary 位置,不重复分析;
- **E 仅 quick 相同**:只作候选("疑似同一素材,等待完整校验"),新建 Asset 并记入
  `scan_run.reconciliation` 的 ambiguous 明细,**绝不自动合并**(有业务数据的
  Asset 人工合并留后续能力)。

扫描结果统计:new_assets / existing_assets / moved_locations / additional_locations /
missing_locations / content_conflicts / ambiguous_candidates / errors
(+ 脱敏明细,只含 id 与相对路径)。现场移动验证的完整哈希计算受单次扫描字节预算
`SCAN_FULL_HASH_BUDGET_BYTES`(默认 16GiB)限制,超出转 ambiguous。

## 指纹计算任务

- `POST /api/assets/{id}/fingerprint`、`POST /api/assets/fingerprints/batch`、
  `GET /api/assets/fingerprint-jobs/{id}`;
- worker 分块只读计算(scan 队列),**批量任务内部串行**(避免并发顺序读占满 NAS);
- 幂等:full_hash 已存在且文件未变化时 skip;计算期间文件变化 → 结果作废(failed);
- per-asset advisory lock:并发任务不互相覆盖;
- 前端只显示缩短哈希;完整哈希不进列表/日志/Git/PR 描述。

## Shot 分析代次保留

```
每次分析产生新 generation → 新代次成为 current →
旧代次标记 retired_at(不再物理删除)→ FinalVideoUsage 继续引用历史 Shot(审计事实)
```

- 默认业务查询(列表/搜索/匹配/项目/集合/统计)只返回 `retired_at IS NULL`;
- 历史 Shot:详情可打开(标注"历史代次")、`?generation=N` 显式查看、
  lineage 正常展示;retired 镜头**不允许新增**使用引用;
- 旧代次检索文档随代次切换同事务退役(EXCLUDED);
- 旧代次派生文件(关键帧/代理)保留(血缘/历史查看需要);无引用历史的清理
  留后续独立任务;
- 新分析失败时旧 current 继续有效;只有完整成功才 retire(同一事务);
- **PR-B 的重新分析 409 守卫已解除**:有使用血缘的素材可安全重新分析;
- 不自动把旧 Usage 映射到新 Shot(时间码可能不同,映射属人工/后续能力)。

## API 一览

`GET /api/assets/{id}/identity`、`GET /api/assets/{id}/locations`、
`POST /api/assets/{id}/fingerprint`、`POST /api/assets/fingerprints/batch`、
`GET /api/assets/fingerprint-jobs/{id}`、`GET /api/assets/{id}/analysis-generations`、
`GET /api/assets/{id}/shots?generation=current|N`;
AssetOut 附带 `fingerprint_state` / `full_hash_available`。
路径只以「root 显示名 + 相对路径 + 状态」形式返回,绝不返回绝对路径。

## 本阶段明确不做

"已使用"目录/文件名证据导入与 legacy_path_rule(PR-C Gate B)、使用次数修改、
使用感知搜索排序(PR-E)、视觉相似/转码识别/音频指纹/自动反查(PR-H)、
Asset 人工合并、Premiere XML/FCPXML/EDL 解析。
