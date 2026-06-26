# PR-04 Gate C：语义搜索 / 画面描述匹配 UI

本文件描述 Gate C（前端）的落地。**最高事实来源仍是 `docs/PRODUCT_REQUIREMENTS.md` 与 UI 参考图
`docs/ui-reference/04-description-matching.jpg`**；后端契约见 `docs/SEMANTIC_SEARCH.md` 第 10 节。

Gate C 只做 UI，不新增搜索算法、不改向量模型、不做 SearchHistory、不做脚本匹配（PR-05）、不做鉴权（PR-07）。
所有匹配度 / 分项分 / 匹配理由 / 风险 / 审核状态 **只读后端事实，绝不在前端伪造或重算**。

## 1. 路由与页面结构

统一搜索工作台：**`/search`**（动态渲染）。通过顶部标签在两种模式间切换，复用同一套
搜索表单 / 高级筛选 / 结果卡 / 解释面板 / 镜头预览 / 状态组件，不复制两套前端逻辑：

- **素材语义搜索**（默认）：自然语言 + 结构化条件混合检索，网格结果卡。
- **画面描述匹配**：对照 UI 参考图 04，左侧画面描述 + 匹配设置，右侧按综合匹配度排序的候选镜头。

TopNav 新增「智能搜索」入口（`active="search"`），不破坏素材库 / 镜头库 / 产品库 / 审核工作台。

核心搜索状态（`mode / q / 搜索模式 / 排序 / 页 / 产品`）同步到 URL query，刷新可恢复；
**不写入任何敏感信息**（无 Key/Endpoint/Cookie）。高级筛选保留在组件内存态以保持 URL 简洁。

## 2. 数据层（前端）

- 类型：`apps/web/lib/types.ts`（Gate B 段：`ShotSearchRequest/ShotSearchResponse/SearchResultItem/
  DescriptionMatch*/SearchSuggestion/SearchIndexStatus/ParsedSearchQuery` 等，与 `apps/api/app/schemas/search.py` 一一对应）。
- API client：`apps/web/lib/api.ts` 新增 `searchShots / matchDescription / searchSuggestions /
  searchIndexStatus / rebuildSearchShot / sweepSearchIndex`，POST 走 JSON、复用 `http<T>` 与 `ApiError`，
  请求带 `AbortSignal`。同源代理 `app/api/[...path]` 已覆盖新端点，无需改动。
- Hooks：`apps/web/lib/hooks.ts` 新增 `useSemanticSearch / useDescriptionMatch / useSearchSuggestions /
  useSearchIndexStatus`。`queryFn` 接 TanStack `signal` → fetch abort，**旧请求被新请求取消，无竞态覆盖**；
  分页/排序用 `placeholderData: keepPreviousData` 保留上页；index status 仅在建设/降级时轮询。
  > 命名：已有 `useShotSearch`（打 `/shot-search`，PR-03B 结构化筛选）与 Gate B `/search/shots` 不同，
  > 故新 hook 命名为 `useSemanticSearch` 等，互不混用。
- 纯逻辑：`apps/web/lib/search.ts`（标签 / 格式化 / 请求组装 / 索引健康 / URL 状态，无副作用、可单测）。

## 3. 组件（`apps/web/components/search/`）

| 组件 | 职责 |
|---|---|
| `SearchWorkbench` | 编排：模式切换、URL 同步、共享详情抽屉 + 预览弹窗、索引状态 |
| `SemanticSearchView` | 语义搜索：搜索栏 + 高级筛选 + 结果元信息/排序/网格/分页 + 状态 |
| `DescriptionMatchView` | 画面描述匹配（参考图 04）：描述输入 + 匹配设置 + 结果行 |
| `SearchBar` | 自然语言输入（中/英/混合/多行/否定）、搜索模式、示例、防抖建议下拉 |
| `AdvancedFilters` | 折叠高级筛选（19 项），危险项 `include_excluded` 置危险区 |
| `SearchResultCard` / `MatchResultRow` | 结果卡（网格）/ 结果行（参考图 04） |
| `MatchScore` / `ScoreBreakdown` / `MatchExplanation` | 综合匹配度 / 分项分 / 理由·不匹配·风险 |
| `SearchResultDrawer` | 详情抽屉：搜索专属解释 + 复用 `ShotDetail`（预览/导出下载/审核） |
| `IndexStatusIndicator` | 索引健康简化态（正常/建设中/部分降级/异常）+ 可展开详情 |
| `DegradedNotice` | 诚实降级提示（parser/embedding/索引），区别于错误，正常态不显示 |
| `SearchBadges` | 审核状态 / 风险 / degraded / 推荐等级 / 产品匹配方式徽章 |

详情抽屉复用既有 `ShotDetail`（含 `ReviewPanel`），**不复制一套新的镜头详情数据结构**；
场景/动作/镜头类型经既有 `effective-result` 在审核面板展示。预览复用 `PreviewModal`，视频按需加载。

## 4. 真实 API 接入

| 端点 | 用途 |
|---|---|
| `POST /api/search/shots` | 语义/混合检索 |
| `POST /api/match/description` | 画面描述匹配 |
| `GET /api/search/suggestions` | 输入建议（产品/品牌/场景/动作/营销/镜头类型/标签） |
| `GET /api/search/index/status` | 索引健康 |
| `POST /api/search/index/rebuild/shot/{id}`、`/sweep` | 管理操作（不进普通用户主流程） |

前端**不**写死结果 / 随机分 / 写死理由或风险 / 浏览器内过滤冒充后端 / 静态 mock 冒充真实 API。

## 5. 诚实降级（可靠性设计，非默认效果）

直接读后端 `parser_status` / `embedding_status(ok|degraded|unavailable)` / `degraded` /
`degradation_reasons` 与 index status：

- **Parser degraded**：「AI 查询理解暂时不可用，已使用关键词和筛选条件搜索。」
- **Embedding degraded**：「语义相似检索暂时不可用，当前结果来自关键词、标签、产品和筛选条件。」
- **索引建设中**：「部分新素材仍在建立索引，当前结果可能不完整。」
- degraded item 标「语义降级」，不显示「语义相似」；不隐藏降级、不把降级显示成全部失败、不清空词法结果；
  正常模式（均 ok）不渲染降级提示。

## 6. 前端验证

```bash
cd apps/web
npm run lint && npm run typecheck && npm test && npm run build
```

测试：`apps/web/__tests__/search/`（vitest + Testing Library，无 MSW，按既有约定 `vi.mock("@/lib/hooks")`），
覆盖请求组装、四种搜索模式、建议、高级筛选、风险包含/排除、产品/时长/画幅/审核状态、排序、分页、
total/filtered_total/truncated、匹配理由/不匹配项/风险、parser/embedding degraded、索引建设中、空、错误、
画面描述匹配、minimum_score、recommendation_level、requires_human_confirmation、URL 状态恢复、请求竞态、视频按需加载。

## 7. 真实 Docker 全栈 UI E2E

UI E2E 用 Playwright 驱动**真实页面 + 真实 API**（FakeProvider + FakeEmbedding），见 `e2e/`：

```bash
# 1) 起全栈（fake provider；项目根，.env 配 AI_PROVIDER=fake / EMBEDDING_PROVIDER=fake / SEARCH_QUERY_PARSER=fake）
docker compose up -d --build
# 2) 播种合成数据（合成视频→扫描→拆镜头→AI(fake)→建产品→审核）+ 建索引
python scripts/ci_pr02_e2e.py --mode full          # 合成视频/扫描/拆镜头
python scripts/gate_c_e2e_seed.py                  # AI 分析(fake) + 产品 + 审核
python scripts/ci_search_e2e.py --mode full        # 验证检索文档/FakeEmbedding 索引
# 3) UI E2E（真实页面）
cd e2e && npm install && npx playwright install --with-deps chromium
WEB_BASE=http://localhost:3000 API_BASE=http://localhost:8000 npx playwright test
# 期望输出：SEARCH_UI_E2E_OK / DESCRIPTION_MATCH_UI_E2E_OK
# 4) 重启后持久化
docker compose restart api web search-worker
WEB_BASE=http://localhost:3000 npx playwright test --grep @persist   # SEARCH_UI_PERSIST_OK
```

覆盖：中文/英文/中英混合搜索、产品/场景+动作、风险排除、排序、分页、degraded 展示、画面描述匹配、
打开详情、预览、重启后仍可搜。E2E 验证真实页面与真实 API，**不只调用后端**。

## 8. 真实 Provider UI 验收（本地，可选）

本地用真实 MiMo Parser + 真实 E5（`docker compose --profile embedding up -d embedder`，
`.env` 配 `SEARCH_QUERY_PARSER=mimo` + `EMBEDDING_PROVIDER=openai_compatible`）验证中文/英文/混合查询的
`parser_status=ok`、`embedding_status=ok`、`degraded=false`、`semantic_score` 非空、匹配理由含真实语义/结构化原因；
停 embedder → UI 降级；恢复 → 能力恢复（无需刷新系统或改代码）。**真实 Key/Endpoint/Authorization 绝不入截图/日志/Git。**

## 9. 安全

- 不在 localStorage 存 Key；不把敏感配置下发浏览器；不直接暴露 embedder Endpoint。
- 前端不传任意 SQL 字段；`search_mode`/`sort`/`aspect_ratios`/`review_statuses` 为固定枚举（非法值后端 422）；
  `page_size` 前后端均有上限（前端 24，后端 ≤100）。
- 重建/sweep 等管理操作不在普通用户主流程；下载/预览复用既有安全资源接口（HTTP Range 代理）。
- URL 仅存核心非敏感条件。

## 10. 性能

- 图片优先 + `loading="lazy"`，卡片层不自动加载视频；视频仅在打开预览/详情时按需加载。
- 搜索请求带 `AbortSignal`，旧请求被取消；建议防抖 250ms；index status 仅建设/降级时轮询、正常态停止。
- 分页/排序保留 query 与筛选，`keepPreviousData` 避免整页闪烁。

## 11. 后端依赖修复：api 缺 httpx（real E5 路径）

Gate C.1 真实 MiMo + 真实 E5 抽检中发现一个**真实后端打包缺陷**并最小修复：

- **现象**：`EMBEDDING_PROVIDER=openai_compatible` 时，`GET /api/search/index/status` 与搜索/匹配端点 500，
  `ModuleNotFoundError: No module named 'httpx'`。
- **根因**：`httpx` 原只列在 `apps/api/pyproject.toml` 的 `[project.optional-dependencies] dev`；
  api 镜像 `pip install /code/apps/api`（不带 `[dev]`）不装 dev extra → 运行时缺 httpx。而查询期语义向量化经
  `clipmind_shared` 的 `OpenAICompatibleEmbeddingProvider`（**惰性** `import httpx`）调用本地/外部 embedder 的
  `/embeddings`。CI 一直用 `FakeEmbedding`（不导入 httpx）故从未暴露。
- **修复**：把 `httpx>=0.27,<0.29` 从 api 的 `dev` extra **移入主 `dependencies`**（与 `services/worker` 一致）；
  不在 main 与 dev 重复声明。`FakeEmbedding` 路径不受影响（不导入 httpx）。
- **验证**：api 镜像 `--no-cache` 重建后 `import httpx` 成功；`openai_compatible` 下 `index/status` 200、查询向量真实调用；
  `alembic upgrade→downgrade→upgrade` 通过、`alembic check` 无新迁移（**零数据库迁移**）。

## 12. CI

- `frontend`：lint / typecheck / test / build。
- `backend`：`-e shared + apps/api[dev] + services/worker[dev]` + `ruff` + 完整 `pytest`（pgvector 测试库）。
- `compose-config`：`docker compose config`。
- `docker-e2e`：FakeProvider + FakeEmbedding 全栈 Gate A/B API E2E（含重启持久化）。
- `ui-e2e`（**本 PR 新增**）：FakeProvider + FakeEmbedding 下真实页面 UI E2E，仅运行 `e2e/search-ui.spec.ts`
  （Chromium），输出 `SEARCH_UI_E2E_OK / DESCRIPTION_MATCH_UI_E2E_OK / SEARCH_UI_PERSIST_OK`；
  **不**下载 E5 模型、**不**用真实 MiMo Key、**不**启 embedder。
- `e2e/real-provider.spec.ts` 是**本地手动**真实 MiMo/E5 验收，受 `RUN_REAL_PROVIDER_E2E=1` 门禁，普通 CI 跳过，
  绝不在 FakeProvider 下伪造 `REAL_*` 标志。
