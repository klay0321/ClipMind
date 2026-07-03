import { expect, test, type APIRequestContext } from "@playwright/test";

// PR-C 真实浏览器 UI E2E：素材身份 / 位置历史 / 分析代次。
// 前置：docker compose 全栈已起，且 ci_pr_c_identity_e2e.py --mode full 已运行
// （栈内存在带移动历史 + 双代次 + full_hash 的 PRC-E2E 素材）。
// 验证 Asset 详情抽屉的身份面板真实渲染：指纹状态 / 缩短哈希 / 位置历史
// （present+historical）/ 代次列表（current+retired）/ 语义文案；
// @persist 重启后仍在。

const API = process.env.API_BASE || "http://localhost:8000";

async function apiJson(request: APIRequestContext, path: string): Promise<unknown> {
  const res = await request.get(`${API}${path}`);
  if (!res.ok()) throw new Error(`GET ${path} -> ${res.status()}`);
  return res.json();
}

/** 找 ci_pr_c_identity_e2e 播种的源素材（有位置历史与双代次）。 */
async function findSeedAsset(request: APIRequestContext): Promise<number | null> {
  const data = (await apiJson(
    request,
    "/api/assets?page=1&page_size=50&q=PRC-E2E-src",
  )) as { items: { id: number; filename: string }[] };
  const hit = data.items.find((a) => a.filename.startsWith("PRC-E2E-src"));
  return hit?.id ?? null;
}

test.describe.serial("PR-C 素材身份 UI", () => {
  test("身份面板：指纹/短哈希/位置历史/代次列表", async ({ page, request }) => {
    const assetId = await findSeedAsset(request);
    test.skip(assetId == null, "缺少 PRC-E2E 播种数据（先运行 API E2E full）");

    await page.goto("/assets");
    // 按文件名搜索后经行内菜单打开详情抽屉
    await page.getByLabel("搜索文件名").fill("PRC-E2E-src");
    const row = page.locator("tbody tr", { hasText: "PRC-E2E-src" }).first();
    await expect(row).toBeVisible();
    await row.getByLabel(/更多操作/).click();
    await page.getByText("查看详情").click();

    const panel = page.getByTestId("asset-identity-panel");
    await expect(panel).toBeVisible();
    // 指纹状态与缩短哈希（不暴露完整 64 位）
    await expect(page.getByTestId("fingerprint-state")).toContainText("完整指纹就绪");
    const fullHash = await page.getByTestId("full-hash").textContent();
    expect(fullHash).toMatch(/^[0-9a-f]{12}…$/);
    // 位置历史：历史 + 在位 + primary 唯一
    const rows = page.getByTestId(/location-row-/);
    await expect(rows.first()).toBeVisible();
    await expect(panel).toContainText("历史位置");
    await expect(panel).toContainText("primary");
    // 代次列表：current + retired + 语义文案
    const gens = page.getByTestId("generation-list");
    await expect(gens).toContainText("current");
    await expect(gens).toContainText("retired");
    await expect(panel).toContainText("文件路径变化不会改变素材身份");
    console.log("PR_C_UI_IDENTITY_OK");
    console.log("PR_C_UI_LOCATIONS_OK");
    console.log("PR_C_UI_GENERATIONS_OK");
    console.log("PR_C_UI_E2E_OK");
  });

  test("@persist 重启后身份面板数据仍在", async ({ page, request }) => {
    const assetId = await findSeedAsset(request);
    test.skip(assetId == null, "缺少 PRC-E2E 播种数据");
    const identity = (await apiJson(request, `/api/assets/${assetId}/identity`)) as {
      full_hash_available: boolean;
      historical_generation_count: number;
      location_count: number;
    };
    expect(identity.full_hash_available).toBe(true);
    expect(identity.historical_generation_count).toBeGreaterThanOrEqual(1);
    expect(identity.location_count).toBeGreaterThanOrEqual(2);

    await page.goto("/assets");
    await page.getByLabel("搜索文件名").fill("PRC-E2E-src");
    const row = page.locator("tbody tr", { hasText: "PRC-E2E-src" }).first();
    await expect(row).toBeVisible();
    await row.getByLabel(/更多操作/).click();
    await page.getByText("查看详情").click();
    await expect(page.getByTestId("asset-identity-panel")).toBeVisible();
    await expect(page.getByTestId("generation-list")).toContainText("retired");
    console.log("PR_C_UI_PERSIST_OK");
  });
});
