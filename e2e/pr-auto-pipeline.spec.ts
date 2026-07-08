import { expect, test } from "@playwright/test";

// AAP 真实浏览器 UI E2E：素材页视频/图片 Tab + 全库处理状态 + 一键补齐 + 导航精简。
// 前置：ci_auto_pipeline_e2e.py --mode full 已运行（栈开自动分析，库里有素材）。

test.describe.serial("AAP 素材页与自动化 UI", () => {
  test("类型 Tab / 处理状态 / 一键补齐 / 导航精简", async ({ page }) => {
    await page.goto("/assets");
    // 全库处理状态条（含自动分析徽标——CI 栈开了开关）
    await expect(page.getByTestId("processing-overview")).toBeVisible();
    await expect(page.getByTestId("auto-badge")).toBeVisible();
    // 视频 | 图片 Tab 切换
    await expect(page.getByTestId("kind-tab-video")).toBeVisible();
    await page.getByTestId("kind-tab-image").click();
    await expect(page.getByTestId("kind-tab-image")).toHaveAttribute(
      "aria-selected",
      "true",
    );
    await page.getByTestId("kind-tab-video").click();
    // 一键补齐分析按钮存在（视频 Tab）
    await expect(page.getByTestId("batch-analyze-btn")).toBeVisible();
    // 导航「更多」下拉可打开（overflow 裁剪修复），且工程页已下架。
    // P2b 起「更多」收纳工作流页（脚本剪辑/导出/收藏），产品入口升为主导航。
    await page.getByRole("button", { name: "更多", exact: true }).click();
    await expect(page.getByRole("menuitem", { name: "脚本剪辑" })).toBeVisible();
    await expect(page.getByRole("menuitem", { name: "导出" })).toBeVisible();
    await expect(
      page.getByRole("menuitem", { name: "视觉识别实验" }),
    ).toHaveCount(0);
    await expect(
      page.getByRole("menuitem", { name: "历史使用证据" }),
    ).toHaveCount(0);
    await page.keyboard.press("Escape");
    // 产品主入口在主导航
    await expect(page.getByTestId("nav-products-hub")).toBeVisible();
    console.log("AAP_UI_E2E_OK");
  });

  test("OBS 链路诊断：素材详情抽屉展开六环节诊断", async ({ page }) => {
    await page.goto("/assets");
    await page.getByRole("button", { name: "查看详情" }).first().click();
    // 默认折叠；展开后按服务端权威判定渲染六环节
    await page.getByTestId("asset-trace-toggle").click();
    await expect(page.getByTestId("asset-trace-stages")).toBeVisible();
    for (const stage of ["scan", "derive", "ai", "review", "document", "embedding"]) {
      await expect(page.getByTestId(`trace-stage-${stage}`)).toBeVisible();
    }
    console.log("OBS_UI_TRACE_OK");
  });

  test("@persist 重启后处理状态与 Tab 保持可用", async ({ page }) => {
    await page.goto("/assets");
    await expect(page.getByTestId("processing-overview")).toBeVisible();
    await expect(page.getByTestId("kind-tab-image")).toBeVisible();
    console.log("AAP_UI_PERSIST_OK");
  });
});
