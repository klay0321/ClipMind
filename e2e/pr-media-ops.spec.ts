import { expect, test, type APIRequestContext } from "@playwright/test";

// OPS 真实浏览器 UI E2E：分组审核队列 + 操作历史撤销。
// 前置：ci_product_media_ops_e2e.py --mode full 已运行（POPS-E2E 数据 +
// 已有一次 bulk 操作与一次 undo 在审计里）。

const API = process.env.API_BASE || "http://localhost:8000";

async function hasPopsFamily(request: APIRequestContext): Promise<boolean> {
  const res = await request.get(`${API}/api/product-media/summary`);
  if (!res.ok()) return false;
  const rows = (await res.json()) as { code: string }[];
  return rows.some((r) => r.code.includes("POPS-E2E"));
}

test.describe.serial("OPS 分组审核 UI", () => {
  test("分组队列/覆盖徽标/操作历史可见", async ({ page, request }) => {
    test.skip(!(await hasPopsFamily(request)), "缺少 POPS-E2E 播种数据");
    await page.goto("/product-media");
    // 分组审核区
    await expect(page.getByTestId("grouped-review")).toBeVisible();
    await expect(page.getByTestId("review-total")).toBeVisible();
    // 分组方式切换
    await page.getByTestId("group-by-directory").click();
    await expect(page.getByTestId("review-total")).toBeVisible();
    await page.getByTestId("group-by-suggested_family").click();
    // 覆盖状态徽标（产品列表）
    await expect(page.locator('[data-testid^="coverage-"]').first()).toBeVisible();
    // 操作历史：含 bulk_link 与 undo 事件（API E2E 已产生）
    await page.getByTestId("toggle-operations").click();
    await expect(page.getByTestId("operations-panel")).toBeVisible();
    await expect(page.getByTestId("operations-panel")).toContainText("bulk_link");
    await expect(page.getByTestId("operations-panel")).toContainText("undo");
    console.log("POPS_UI_E2E_OK");
  });

  test("@persist 重启后审计与统计保持", async ({ page, request }) => {
    test.skip(!(await hasPopsFamily(request)), "缺少 POPS-E2E 播种数据");
    await page.goto("/product-media");
    await page.getByTestId("toggle-operations").click();
    await expect(page.getByTestId("operations-panel")).toContainText("undo");
    await expect(page.locator('[data-testid^="coverage-"]').first()).toBeVisible();
    console.log("POPS_UI_PERSIST_OK");
  });
});
