# 产品视觉识别实验（Visual Recognition Experiment）

> PR-F Gate A。用本地视觉模型把 Shot 关键帧 / 测试图片与**已批准产品**的参考图
> 比较，返回**可解释的产品候选**。这是实验性候选检索，不是生产自动识别：
> **模型候选 ≠ 产品确认；高相似度 ≠ 自动绑定；Top-1 ≠ 识别事实。**

## 1. 冻结边界

- 默认关闭（`VISUAL_RECOGNITION_ENABLED=false`）；开启后所有结果仍只是候选。
- **零自动写入**：绝不修改 AssetProduct、Shot 产品归属、ProductOnboardingReview、
  FinalVideoUsage、CatalogRevision；不把候选存库；不改搜索排序；不碰 Script Match。
- 图片**全程本地处理**：不上传任何第三方 AI API；临时上传图片内存处理、
  请求结束即弃；审计日志只记录计数与耗时（无图片内容、无绝对路径）。
- UI 固定提示（冻结文案）："这是实验性视觉候选，不会自动修改产品归属。
  候选结果必须由人工核对。"

## 2. Provider 架构与模型

```
VisualEmbeddingProvider（协议：embed_images / identity；预处理全在 Provider 内）
├── FakeVisualProvider   确定性假向量（sha256 种子 / FAKE:<token>: 族语义）
│                        仅供单测 / API E2E / Playwright / CI；不得用于真实验收
└── LocalVisualProvider  HTTP → embedder /visual-embeddings（本地推理）
```

- **本地模型**：`google/siglip-base-patch16-224`（**Apache-2.0**，768 维，
  L2 归一化，CPU 可运行，AutoProcessor 批处理）。经 transformers 加载——
  embedder 镜像已有 torch/transformers，仅新增 pillow 解码依赖。
- **惰性单例加载**：只有首个 `/visual-embeddings` 请求触发权重下载/加载
  （落 `EMBEDDER_CACHE_DIR` 模型卷）；文本 e5 与服务启动不受影响；
  CI 用 fake provider，永不触发下载。权重**不进镜像、不进 Git**
  （`clipmind-data/` 已在 .gitignore）。
- 失败语义：解码失败/推理失败显式报错（绝不产生零向量、绝不静默回退 fake
  冒充真实识别）；`/status` 如实返回 provider/model/device/ready 与不可用原因。

## 3. 参考图资格（进入候选库的条件）

产品（Family）：`CatalogStatus=active` + 未 merged/archived + 最新
onboarding 审核 `approved`（缺审核记录 = 不合格）。

参考图：`state=active` 且未归档，且 `quality_status` 不属于
wrong_product / duplicate / blurred / occluded / low_resolution，
且 media_type ∈ jpg/jpeg/png/webp。Variant/SKU 挂图向上归并计入 Family
（标注来源层级）。模型输入用原图（缩略图不作输入）。

约束：primary 加权但不唯一；powered_on/off 为不同视图；package 降权（×0.6）、
detail 降权（×0.8）且**不能单独代表产品**；合格图 < `VISUAL_MIN_REFERENCES`
（默认 2）→ `insufficient_reference`。绝不从产品名称生成伪造视觉特征；
不使用旧 `product_image` 表。

**识别层级**：Gate A 以 **Family** 为主；Variant/SKU 仅在自身有足量合格图时
作 experimental 展示，绝不因 Family 命中自动推断。

## 4. 候选聚合与 Open-set

- 相似度：cosine（向量已 L2 归一化）；聚合策略 `max` / `top_k_mean`(k=3，默认)
  / `weighted_top_k_mean`（primary ×1.2、package ×0.6、detail ×0.8——只按
  维度配置，绝不按真实产品名称硬编码）。
- 判定状态机：`model_unavailable` → `insufficient_reference` →
  `unknown`（top1 < `VISUAL_MIN_SCORE`）→ `ambiguous`（margin <
  有效 margin）→ `candidate`。排序确定：score ↓ → family_id ↑。
- **Confusion Pair 加强**：top1/top2 命中 `ProductConfusionPair` 时用更严的
  `VISUAL_CONFUSION_MARGIN`，返回人工维护的 distinguishing_features，
  默认不判 confident candidate；UI 醒目提示核对区分特征。
- **阈值全部实验性**（`thresholds.calibrated=false`）：初始值未经真实
  Benchmark 校准；须由验证集 coverage-accuracy 曲线选取后才可谈校准；
  数据不足时不得声称已校准，绝不输出伪造准确率。

## 5. API（前缀 /api/product-visual-experiments）

`GET /status`（开关/provider/model/device/ready/合格产品与参考图计数/阈值）、
`GET /models`（双 provider 及许可证）、`GET /reference-coverage`（按 Family 的
资格与角度覆盖）、`POST /candidates/shot/{shot_id}`（当前与历史代次均可，
响应标记 generation/is_historical）、`POST /candidates/image`（临时上传：
MIME/扩展名/大小上限校验，内存即弃）、`POST /benchmark`（同步小样本）。

响应含 decision / candidates(score/best_reference/matched_angles/
reference_count/aggregation) / top1·top2·margin / thresholds / model /
provider / confusion_warning。未开启时一律 403。

## 6. Benchmark（离线评测）

样本：参考图留一法（按 sha256 内容身份剔除，防同文件自匹配）/ Shot 关键帧 /
unknown 负样本。Ground Truth 人工提供（目录名绝不自动当 GT）。
指标：Top-1/Top-3/MRR/Macro Recall/每产品 Recall/Confusion Matrix/
Unknown Rejection P·R/Ambiguous Rate/Coverage/Accepted-candidate Accuracy
+ 按来源/参考图桶分组 + coverage-accuracy·score·margin 曲线；样本不足时
输出 data_gaps，绝不只报一个 Top-1，绝不声称统计显著或生产可用。
工件写 `.local/pr-f-a/benchmark/`（不提交真实图片/文件名/embedding）。

## 7. 配置（.env）

见 `.env.example` "PR-F 产品视觉识别" 段：ENABLED / PROVIDER / MODEL_ID /
DEVICE / BATCH_SIZE / TOP_K / MIN_SCORE / MIN_MARGIN / CONFUSION_MARGIN /
MIN_REFERENCES / EMBEDDER_URL。CI 一律 fake；本地真实验收显式 local + 启用
embedder profile。NAS 部署不要求 GPU（CPU 推理），默认不启用视觉能力。

## 8. 性能与资源

模型单例惰性加载（不逐请求加载）；参考图批量嵌入（`VISUAL_BATCH_SIZE`）+
进程内特征缓存（键含 sha256/model——内容或模型变化自然失效）；候选查询
同步小规模（本阶段参考图数量级）；OOM/推理错误安全失败（500 + 原因）。
本阶段不新增 visual-worker（审计结论：规模不需要）；不把 torch 装进
api/worker 镜像。

## 9. 验证与后续

后端 `apps/api/tests/test_visual_experiments.py`（9 用例）；中性 E2E
`scripts/ci_pr_f_visual_e2e.py`（10 标志）；UI `e2e/pr-f-visual-experiments.spec.ts`。
真实验收只做管道层（本地推理/资格过滤/只读），质量层按真实 Ground Truth
样本量如实报告。后续：Gate B 持久视觉索引 + 人工候选审核工作流；PR-G 多路
召回融合；PR-H 成片反向引用；PR-I 全脚本分镜匹配。
