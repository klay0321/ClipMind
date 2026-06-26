import { expect, test, type APIRequestContext } from "@playwright/test";

// Gate C 真实页面 UI E2E：驱动真实 web 页面 + 真实 API（FakeProvider + FakeEmbedding）。
// 不写死结果、不 mock，从真实 suggestions / 搜索响应断言契约。截图证据按需在失败时保留。
//
// 前置：docker compose 全栈已起，且已播种合成数据并建索引（见 docs/SEARCH_UI.md 第 7 节）。
// 期望标志：SEARCH_UI_E2E_OK / DESCRIPTION_MATCH_UI_E2E_OK / SEARCH_UI_PERSIST_OK。

const API = process.env.API_BASE || "http://localhost:8000";
const SHOTS_DIR = process.env.SHOTS_DIR || "e2e/.artifacts";

/** 从真实 suggestions API 取一个可检索词（产品/场景/动作优先），失败兜底通用词。 */
async function pickTerm(request: APIRequestContext): Promise<string> {
  try {
    const res = await request.get(`${API}/api/search/suggestions?limit=20`);
    if (res.ok()) {
      const body = await res.json();
      const items: { value: string; type: string }[] = body.items ?? [];
      const pref = items.find((i) => ["product", "scene", "action"].includes(i.type));
      if (pref) return pref.value;
      if (items[0]) return items[0].value;
    }
  } catch {
    /* 兜底 */
  }
  return "镜头";
}

test("素材语义搜索：真实页面 + 真实 API", async ({ page, request }) => {
  const term = await pickTerm(request);
  await page.goto("/search");
  await expect(page.getByRole("heading", { name: "智能搜索" })).toBeVisible();

  await page.getByTestId("search-input").fill(term);
  await page.getByTestId("search-submit").click();

  // 结果元信息出现（成功或空都会渲染），再断言至少一张结果卡（已播种数据应有结果）
  await expect(page.getByTestId("results-meta")).toBeVisible();
  const cards = page.getByTestId("search-result-card");
  await expect(cards.first()).toBeVisible();

  await page.screenshot({ path: `${SHOTS_DIR}/02-search-results.png`, fullPage: false });

  // 打开详情抽屉并断言详情入口（点卡片标题区，避免点到非交互留白）
  await page.getByTitle("查看匹配详情").first().click();
  await expect(page.getByTestId("result-drawer")).toBeVisible();
  await expect(page.getByTestId("drawer-detail-link")).toBeVisible();
  await page.screenshot({ path: `${SHOTS_DIR}/04-match-detail.png`, fullPage: false });

  // eslint-disable-next-line no-console
  console.log("SEARCH_UI_E2E_OK");
});

test("画面描述匹配：真实页面 + 真实 API", async ({ page, request }) => {
  const term = await pickTerm(request);
  await page.goto("/search?mode=description");
  await expect(page.getByTestId("tab-description")).toHaveAttribute("aria-selected", "true");

  await page.getByTestId("desc-input").fill(term);
  await page.getByTestId("desc-match").click();

  await expect(page.getByTestId("desc-meta")).toBeVisible();
  await expect(page.getByTestId("match-result-row").first()).toBeVisible();
  await page.screenshot({ path: `${SHOTS_DIR}/05-description-match.png`, fullPage: false });

  // eslint-disable-next-line no-console
  console.log("DESCRIPTION_MATCH_UI_E2E_OK");
});

test("@persist 重启后搜索仍可用", async ({ page, request }) => {
  const term = await pickTerm(request);
  await page.goto("/search");
  await page.getByTestId("search-input").fill(term);
  await page.getByTestId("search-submit").click();
  await expect(page.getByTestId("results-meta")).toBeVisible();
  await expect(page.getByTestId("search-result-card").first()).toBeVisible();

  // eslint-disable-next-line no-console
  console.log("SEARCH_UI_PERSIST_OK");
});
