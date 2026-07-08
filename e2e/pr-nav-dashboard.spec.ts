import { expect, test } from "@playwright/test";

// P2b 导航重组 + 使用记录三页合一 + 首页运营仪表盘 真实浏览器 E2E。
// 无需专用播种：仪表盘聚合的是既有 API 的真实数字（CI 栈到此步已有素材）。

test.describe.serial("P2b 导航与仪表盘", () => {
  test("首页运营仪表盘：三大区块 + 快捷入口直达", async ({ page }) => {
    await page.goto("/");
    await expect(page.getByTestId("dash-pipeline")).toBeVisible();
    await expect(page.getByTestId("dash-products")).toBeVisible();
    await expect(page.getByTestId("dash-usage")).toBeVisible();
    await expect(page.getByTestId("dash-quick-links")).toBeVisible();
    // 处理进度数字为真实 API 值（不是骨架/空白）
    await expect(page.getByTestId("dash-videos-total")).not.toHaveText("");
    // OBS：管线健康卡片来自真实 /system/pipeline-health（徽标必有终态文案）
    await expect(page.getByTestId("dash-health")).toBeVisible();
    await expect(page.getByTestId("dash-health-badge")).toHaveText(/全部环节正常|项待处理/);
    console.log("OBS_UI_HEALTH_OK");
    // 快捷入口直达搜索工作台
    await page.getByTestId("dash-quick-links").getByRole("link", { name: /搜索/ }).click();
    await expect(page).toHaveURL(/\/search/);
    console.log("P2B_UI_DASHBOARD_OK");
  });

  test("使用记录中心三页合一：成片登记 Tab + 导入规则次级入口", async ({ page }) => {
    await page.goto("/usage-review");
    // 成片登记 Tab 内嵌成片工作台
    await page.getByTestId("tab-final-videos").click();
    await expect(page.getByTestId("final-videos-panel")).toBeVisible();
    await expect(page.getByTestId("toggle-create-final-video")).toBeVisible();
    // 规则与导入次级入口保留
    await expect(page.getByTestId("link-rules-imports")).toBeVisible();
    // 独立 /final-videos 路由保留且高亮「使用记录」
    await page.goto("/final-videos");
    await expect(page.getByTestId("nav-usage-review")).toHaveAttribute(
      "aria-current",
      "page",
    );
    console.log("P2B_UI_USAGE_TABS_OK");
  });

  test("产品入口：素材与目录互链 Tab", async ({ page }) => {
    await page.goto("/product-media");
    await expect(page.getByTestId("product-section-media")).toHaveAttribute(
      "aria-selected",
      "true",
    );
    await page.getByTestId("product-section-catalog").click();
    await expect(page).toHaveURL(/\/products/);
    await expect(page.getByTestId("product-section-catalog")).toHaveAttribute(
      "aria-selected",
      "true",
    );
    // 目录页高亮主导航「产品」
    await expect(page.getByTestId("nav-products-hub")).toHaveAttribute(
      "aria-current",
      "page",
    );
    console.log("P2B_UI_PRODUCT_TABS_OK");
    console.log("P2B_UI_E2E_OK");
  });

  test("@persist 重启后仪表盘与合一 Tab 保持可用", async ({ page }) => {
    await page.goto("/");
    await expect(page.getByTestId("dash-pipeline")).toBeVisible();
    await page.goto("/usage-review");
    await expect(page.getByTestId("tab-final-videos")).toBeVisible();
    console.log("P2B_UI_PERSIST_OK");
  });
});
