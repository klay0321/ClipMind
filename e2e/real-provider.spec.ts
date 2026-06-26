import { expect, test, type APIRequestContext, type Page } from "@playwright/test";

// Gate C.1：真实 MiMo Parser + 真实 E5 的 UI 端到端抽检（驱动真实页面 + 真实 API）。
// 按标签分阶段运行（外部用 docker 改变 embedder/parser 状态）：
//   @normal           正常完整模式（parser=mimo ok / embedding ok / degraded=false / semantic 非空）
//   @embdegraded      停 embedder 后降级（embedding_status=degraded / degraded=true / 无 semantic / 词法仍返回）
//   @embrecovered     重启 embedder 后自动恢复（degraded=false / semantic 恢复）
//   @parserdegraded   MiMo Parser 超时降级（parser_status=degraded / 词法结构化仍返回）
//   @parserrecovered  恢复后 parser_status=ok
// 不 mock、不前端造数；标志只在真实断言通过后输出。绝不打印 Key/Endpoint/Authorization。

const API = process.env.API_BASE || "http://localhost:8000";

// 真实 Provider 验收是**本地手动**流程：需真实 MiMo + 真实 E5 embedder + 显式开关。
// 普通 CI（含 ui-e2e）绝不运行本文件——既靠 CI 只显式指定 search-ui.spec.ts，也靠此处 env 门禁。
// 缺 RUN_REAL_PROVIDER_E2E=1 时整文件 skip，绝不在 FakeProvider 下伪造 REAL_* 标志。
const RUN_REAL = process.env.RUN_REAL_PROVIDER_E2E === "1";
test.beforeEach(() => {
  test.skip(!RUN_REAL, "真实 Provider 手动验收：需 RUN_REAL_PROVIDER_E2E=1（CI 默认跳过）");
});

const ZH = "找桌面上给手机充电的竖屏镜头，不要人脸";
const EN = "Find a clean vertical product shot in a car interior, no people";
const MIX = "找 outdoor 安装产品的 close-up，exclude blurry shots";

/** 取一个真实可词法命中的种子词（产品/场景/动作），供降级模式确保仍有结果。 */
async function lexicalTerm(request: APIRequestContext): Promise<string> {
  const r = await request.get(`${API}/api/search/suggestions?limit=20`);
  if (r.ok()) {
    const b = await r.json();
    const items: { value: string; type: string }[] = b.items ?? [];
    const pref = items.find((i) => ["product", "scene", "action"].includes(i.type));
    if (pref) return pref.value;
    if (items[0]) return items[0].value;
  }
  return "镜头";
}

function watch(page: Page) {
  const consoleErrors: string[] = [];
  const serverErrors: string[] = [];
  page.on("console", (m) => {
    if (m.type() === "error") consoleErrors.push(m.text());
  });
  page.on("response", (r) => {
    if (r.url().includes("/api/search") && r.status() >= 500) {
      serverErrors.push(`${r.status()} ${r.url().split("?")[0]}`);
    }
  });
  return { consoleErrors, serverErrors };
}

/** 在真实页面执行一次搜索，返回 UI 实际发出的搜索响应体（断言 UI 渲染 + 无 5xx）。 */
async function uiSearch(page: Page, query: string, mode: "search" = "search") {
  await page.goto("/search");
  await page.getByTestId("search-input").fill(query);
  const respP = page.waitForResponse(
    (r) => r.url().includes("/api/search/shots") && r.request().method() === "POST",
  );
  await page.getByTestId("search-submit").click();
  const resp = await respP;
  expect(resp.status(), "search api must not 5xx").toBeLessThan(500);
  const body = await resp.json();
  await expect(page.getByTestId("results-meta")).toBeVisible();
  return body;
}

test("@normal 真实 MiMo+E5 三语搜索（中/英/混合）正常完整模式", async ({ page, request }) => {
  const w = watch(page);
  for (const [label, q] of [
    ["zh", ZH],
    ["en", EN],
    ["mix", MIX],
  ] as const) {
    const body = await uiSearch(page, q);
    expect(body.parser_status, `${label} parser_status`).toBe("ok");
    expect(String(body.parser_provider), `${label} parser_provider`).toContain("mimo");
    expect(body.embedding_status, `${label} embedding_status`).toBe("ok");
    expect(body.degraded, `${label} degraded`).toBe(false);
    expect(body.degradation_reasons ?? [], `${label} degradation_reasons`).toHaveLength(0);
    // 真实进入向量通道：至少一个候选有非空 semantic_score
    const withSem = (body.items ?? []).filter((it: { semantic_score: number | null }) => it.semantic_score != null);
    expect(withSem.length, `${label} 至少一个 semantic_score 非空`).toBeGreaterThan(0);
    // 页面未显示 parser/embedding 降级提示
    await expect(page.getByTestId("degraded-parser")).toHaveCount(0);
    await expect(page.getByTestId("degraded-embedding")).toHaveCount(0);
  }
  expect(w.serverErrors, "无 5xx").toEqual([]);
  expect(w.consoleErrors, "无 console error").toEqual([]);
  // eslint-disable-next-line no-console
  console.log("REAL_MIMO_SEARCH_UI_OK");
  // eslint-disable-next-line no-console
  console.log("REAL_E5_SEARCH_UI_OK");
  // eslint-disable-next-line no-console
  console.log("REAL_PROVIDER_SEARCH_UI_OK");
});

test("@normal 真实 Description Match（产品+场景+动作+画幅+风险排除+最低匹配度）", async ({ page, request }) => {
  const term = await lexicalTerm(request);
  await page.goto("/search?mode=description");
  await page.getByTestId("desc-input").fill(`${term} 室内 展示 竖屏 演示`);
  await page.getByTestId("desc-exclude-risks").fill("competitor");
  // 画幅 9:16 + 最低匹配度 10%
  const aspect = page.locator('[aria-pressed]', { hasText: "9:16" }).first();
  if (await aspect.count()) await aspect.click();
  await page.getByTestId("desc-min-score").evaluate((el: HTMLInputElement) => {
    el.value = "10";
    el.dispatchEvent(new Event("input", { bubbles: true }));
    el.dispatchEvent(new Event("change", { bubbles: true }));
  });
  const respP = page.waitForResponse(
    (r) => r.url().includes("/api/match/description") && r.request().method() === "POST",
  );
  await page.getByTestId("desc-match").click();
  const resp = await respP;
  expect(resp.status()).toBeLessThan(500);
  const body = await resp.json();
  expect(body.parser_status).toBe("ok");
  expect(body.embedding_status).toBe("ok");
  expect(Array.isArray(body.target_requirements)).toBe(true);
  expect(typeof body.minimum_score).toBe("number");
  expect(typeof body.filtered_total).toBe("number");
  expect(typeof body.truncated).toBe("boolean");
  await expect(page.getByTestId("desc-meta")).toBeVisible();
  if ((body.items ?? []).length > 0) {
    const it = body.items[0];
    expect(["high", "medium", "low", "not_recommended"]).toContain(it.recommendation_level);
    expect(typeof it.requires_human_confirmation).toBe("boolean");
    expect(Array.isArray(it.matched_requirements)).toBe(true);
    await expect(page.getByTestId("match-result-row").first()).toBeVisible();
  }
  // eslint-disable-next-line no-console
  console.log("REAL_DESCRIPTION_MATCH_UI_OK");
});

test("@embdegraded 停 embedder 后 UI 真实降级但仍返回词法结果", async ({ page, request }) => {
  const term = await lexicalTerm(request);
  const body = await uiSearch(page, term);
  expect(["degraded", "unavailable"]).toContain(body.embedding_status);
  expect(body.degraded).toBe(true);
  const withSem = (body.items ?? []).filter((it: { semantic_score: number | null }) => it.semantic_score != null);
  expect(withSem.length, "降级时无 semantic_score").toBe(0);
  // 词法/标签/产品仍返回（用种子词应有命中）
  expect(body.total, "降级仍有词法结果").toBeGreaterThan(0);
  await expect(page.getByTestId("degraded-embedding")).toBeVisible();
  // 结果理由不得出现“语义相似（向量召回）”（degraded item 契约）。
  // 注意：不能用页面级 getByText——搜索模式区的“语义”模式说明文案本身含“语义相似”，属正常 UI。
  const semanticInReasons = (body.items ?? []).some((it: { matched_reasons: string[] }) =>
    (it.matched_reasons ?? []).some((r) => r.includes("语义相似")),
  );
  expect(semanticInReasons, "降级结果理由不得含语义相似").toBe(false);
  // eslint-disable-next-line no-console
  console.log("EMBEDDING_DEGRADED_UI_OK");
});

test("@embrecovered 重启 embedder 后无需重启 API/web 自动恢复", async ({ page, request }) => {
  const term = await lexicalTerm(request);
  const body = await uiSearch(page, term);
  expect(body.embedding_status).toBe("ok");
  expect(body.degraded).toBe(false);
  const withSem = (body.items ?? []).filter((it: { semantic_score: number | null }) => it.semantic_score != null);
  expect(withSem.length, "恢复后 semantic_score 回来").toBeGreaterThan(0);
  await expect(page.getByTestId("degraded-embedding")).toHaveCount(0);
  // eslint-disable-next-line no-console
  console.log("EMBEDDING_AUTO_RECOVERY_UI_OK");
});

test("@parserdegraded MiMo Parser 超时降级，词法/结构化仍可用", async ({ page, request }) => {
  const term = await lexicalTerm(request);
  const body = await uiSearch(page, term);
  expect(body.parser_status).toBe("degraded");
  expect(body.total, "parser 降级仍返回结果").toBeGreaterThan(0);
  await expect(page.getByTestId("degraded-parser")).toBeVisible();
  // eslint-disable-next-line no-console
  console.log("PARSER_DEGRADED_UI_OK");
});

test("@parserrecovered 恢复真实 MiMo 配置后 parser_status=ok", async ({ page, request }) => {
  const body = await uiSearch(page, ZH);
  expect(body.parser_status).toBe("ok");
  expect(String(body.parser_provider)).toContain("mimo");
  await expect(page.getByTestId("degraded-parser")).toHaveCount(0);
  // eslint-disable-next-line no-console
  console.log("PARSER_AUTO_RECOVERY_UI_OK");
});
