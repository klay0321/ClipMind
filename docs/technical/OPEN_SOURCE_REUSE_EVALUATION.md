# 开源技术复用评估（OPEN_SOURCE_REUSE_EVALUATION）

> 阶段：Phase 0 Discovery（调研评估，**不集成代码、不下载权重、不复制未知许可证代码**）。
> 本文件对 ClipMind 在「跨境电商产品带货视频素材管理与智能匹配」场景下，**可复用 / 可补强**的开源技术做横向评估，
> 给出三档结论（现在应验证 / 后续可验证 / 暂不采用）与 Provider 接入边界。
>
> 上游事实来源：
> - 业务语境：`../requirements/ECOMMERCE_MEDIA_ASSET_REQUIREMENTS.md`（§0–§7）
> - 产品身份与使用血缘：`../requirements/PRODUCT_IDENTITY_AND_USAGE_LINEAGE_SPEC.md`（§1–§7）
> - 公司基准（评测）：`../evaluation/COMPANY_MEDIA_BENCHMARK_PLAN.md`（本文引用其基准名）
> - 路线图（权威 PR 编号 PR-A..PR-I）：`../roadmap/ECOMMERCE_ASSET_INTELLIGENCE_ROADMAP.md`
>
> 本文与上述文档在术语 / 对象模型 / 状态机 / 证据等级上**完全一致**：
> Product Family / Product Variant / SKU / Alias / Reference Image / **Confusable Group**；
> Source Asset / Shot / **Final Video（新增）** / **Final Video Usage（新增）**；
> Storyboard·Segment / Project / Human Review（ShotReviewState + ReviewEvent + ReviewStatus）；
> 6 级使用证据（`confirmed_editor_project` / `confirmed_manual` / `confirmed_clipmap_export` 计入正式 `usage_count`；
> `suspected_visual_match` / `suspected_audio_match` / `legacy_path_rule` 不计入）；8 种使用状态。

---

## 0. 评估原则（先于结论）

为避免「只因 Star 多就推荐」，本评估对每项技术固定从以下维度审查，并把结论分层标注
（**事实** / **规则推断** / **AI 推断** / **人工确认**）：

| 维度 | 说明 |
|---|---|
| 官方仓库 / License | 代码许可证（是否商用可闭源 NAS 部署、是否 copyleft 传染） |
| 权重 License | 模型权重许可证（跨境电商为**商用**场景，须排除 NC / 数据集 NC 传染） |
| 维护状态 | 活跃 / 稳定 / 低频；是否官方仍迭代 |
| 输入 / 输出 | I/O 形态，及到 ClipMind 对象（Shot / ShotTag / AssetProduct / ShotSearchDocument / Final Video Usage）的映射 |
| CPU / GPU | 是否有官方 CPU 路径（公司 NAS 默认**纯 CPU x86_64**） |
| 内存 | 权重 + 推理峰值的量级（不臆造精确数字） |
| x86_64 NAS 可行性 | 在无 GPU 的 NAS 上线的可行度 |
| Windows 开发可行性 | 本机（Windows）联调 / 离线评测可行度 |
| 速度预估 | 实时 / 准实时 / 仅离线批处理 |
| 项目价值 | 对应哪条公司痛点（`ECOMMERCE_…REQUIREMENTS §1`） |
| Provider 接入 | 能否纳入现有可替换 / 可降级 Provider 抽象（含 `AIProvider.rerank_candidates` 空槽） |
| 失败回退 | 不可用时如何降级而**不破坏检索可用性** |
| 推荐优先级 | P0（已采用基座）/ P1 / P2 / 暂不 |
| 验证基准 | 用哪套公司基准验收 |

**贯穿硬约束（继承项目 §2、需求 §6、规格 §7）：**

1. 绝不做任何**生成式视频**能力；「关键帧 / 缩略图 / 代理 / 可剪辑片段」一律指 **FFmpeg 从源视频派生**。
2. 源素材**只读**；本阶段**不建 Alembic 迁移、不改模型、不改搜索排序、不接新模型、不下载权重**。
3. **证据分层**：自动结论标【事实 / 规则推断 / AI 推断 / 人工确认】；UI 不伪造「已识别 / 已匹配 / 使用次数」。
4. **嵌入正交可降级**：`ShotSearchDocument` 的 `document_status` 与 `embedding_status` **正交**——
   任一嵌入（文本 / 视觉 / 视频）不可用时仍 `is_searchable`，继续走词法（pg_trgm）/ 标签 / 产品 / 结构化召回，
   **绝不因嵌入缺失而无法搜索**。
5. **Confusable Group（软屏 vs 硬屏）默认不自动判定**：任何视觉 / 视频模型对易混变体只产候选，强制人工确认，绝不自动断言变体。
6. **权重不冻结**：本文只列「可配置因素 + 默认倾向」，不在规格中固定向量维度、阈值、融合权重。

**公司基准（验证集，名称与评测计划一致，集合本身待建）：**

- **素材搜索集**：自然语言 / 产品 / 动作 / 场景 查询 → 镜头召回与排序质量。
- **产品识别集**：关键帧 → 4 产品（含软 / 硬屏 confusable）识别召回 / 精度与人工确认率。
- **分镜匹配集**：Segment → Shot 候选质量（结构化分镜全局分配）。
- **成片引用识别集**：成片 ↔ 源镜头反查（视觉 / 音频疑似引用），验证 `suspected_*` 召回与退化。

> 本阶段素材库只读审计聚合事实（来自 `audit_summary.json`，不含任何文件名）：
> 文件 190 / 视频 102 / 产品参考图 81 / 系统垃圾 7 / ≈4.66 GB / 顶层目录 8（7 拍摄目录 + 1 参考图目录）/
> 产品候选 6（family×variant）/ 疑似源视频 94 / 疑似成片 **0** / 「已使用」证据 8 / 能确定使用次数 **0** / 能确定对应成片 **0** /
> 字节级重复组 **0**（印证「已使用」靠**移动**而非复制）/ 疑似低码率代理 14。
> 推论：成片引用识别集**当前为空**，需公司先提供真实成片样本才能验收成片反查类技术。

---

## 1. 总览表

> 「现有承载」列标注与 ClipMind 现状的关系：**基线**＝已落地在用；**复用**＝纳入现有抽象即可；**新增能力位**＝需在现有 Provider 抽象下新建一类能力。
> License / 权重 License 中 NC＝NonCommercial（商用须排除）。优先级 P0＝已采用基座，P1＝建议优先验证，P2＝后续，暂不＝当前阶段不采用。

| # | 技术 | 组 | 代码 License | 权重 License | 维护 | CPU 路径 | NAS(x86,无GPU) | I/O 摘要 | 对应能力位 | Provider 接入 | 优先级 | 结论档 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 1 | **MiMo Provider** | embed/rerank（实为理解） | 闭源商业 API（适配器随本仓库许可） | 不适用（不下发权重） | 供应商维护，在用 | 云端（本地仅 httpx） | 可行（仅 HTTP 客户端） | 图+文 → 结构化 JSON（镜头分析 / query 解析 / script 解析）；**无 embeddings / 无 rerank** | 理解基线（视觉打标 / 解析） | 已是 `AIProvider`（rerank 未实现，按 capabilities 降级） | **P0 基线** | 现在应验证 |
| 2 | **E5 本地 embedder**（intfloat/multilingual-e5-small） | embed/rerank | MIT | MIT | 稳定，revision 钉死，在用 | CPU 即可 | 已验证可行 | 文本 → 384 维 dense | 文本 dense 召回基线 | `EmbeddingProvider`（非 rerank 路径） | **P0 基线** | 现在应验证 |
| 3 | **pgvector** | infra | PostgreSQL License | 不适用 | 活跃，在用 | 纯 CPU | 已采用 | 向量存 / 索引 / 距离（HNSW） | 检索基座（存+查） | 检索基础设施（非 Provider） | **P0 基线** | 现在应验证 |
| 4 | **PySceneDetect** | infra | BSD-3-Clause | 不适用（传统算法，无权重） | 活跃（v0.7），在用 | 纯 CPU | 高度可行 | 视频 → 场景边界（帧号 / 时间码） | 拆镜头基线（→ Shot） | 已是可替换 `ShotDetector` | **P0 基线** | 现在应验证 |
| 5 | **BGE Reranker v2-m3** | embed/rerank | MIT | Apache-2.0 | 活跃（FlagEmbedding v1.4.0） | CPU 可跑（偏慢） | 条件可行（仅 Top-K 精排） | (query, passage) → 相关性分 | **填 `rerank_candidates` 空槽** | 本地 Reranker Provider | **P1（本组最具增量）** | 后续可验证 |
| 6 | **OpenCLIP** | visual | MIT | 因 checkpoint 而异（须选商用：laion2b/datacomp；部分 CC-BY-NC 须排除） | 活跃 | CPU 可（ViT-B 量级） | 可行（ViT-B/16 或 B/32） | 图 + 文 → 图文嵌入 | **新增视觉嵌入位**（图文检索） | 本地视觉 embedding provider | **P1（视觉检索首选）** | 现在应验证 |
| 7 | **SigLIP2** | visual | Apache-2.0（经 HF Transformers） | Apache-2.0（base 已核） | 活跃（Google 2025-02） | CPU 可（base/so400m） | 可行（base / so400m） | 图 + 文（多语言）→ 图文嵌入 | 同视觉嵌入位（与 OpenCLIP 互换 A/B） | 同上抽象，可互换 | **P1（与 OpenCLIP 并列，许可更干净）** | 现在应验证 |
| 8 | **Grounding DINO** | detect/segment | Apache-2.0 | Apache-2.0（swint_ogc） | 中等 / 低频（1.0 版稳定） | 官方支持 CPU-only | 可行但慢（仅离线批） | (image, text prompt) → 带标签 bbox | **新增开放词表检测位**（产品候选） | 本地检测 Provider（→ ShotTag[product] / AssetProduct 候选） | **P1（产品识别最直接）** | 现在应验证 |
| 9 | **BGE-M3** | embed/rerank | MIT | MIT | 活跃 | CPU 可（ONNX/量化） | 可行但需评估（1024 维＝重嵌） | 文本 → 1024 维 dense（+sparse / multi-vec） | dense 召回升级候选 | `EmbeddingProvider` 同位替换 | P2（A/B 后再决） | 后续可验证 |
| 10 | **DINOv2** | visual | Apache-2.0 | 标准 backbone Apache-2.0（衍生 NC 须排除） | 活跃 | CPU 可（ViT-S/B） | 可行（用途受限） | 仅图像 → 纯视觉特征（无文本塔） | 视觉去重 / 同源去重 / 视觉反查候选 | 辅助视觉特征 Provider（非检索主路） | P2（去重专用） | 后续可验证 |
| 11 | **Chromaprint**（fpcalc） | infra | 整体按 LGPL-2.1（核心 MIT；**FFT 后端选择影响传染：FFTW3→GPL，须用非 GPL 后端**） | 不适用（确定性指纹，无权重） | 稳定 / 慢 | 纯 CPU | 可行（须固定非 GPL 二进制） | 音轨 → 音频指纹 | 成片音频反查（`suspected_audio_match`） | 成片反查 Provider 之一 | P2（后置） | 后续可验证 |
| 12 | **InternVideo2** | video | Apache-2.0（代码） | **不一致 + 数据集 NC（CC-BY-NC-SA）须法务确认** | 活跃 | 无官方 CPU 路径 | 低可行（强依赖 CUDA / Flash-Attn / DeepSpeed） | 视频片段 + 文 → 视频文本嵌入 | 视频原生嵌入位（条件性） | 须自建推理服务封 Provider | P2（条件性，双门槛） | 后续可验证 |
| 13 | **SAM 2** | detect/segment | Apache-2.0 | Apache-2.0 | 稳定（曾活跃） | 无官方 CPU 支持 | 可行性低（GPU 依赖） | 图/帧 + 提示 → 分割掩码 / 跟踪 | 区域抠图 / 产品跟踪增强 | 理论可，价值/成本不匹配 | **暂不采用** | 暂不采用 |

---

## 2. 分组详评

### 2.1 embed / rerank 组（语义召回与精排）

#### 1）MiMo Provider —— **P0 理解基线（不在本组改动）**【事实】

- **定位**：小米 MiMo 闭源外部 API（OpenAI 兼容 `/chat/completions`），ClipMind 内适配器
  `packages/shared/clipmind_shared/ai/providers/mimo.py`，PR-03A 已落地并经 `scripts/probe_ai_provider.py` 能力探测。
- **I/O**：系统提示词 + 多关键帧（Base64 内联图）/ 文本 → 结构化 JSON（镜头分析、search query 解析、script 解析）。
  **无 embeddings、无 rerank 端点**（mimo-v2.5 视觉、mimo-v2.5-pro 纯文本）。
- **到对象**：产出 `ShotTag`（product/scene/action/shot_type/marketing/quality/risk，source=ai）与 `AssetProduct` 候选，
  全部标【AI 推断】进入人工审核队列。
- **Provider 接入**：**已是** `AIProvider`；`rerank_candidates` 协议方法存在但 MiMo **未实现**，调用层据 `ProviderCapabilities` **降级**，绝不伪造。
- **失败回退**：供应商不可用 → 编排层据 capabilities 降级到规则 / 词法召回 + 人工确认。
- **价值**：视觉打标 / query 解析 / script 解析三类结构化理解的事实基线，是产品识别与标签来源；但**不提供向量与重排**，故 embed/rerank 仍需本地方案补位。
- **结论**：**现在应验证**（保持现状基线，本组不改动）。**验证基准**：产品识别集（视觉打标质量）；间接素材搜索集（标签 / 产品召回质量）。

#### 2）E5 本地 embedder（intfloat/multilingual-e5-small）—— **P0 文本 dense 基线**【事实】

- **定位**：PR-04 Hybrid Search 的 dense 召回支柱；微服务 `services/embedder/`，revision 钉死（`test_revision_consistency` 强制一致）。
  换模型 / 改维度须**全量重嵌**。
- **License / 权重**：MIT / MIT（可商用、可本地缓存）。
- **I/O**：文本（调用端加 `query:` / `passage:` E5 前缀并归一化）→ **384 维** dense；CPU 即可，毫秒级 / 条，批量高吞吐。
- **Provider 接入**：已作为独立 embedder 微服务接入（`embedding_factory` + `EmbeddingProvider` 抽象，已有 fake/openai 实现），**非** `AIProvider.rerank` 路径。
- **失败回退**：嵌入服务不可用 → Hybrid Search 退化到词法 / pg_trgm + 标签 + 产品 + 结构化召回，仍 `is_searchable`（架构已保证）。
- **结论**：**现在应验证**（保持基线，是否升级更强 dense 模型属后续可选，不在本组冻结）。**验证基准**：素材搜索集；分镜匹配集（segment→shot 语义候选）。

#### 5）BGE Reranker v2-m3 —— **P1：本组最具增量价值（填 `rerank_candidates` 空槽）**

- **License / 权重**：MIT（FlagEmbedding 代码）/ Apache-2.0（`BAAI/bge-reranker-v2-m3` 权重，可商用、可本地缓存）。【事实】
- **维护**：活跃，随 FlagEmbedding v1.4.0（2026-04-22）。【事实】
- **I/O**：(query, passage) 文本对 → 单个相关性分（可 sigmoid 映射 [0,1]）；base＝bge-m3，约 0.6B（568M）参数，max 512 token。交叉编码每对一次前向，**候选数线性增长**。
- **CPU / NAS**：CPU 可跑但偏慢；**仅对 Hybrid Search Top-K（如前 50~100）做精排**，控制 K 后 x86 CPU 可接受；全量重排不可行。CPU 上每对约数十 ms，重排 Top-50 约秒级。【事实 + 规则推断】
- **项目价值**：正好填补现有 `AIProvider.rerank_candidates` **空槽**——召回后对 Top-K 语义精排，直接命中跨境电商「产品 / 动作 / 场景不准」痛点（需求 §1.6）。
  与现有多因子 `final_score`（semantic / lexical / tag / product / quality / review_bonus / risk_penalty）**融合而非取代**；**须与使用感知降权 / 同源去重在精排之后或并行**。**融合权重不在本规格冻结**。
- **Provider 接入**：**高**——实现为本地 Reranker Provider 填充 `rerank_candidates`；调用层据 `ProviderCapabilities` 决定是否启用，缺失时回退现有 `final_score` 排序，**绝不伪造匹配度**。
- **失败回退**：reranker 不可用 / 超时 → 直接用既有多因子排序，检索功能不退化。
- **结论**：**后续可验证**（本组最值得做的增量；先离线在公司基准验证增益再决定是否在线启用，K 必须受控）。**验证基准**：素材搜索集（重排前后 Top-K 排序增益）；分镜匹配集（segment→shot 精排）；间接产品识别集（产品硬过滤后的同产品精排）。

#### 9）BGE-M3 —— **P2：dense 召回升级候选**

- **License / 权重**：MIT / MIT（`BAAI/bge-m3`，可商用、可本地缓存）。【事实】活跃（FlagEmbedding v1.4.0）。
- **I/O**：文本（到 8192 token）→ **1024 维** dense（+ 可选 sparse 词级权重 + multi-vector ColBERT 风格）；base＝XLM-RoBERTa，100+ 语言，约 0.56B 参数。
- **CPU / NAS**：CPU 可跑（ONNX O2 / FastEmbed INT8 量化路径），比 E5-small 重约 10x；量化后单条几十~上百 ms。**dense 单向量可灌入现有 pgvector，但须 384→1024 维迁移＝重嵌，本阶段只记录不实施**；sparse / multi-vector 需额外存储与检索改造，成本更高。
- **价值**：跨境电商**中英混合产品词 / 品类词**多语言召回潜在优于 E5-small；sparse 模式天然兼容词法召回理念。
- **Provider 接入**：作为 `EmbeddingProvider` 新实现与 E5 **同位替换** dense 通道，无须改 `AIProvider` 协议；多向量 / 稀疏检索若启用属更大改造。
- **失败回退**：推理失败 / 资源不足 → 回退 E5-small dense 或非向量召回；维度迁移未完成前**不切换主嵌入**。
- **结论**：**后续可验证**（先离线 A/B 对比再决定；不在本阶段冻结权重或迁移维度）。**验证基准**：素材搜索集（与 E5-small dense A/B）；分镜匹配集。

---

### 2.2 visual 组（视觉 / 图文嵌入，补 PR-04 视觉召回维度）

> 现状 PR-04 只有文本 E5（384 维，且文本派生于 AI 标签）。视觉组补「自然语言搜图 / 搜镜头」与「产品参考图 → 镜头」视觉召回。
> **新增视觉嵌入位**：落地时作为 `ShotSearchDocument` 的**独立视觉向量列 / 独立向量空间**（pgvector，落地 PR 评审），与现有 `embedding_status` 正交——视觉嵌入缺失不阻断非向量召回。
> 产品参考图 → 镜头的视觉相似只产 `needs_human` 候选；**confusable（软 / 硬屏）绝不自动断言变体**。

#### 6）OpenCLIP —— **P1：视觉检索首选基线**

- **License**：代码 MIT。【事实】**权重 License 因 checkpoint 而异，须逐个核对**：LAION/DataComp 多数为宽松开源（Apache-2.0/MIT/CC-BY），**部分预训练权重为 CC-BY-NC（仅非商用）**；跨境电商为商用，**必须只选商用可用 checkpoint（如 laion2b/datacomp 系列），不得臆断全部可商用**。【事实 + 规则推断】
- **维护**：活跃（已跟进 SigLIP2 / timm 权重）。【事实】
- **I/O**：图像 + 文本（分别编码）→ 图 / 文嵌入（依模型 512/768/1024 维），支持零样本分类 / 图文检索 / 相似度。与 E5（384 维文本）**不同模态，独立视觉向量空间**。【事实】
- **CPU / NAS / 速度**：CPU 可推理（慢），ViT-B/32 CPU 单图约 50–200ms；NAS 无 GPU 选 **ViT-B/16 或 B/32**，内存压力可控（ViT-B 约 0.5–1GB）。批量派生关键帧嵌入建议**离线批处理**。【规则推断】
- **价值**：图文双塔直接支撑「自然语言搜镜头」与「产品参考图 → 镜头视觉检索」，补齐 Hybrid Search 视觉召回维度；可辅助产品归属候选（仍需人工确认，confusable 不自动断言）。【规则推断】
- **Provider / 回退**：封装为本地视觉 embedding provider，与 MiMo 并列；失败回退文本 E5 + pg_trgm + 标签 + 产品硬过滤召回，**绝不因视觉嵌入缺失而无法搜索**。
- **结论**：**现在应验证**（成熟稳定、生态最广、CPU 可跑、商用权重可选）。**验证基准**：素材搜索集（自然语言 / 参考图 → 镜头 Recall@K、产品相关性）为主；产品识别集（参考图 → 镜头视觉相似辅助候选，仅 `needs_human`）为辅。

#### 7）SigLIP2 —— **P1：与 OpenCLIP 并列首选，许可证更干净**

- **License / 权重**：经 HF Transformers（Apache-2.0）集成；权重 **Apache-2.0**（`google/siglip2-base-patch16-224` 已核 license=apache-2.0），可商用，**优于 OpenCLIP 部分 NC 权重的合规风险**。【事实】
- **维护**：活跃（Google 2025-02 发布，已并入 HF Transformers / timm / OpenCLIP）。【事实】
- **I/O**：图像 + 文本（多语言，WebLI 训练）→ 图文嵌入（base 768 维 / so400m 1152 维）；各尺度均优于 SigLIP-1。【事实】
- **CPU / NAS / 速度**：base(86M)/large(303M)/so400m(400M)/giant(1B) 四档；base/so400m 适配无 GPU NAS（base 约 0.5–1GB，CPU 约 50–200ms/图；so400m CPU 约 0.2–0.8s/图）；**giant 不建议无 GPU NAS**。【事实 + 规则推断】
- **价值**：检索精度全面超 SigLIP-1，**多语言契合跨境电商多市场文案**，sigmoid 损失对图文检索更稳。【事实 + 规则推断】
- **Provider / 回退**：与 OpenCLIP 在**同一视觉 embedding provider 抽象下可互换**（同为图文双塔），便于 A/B 后择优；失败回退同 OpenCLIP（降级文本 E5，或回退 OpenCLIP 作视觉基线）。
- **结论**：**现在应验证**（建议与 OpenCLIP **同期 A/B**，许可更干净、精度与多语言更优）。**验证基准**：素材搜索集（图文检索 Recall@K、多语言查询相关性，与 OpenCLIP 同基准直接对比）为主；产品识别集为辅。

#### 10）DINOv2 —— **P2：视觉去重 / 同源去重 / 成片视觉反查候选专用**

- **License / 权重**：代码 Apache-2.0；**标准自监督 backbone（ViT-S/B/L/g）权重 Apache-2.0 可商用**，但**专用衍生权重（XRay-DINO/Cell-DINO）为 FAIR Noncommercial 须避开，只用标准 backbone**。后继 DINOv3 为自定义授权，需单独评估，本调研只覆盖 DINOv2。【事实】
- **I/O**：**仅图像（无原生文本编码器）**→ 纯视觉特征（patch + CLS，384/768/1024/1536 维）。**无法直接做自然语言 → 镜头检索**。【事实】
- **CPU / NAS**：ViT-S/B CPU 可跑（约 50–300ms/图），但用途受限于纯视觉相似度。【规则推断】
- **价值**：定位为「以图搜图 / 视觉去重 / **同源去重** / 参考图 → 镜头视觉相似 / 近重复检测」，可辅助高频素材**同源去重**（需求 §1.7）与成片视觉反查（`suspected_visual_match` 候选，须人工确认）。对核心自然语言检索价值低于 OpenCLIP/SigLIP2。【规则推断】
- **Provider / 回退**：作为辅助视觉特征 Provider（纯视觉相似 / 去重 / 反查管线），**不替代图文检索主路**；回退到 pHash / 字节哈希（现有 `quick_hash`/`full_hash` 预留）做近重复，或回退 OpenCLIP/SigLIP2 视觉嵌入。
- **结论**：**后续可验证**（不作首选语义检索引擎；后续去重 / 同源去重 / 成片视觉反查专用模块）。**验证基准**：成片引用识别集（`suspected_visual_match` 反查候选准确率，须人工确认计入 usage）+ 素材搜索集中「以图搜图 / 同源去重」子任务。

---

### 2.3 detect / segment 组（产品检测与分割）

#### 8）Grounding DINO —— **P1：对产品识别最直接可用，优先级高于 SAM 2**

- **License / 权重**：均 **Apache-2.0**（`groundingdino_swint_ogc.pth` 在 HF 标注 apache-2.0，可商用，与代码一致）。【事实】
- **维护**：**中等 / 低频**（ECCV 2024 官方实现，主力 checkpoint 约 2023-04；IDEA-Research 后续重心转向闭源 1.5 / DINO-X API）。开源 1.0 仍可用、社区集成多，**但不要指望频繁更新**。【事实】
- **I/O**：(image, text prompt)，prompt 可为类别词 / 短语（如 `keyboard . gear shift knob . screen`）→ 默认 900 候选框，每框带与各输入词相似度分，阈值后得带短语标签 **bounding boxes**。属**开放词表目标检测**。【事实】
- **CPU / NAS / 速度**：**官方支持 CPU-only**；GPU 可选加速。x86 NAS 可装可跑**但很慢**——CPU 单图数秒~十数秒级，**仅离线批处理**，不适合在线实时（与现有 CPU 化路线兼容）。GPU 约 100ms/图。Swin-T 权重约 0.7–0.8GB，CPU 推理建议预留 4–8GB。【事实 + 规则推断】
- **价值**：**高**——可用产品名 / 品类词作 prompt（恶魔之眼软屏 / 硬屏、车换挡握把 / 十字架档把、小键盘 / mini键盘、汽配 / 数码 / 键盘 / 握把），在关键帧上**定位产品并产 bbox**，为「产品归属 / 产品识别」与镜头级产品候选提供 **AI 推断**证据；bbox 还可裁剪产品区域辅助参考图比对。**软 vs 硬屏属 confusable group，本工具只给候选，必须人工确认，绝不自动断言变体。**
- **Provider 接入**：契合现有 AI Provider 接口（与 MiMo 视觉 provider 同层，作「product detection / open-vocab detection」可替换 Provider）。输出 bbox + 标签 + confidence，**天然映射** `ShotTag[type=product, source=ai, confidence/match_type]` 与 `AssetProduct` 候选；遵循证据分层标【AI 推断】，进人工审核队列。
- **失败回退**：回退到现有【规则推断】文件名 / 目录规则命中产品候选（`needs_human=true`）+ 名称匹配；嵌入 / 检索侧不受影响（正交）。检测不可用时 UI 标「未识别 / 待确认」，**绝不伪造产品识别**。
- **结论**：**现在应验证**（本组对 ClipMind 产品识别最直接可用，优先级高于 SAM 2）。**验证基准**：产品识别集（主，真实关键帧上验证 4 产品含软 / 硬屏的检测召回 / 精度与人工确认率）；次要素材搜索集（检测产出产品标签对「产品 / 动作不准」检索的改善）。

#### 13）SAM 2 —— **暂不采用（GPU 依赖与 CPU NAS 路线冲突）**

- **License / 权重**：均 Apache-2.0（可商用；可选 cc_torch 为 BSD-3-Clause；demo 字体不影响后端推理）。【事实】
- **维护**：稳定（2024-07 首发，SAM 2.1 于 2024-09，此后趋缓）。【事实】
- **I/O**：图 / 视频帧 + 提示（点 / 框 / 掩码）→ 分割掩码，可跨帧传播跟踪。**本质是 promptable 分割 / 跟踪，不做分类 / 识别**（不会告诉你「这是哪款产品」）。【事实】
- **硬件 / NAS**：**强烈推荐 GPU**（torch≥2.5.1，README 未正式支持 CPU-only，CUDA 算子）；无 GPU x86 NAS 上 **CPU 推理不实用**，批量分割性价比差。即便 GPU 每帧上百 ms。【事实 + 规则推断】
- **价值**：**中等 / 辅助**——核心痛点是产品归属 / 识别 / 检索 / 分镜匹配，SAM 2 只产掩码不做产品识别。潜在价值在配合检测器抠产品区域做更干净参考图比对、或镜头内跟踪产品出现时长 / 占比（结构化标签增强）。属锦上添花，且 **GPU 依赖与本项目 CPU NAS 路线冲突**。
- **Provider**：理论可封「分割 / 跟踪 Provider」输出掩码 + 区域统计 → `ShotTag[scene/shot_type]`，但**不产生产品身份，需与检测器级联（Grounded-SAM 范式）才有意义**，引入复杂度高、GPU 成本大，当前阶段不建议接入。
- **失败回退**：无 SAM 2 时产品识别 / 检索**完全不受影响**（其能力本就是可选增强）；区域裁剪可退化为**按检测 bbox 直接 FFmpeg 裁剪**（符合「派生而非生成」约束），无需分割掩码。
- **结论**：**暂不采用**（当前阶段不优先；待 Grounding DINO 等产品识别先落地、且确有 GPU 资源与「区域抠图 / 产品跟踪」明确需求时再评估）。**验证基准**：当前阶段无需纳入任一公司基准。

---

### 2.4 video 组（视频原生嵌入）

#### 12）InternVideo2 —— **P2：条件性（双门槛：GPU 可用 + 权重商用合规）**

- **License / 权重**：代码 **Apache-2.0**（已核 LICENSE）。**权重存在【许可证不一致 + 非商用风险】须人工法务确认**：模型卡自相矛盾（1B 卡标 apache-2.0、6B 卡标 MIT），但**训练数据集 `OpenGVLab/InternVideo2_Vid_Text` 明确为 CC-BY-NC-SA-4.0（NonCommercial + ShareAlike）**。对**跨境电商商用部署**，权重源数据带 NC 限制构成**实质合规风险**，不能仅凭模型卡 apache/MIT 字样视为可商用。【规则推断 / 需人工确认】
- **维护**：活跃（ECCV2024；2025-02-25 发布 Stage2-6B，延伸 InternVideo2.5 / VideoChat-Flash）。【事实】
- **I/O**：视频片段（稀疏采样典型 4/8 帧，224p ViT）+ 文本 → 视频 / 文本对齐嵌入（CLIP 式），可做 video-text 检索 / 嵌入抽取，及动作识别 / 时序定位 / 视频字幕。对 ClipMind 最相关＝**视频片段嵌入 + 视频-文本检索**。【事实】
- **硬件 / NAS**：官方安装路径**强依赖 GPU**（multi_modality 要求 Flash Attention + DeepSpeed + CUDA；6B 还需 InternVL-6B 视觉编码器权重）；蒸馏 S/B/L 体量小但官方无 CPU-only 文档。**纯 CPU x86 NAS 低可行**——无官方 CPU 路径，强行 CPU 跑蒸馏小模型视频帧批推理很慢且推理码为研究级（issue #185 反映初始化较脆弱）。**除非 NAS 配独立 GPU 或外置 GPU 推理服务，否则不建议上线。**【事实 + 规则推断】
- **Windows 开发**：原生**困难**（Flash-Attn / DeepSpeed / CUDA 扩展 Windows 编译受限，官方仅面向 Linux+CUDA）；建议 WSL2+Linux+NVIDIA GPU 或 Linux 容器评测，Windows 本机仅适合读码 / 写规格。【规则推断】
- **价值**：「视频片段 → 嵌入」与「视频-文本检索」恰对应镜头语义检索与画面匹配，可作**视频原生**嵌入补强当前 E5（文本派生于 AI 标签，对纯视觉差异如软 / 硬屏区分力有限）。但 **confusable（软 / 硬屏）仍须人工确认，不能靠它自动断言变体**。价值兑现取决于 GPU 可用性与权重商用合规。【规则推断】
- **Provider 接入**：**需新建「视频嵌入 Provider」能力位**。维度与 E5 的 384 维不同，须作**独立向量空间 / 独立列**接入，与 `embedding_status` 正交（嵌入缺失仍走词法 / 标签 / 产品召回）。落地需**自建推理服务**封装为 Provider，而非现成 API。【规则推断】
- **失败回退**：① 回退 E5 文本嵌入 + Hybrid Search；② 视觉识别失败回退文件名 / 目录规则 + 人工确认；③ 嵌入抽取不可用时 `ShotSearchDocument` 仍 `is_searchable` 走非向量召回。**绝不因 InternVideo2 缺失而使搜索不可用。**
- **结论**：**后续可验证**（中，条件性）。仅当「视频原生嵌入显著优于现有文本派生嵌入」被基准证明、**且 GPU 与权重商用合规两道门槛都通过**时才提级；否则维持观望，短期不作主路径替换 E5。**验证基准**：素材搜索集（对比 E5+Hybrid 基线）；产品识别集（软 / 硬屏 confusable 可分性，作视觉佐证而非自动判定）；分镜匹配集。成片引用识别集不适用。

---

### 2.5 infra 组（检索 / 拆镜头 / 反查基础设施）

#### 3）pgvector —— **P0：检索基座（已采用）**【事实】

- **License**：PostgreSQL License（类 BSD/MIT，可商用闭源 NAS，无 copyleft 传染）。权重不适用（只存 / 查向量，不产嵌入）。
- **维护**：活跃（README 引用 v0.8.3）。
- **I/O**：定长 / 稀疏向量列（vector/halfvec/bit/sparsevec）+ 查询向量 → 按距离排序近邻；支持 L2/内积/cosine/L1/Hamming/Jaccard；vector/halfvec 最大 16000 维（项目用 **384 维**）；HNSW 与 IVFFlat。纯 CPU，亚毫秒~毫秒级（当前数据量级），索引构建为离线一次性成本。
- **价值 / 设计锁定**：支撑 PR-04 Hybrid Search 语义向量召回，缓解「搜索产品 / 动作 / 场景不准」。**`document_status` 与 `embedding_status` 正交**——嵌入不可用仍 `is_searchable`，继续词法 / pg_trgm / 标签 / 产品召回，绝不因嵌入缺失无法搜索；pgvector 故障可降级不影响可用性。项目硬约束即要求 PostgreSQL + pgvector（**禁用 SQLite**）。
- **Provider**：本身**非 AI Provider**，是检索基础设施（存 + 索引 + 距离）；与 Provider 解耦——E5（本地）/ MiMo（外部）产向量，pgvector 存查。
  > 说明：若后续启用视觉 / 视频嵌入（OpenCLIP/SigLIP2/InternVideo2，维度 ≠ 384），将作为**独立向量列 / 独立空间**落入 pgvector，向量维度迁移属落地 PR，本阶段**不建迁移、不改维度**。
- **失败回退**：嵌入或向量索引不可用 → 非向量召回（pg_trgm + 标签 + 产品硬过滤 + 结构化）；pgvector 扩展缺失则该路关闭、其余检索照常。向量得分仅多因子之一，不单独决定结果。
- **结论**：**现在应验证**（P0 已采用检索基座）。**验证基准**：素材搜索集（向量开 / 关对比）；分镜匹配集（结构化 `semantic_score` 贡献）。

#### 4）PySceneDetect —— **P0：拆镜头基线（已采用并持续复用）**【事实】

- **License**：BSD-3-Clause（宽松，可商用闭源 NAS，无 copyleft）。权重不适用（基于 OpenCV 像素统计的传统算法 ContentDetector / AdaptiveDetector / ThresholdDetector，**无模型权重，本阶段不下载任何权重**）。
- **维护**：活跃（v0.7，2026-05-03）。
- **I/O**：FFmpeg/FFprobe 可解码源视频（只读 `open(rb)`）→ 场景切分边界（帧号 + 时间码区间），可选 FFmpeg 派生分割片段 / 关键帧。映射为 **Shot 的时间码 + generation**；现有 `ShotDetector` 已用 **PySceneDetect 主 + 固定切分兜底**，本项为**复用其能力而非新增**。
- **CPU / NAS / 速度**：纯 CPU（OpenCV 像素差分），x86 NAS 直接可跑；内存低（与单帧分辨率相关，数十~数百 MB，不随时长膨胀）；优于实时到接近实时（可降采样 / 跳帧加速）。102 视频 / ≈4.66GB 全量拆镜头属可接受离线批处理，media-worker 默认并发 1 串行即可。PR-02 已引入 PySceneDetect + opencv-python-headless 后端。
- **价值**：把「目录乱、无法理解」的原始产品视频切成可检索 **Shot**，是产品识别 / 标签 / 语义检索 / 分镜匹配全链路前置。一个长拍产品视频内含多镜头（展示 / 握持 / 安装 / 特写），拆镜头后才能按动作 / 景别精确选镜并支撑全局分配与同源去重。**ClipMind 已落地能力（PR-02），本调研确认其许可证与可行性，不引入生成式能力。**
- **Provider / 回退**：已是可替换组件（`ShotDetector`：PySceneDetect 主 + 固定切分兜底），符合可降级模式，**无需作为外部 AI Provider**（本地确定性算法）。不可用 / 检测异常 → 回退**固定时长切分**保证不中断；再不行仅按整段建单 Shot。结论标【规则推断】，非 AI 推断。
- **结论**：**现在应验证**（P0，已采用并需持续复用）。**验证基准**：素材搜索集（拆镜头质量决定可检索 Shot 颗粒度与召回）；辅以分镜匹配集（镜头边界是否贴合可选片段）。真实素材 + 真实运行验收，CI 可用合成 testsrc。

#### 11）Chromaprint（AcoustID fpcalc）—— **P2：成片音频反查（后置）**

- **License**：核心 **MIT**，但仓库含 FFmpeg 部分（LGPL-2.1），官方 LICENSE 声明整体按 **LGPL-2.1** 处理。**【关键风险】最终 fpcalc 二进制的 FFT 库选择会传染许可证：用 FFTW3 编译会使二进制变为 GPL；应选 FFmpeg/KissFFT/vDSP 后端避免 GPL。NAS 部署须固定一个非 GPL 的官方 / 发行版二进制并留存许可证审计记录。** 权重不适用（确定性声学指纹算法，无权重，不下载权重）。
- **维护**：较慢但稳定（成熟 C 库，AcoustID/MusicBrainz 生态长期使用）；本阶段不冻结具体版本，落地 PR 再锁定一个非 GPL 二进制并记录。
- **I/O**：FFmpeg 可解码的音频 / 视频音轨（只读）→ 紧凑音频指纹；用于 **`suspected_audio_match`** 级成片 → 源镜头反查（成片含原片音轨时指纹比对得疑似引用）。纯 CPU，内存低，远超实时。
- **价值**：**中（针对性强但仅一条证据路径）**。价值在使用血缘：剪辑成片复用源片原始音轨时给出 `suspected_audio_match` 疑似引用，缓解「无法知道素材被哪些成片引用 / 使用次数不可追踪」（需求 §1.4–1.5）。但带货成片常配音 / 换 BGM / 去原声，音轨可能被替换，召回有限；按规格 **`suspected_audio_match` 不计入正式 `usage_count`，必须人工确认**。对「4 产品纯产品展示无对白」类素材命中率不确定，需真实验证。
- **Provider 接入**：作为成片反查 Provider 之一，输出固定 `evidence_level=suspected_audio_match` 的 `final_video_usage` 候选（`confirmed=false`）进人工审核队列，**绝不自动计数**；与 `suspected_visual_match`（pHash / DINOv2）并列为两条独立反查证据路径。
- **失败回退**：低命中 → 回退 `suspected_visual_match`（帧 / 关键帧 pHash 视觉反查）与 `confirmed_manual` / `confirmed_editor_project` / `confirmed_clipmap_export`（人工或工程文件 / 系统导出回填）。音频反查不可用不影响其余使用血缘证据链。
- **结论**：**后续可验证**（P2，非现阶段刚需）。先把工程文件解析 / 系统导出回填（`confirmed_*`）与 legacy 历史导入做扎实，音频指纹作补充疑似证据后置。**验证基准**：成片引用识别集（核心，用已知「成片 ↔ 源镜头」对照样本量化召回 / 精确，验证换 BGM / 配音后退化）。**本库当前疑似成片为 0，需公司先提供真实成片样本才能验收。**

---

## 3. 分档结论

### 3.1 现在应验证（已采用基座 + 建议本批先上公司基准验证）

| 技术 | 角色 | 一句话理由 | 主验证基准 |
|---|---|---|---|
| **MiMo Provider** | P0 理解基线 | 视觉打标 / query 解析 / script 解析事实基线，保持现状不在本组改动 | 产品识别集（间接素材搜索集） |
| **E5 本地 embedder** | P0 文本 dense 基线 | Hybrid Search dense 支柱，MIT 可商用，CPU 已验证 | 素材搜索集 / 分镜匹配集 |
| **pgvector** | P0 检索基座 | 已采用且硬约束要求，正交可降级 | 素材搜索集（向量开 / 关）/ 分镜匹配集 |
| **PySceneDetect** | P0 拆镜头基线 | 全链路前置，BSD 可商用，纯 CPU 已落地（PR-02） | 素材搜索集 / 分镜匹配集 |
| **OpenCLIP** | P1 视觉检索首选 | 补视觉召回维度，生态最广、CPU 可跑（须选商用 checkpoint） | 素材搜索集（参考图 → 镜头） |
| **SigLIP2** | P1 视觉检索并列首选 | 许可更干净（Apache-2.0 权重）、多语言精度更优，与 OpenCLIP 同期 A/B | 素材搜索集（多语言 Recall@K） |
| **Grounding DINO** | P1 产品识别最直接 | 开放词表检测用产品 / 品类词作 prompt 产 bbox → ShotTag/AssetProduct 候选，官方支持 CPU-only | 产品识别集 |

### 3.2 后续可验证（先离线 / 受控验证增益，再决定是否上线）

| 技术 | 角色 | 前置条件 / 注意 | 主验证基准 |
|---|---|---|---|
| **BGE Reranker v2-m3** | P1 本组最具增量 | 填 `rerank_candidates` 空槽；**仅 Top-K 精排，K 必须受控**；融合权重不冻结；先离线验证增益 | 素材搜索集 / 分镜匹配集 |
| **BGE-M3** | P2 dense 升级候选 | 1024 维 ≠ 384 维＝**全量重嵌 + 维度迁移**，本阶段只记录不实施；先 A/B | 素材搜索集 / 分镜匹配集 |
| **DINOv2** | P2 去重 / 同源去重专用 | 无文本塔，**不替代图文检索主路**；只用标准 backbone（避 NC 衍生权重） | 成片引用识别集 / 素材搜索集（以图搜图） |
| **Chromaprint** | P2 成片音频反查后置 | **fpcalc FFT 后端须非 GPL（避 FFTW3）**；`suspected_audio_match` 不计入次数；需真实成片样本 | 成片引用识别集 |
| **InternVideo2** | P2 视频原生嵌入条件性 | **双门槛：GPU 可用 + 权重商用合规（数据集 CC-BY-NC-SA 须法务确认）**；独立向量空间；不替换 E5 主路 | 素材搜索集 / 产品识别集 / 分镜匹配集 |

### 3.3 暂不采用（当前阶段）

| 技术 | 不采用理由 | 重新评估触发条件 |
|---|---|---|
| **SAM 2** | 只产分割掩码不做产品识别；**GPU 依赖与 CPU NAS 路线冲突**；价值属锦上添花，需与检测器级联（Grounded-SAM）才有意义，复杂度 / GPU 成本高 | Grounding DINO 已落地 + 确有 GPU 资源 + 明确「区域抠图 / 产品跟踪」需求；其中区域裁剪可先用「检测 bbox + FFmpeg 裁剪」替代 |

---

## 4. 落地边界与下一步（本阶段不执行）

> 以下为**冻结的设计倾向**，落地见 `../roadmap/ECOMMERCE_ASSET_INTELLIGENCE_ROADMAP.md`，本阶段**不建迁移、不改模型、不接模型、不下权重**。

1. **能力位归并**：现有 Provider 抽象需容纳三类新能力位——**视觉图文嵌入**（OpenCLIP/SigLIP2 互换）、**开放词表检测**（Grounding DINO）、**本地重排**（BGE Reranker 填 `rerank_candidates` 空槽）；以及条件性的**视频嵌入**（InternVideo2）。全部**遵循 `ProviderCapabilities` 降级**，缺失即回退，绝不伪造。
2. **向量空间**：视觉 / 视频嵌入维度 ≠ 文本 E5 的 384 维，落地时作为 `ShotSearchDocument` 的**独立向量列 / 独立空间**入 pgvector，与 `embedding_status` 正交。**维度与索引参数（HNSW）为落地 PR 评审项，本文不冻结。**
3. **证据映射**：检测 → `ShotTag[type=product, source=ai]` / `AssetProduct` 候选（【AI 推断】，`needs_human`）；视觉 / 音频反查 → `final_video_usage`（`suspected_visual_match` / `suspected_audio_match`，`confirmed=false`，不计入 `usage_count`）；规则命中 → 【规则推断】候选。**Confusable Group（软 / 硬屏）任何模型只给候选，强制人工确认。**
4. **精排与使用感知的次序**：BGE Reranker 精排须与**使用感知降权 / 同源去重**在**精排之后或并行**协同；最终融合权重**不在本规格冻结**，仅列可配置因素与默认倾向（语义 / 视觉 / 词法 / 标签 / 产品 / 质量 / 审核加成 / 风险惩罚 / 使用降权 / 同源去重）。
5. **许可证审计清单（落地前必须完成）**：
   - OpenCLIP：**只选 laion2b/datacomp 等商用 checkpoint**，逐个核对权重 License，排除 CC-BY-NC。
   - DINOv2：只用标准 ViT-S/B/L/g backbone，避开 FAIR Noncommercial 衍生权重；DINOv3 单独评估。
   - InternVideo2：**法务确认权重与训练数据集（CC-BY-NC-SA-4.0）的商用合规**，不通过则不采用。
   - Chromaprint：**固定一个非 GPL 的 fpcalc 二进制**（避 FFTW3 后端），留存许可证审计记录。
6. **验证优先级**：先在公司基准（素材搜索集 / 产品识别集 / 分镜匹配集）离线验证 P1（OpenCLIP/SigLIP2、Grounding DINO、BGE Reranker）增益；成片引用识别集需公司**先提供真实成片样本**（当前库疑似成片为 0）方可验收 DINOv2 / Chromaprint 反查。
