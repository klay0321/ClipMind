# ClipMind Gate C 真实页面 UI E2E（Playwright）

驱动**真实运行的 web 页面 + 真实 API**（不 mock、不调浏览器内过滤），验证 `/search` 工作台。
与仓库内的 Python E2E（`scripts/ci_*_e2e.py`，断言后端契约）互补——这里断言**真实 UI**。

## 前置

全栈已起且已播种数据（FakeProvider + FakeEmbedding）：

```bash
# 项目根：.env 配 AI_PROVIDER=fake / EMBEDDING_PROVIDER=fake / SEARCH_QUERY_PARSER=fake
docker compose up -d --build
python scripts/ci_pr02_e2e.py --mode full     # 合成视频→扫描→拆镜头
python scripts/gate_c_e2e_seed.py             # AI(fake) + 产品 + 审核
python scripts/ci_search_e2e.py --mode full   # 验证 FakeEmbedding 索引（SEARCH_E2E_OK）
```

## 运行

```bash
cd e2e
npm install
npx playwright install --with-deps chromium

# 主流程（搜索 + 画面描述匹配）
WEB_BASE=http://localhost:3000 API_BASE=http://localhost:8000 npm run test:main
#   → SEARCH_UI_E2E_OK / DESCRIPTION_MATCH_UI_E2E_OK

# 重启后持久化
docker compose restart api web search-worker
WEB_BASE=http://localhost:3000 API_BASE=http://localhost:8000 npm run test:persist
#   → SEARCH_UI_PERSIST_OK
```

## 环境变量

| 变量 | 默认 | 说明 |
|---|---|---|
| `WEB_BASE` | `http://localhost:3000` | 真实 web 页面地址 |
| `API_BASE` | `http://localhost:8000` | 真实 API（仅用于取真实可检索词） |
| `SHOTS_DIR` | `e2e/.artifacts` | 截图输出目录（已 gitignore） |

截图、报告、`node_modules` 均已 `.gitignore`，不提交二进制进 Git。
