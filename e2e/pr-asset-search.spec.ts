import { expect, test } from "@playwright/test";

// P2a 素材级统一搜索 UI E2E：检索目标 Tab（镜头|整条视频|图片）+ 素材面板检索。
// 前置：ci_asset_search_e2e.py --mode full 已运行（AAPS-E2E 图片/视频已可搜）。

test.describe.serial("P2a 素材级搜索 UI", () => {
  test("目标 Tab 切换与图片检索面板", async ({ page }) => {
    await page.goto("/search");
    await expect(page.getByTestId("search-target-tabs")).toBeVisible();
    // 默认镜头 Tab（既有链路不变）
    await expect(page.getByTestId("search-target-shots")).toHaveAttribute(
      "aria-selected",
      "true",
    );
    // 切图片 Tab → 素材检索面板
    await page.getByTestId("search-target-image").click();
    await expect(page.getByTestId("asset-search-image")).toBeVisible();
    await expect(page.getByTestId("asset-search-family")).toBeVisible();
    // 空查询浏览：直接搜索应能返回（库里已有可搜图片）
    await page.getByTestId("asset-search-submit").click();
    await expect(page.getByTestId("asset-search-results")).toBeVisible({
      timeout: 15000,
    });
    // 切整条视频 Tab
    await page.getByTestId("search-target-video").click();
    await expect(page.getByTestId("asset-search-video")).toBeVisible();
    // IMG-SEARCH：以图搜图 Tab 与面板可达
    await page.getByTestId("search-target-visual").click();
    await expect(page.getByTestId("visual-search-panel")).toBeVisible();
    await expect(page.getByTestId("visual-search-submit")).toBeDisabled();
    console.log("AAPS_UI_E2E_OK");
  });

  test("@persist 重启后 Tab 与素材检索可用", async ({ page }) => {
    await page.goto("/search");
    await page.getByTestId("search-target-image").click();
    await page.getByTestId("asset-search-submit").click();
    // 面板可用即通过：返回结果或空态皆可——数据持久性由 API 级
    // AAPS_RESTART_PERSIST_OK 保证；其他 persist spec 可能清理各自数据，
    // UI persist 不与库内容顺序耦合。
    await expect(
      page
        .getByTestId("asset-search-results")
        .or(page.getByText("没有匹配的图片")),
    ).toBeVisible({ timeout: 15000 });
    console.log("AAPS_UI_PERSIST_OK");
  });
});
