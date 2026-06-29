import { expect, test } from "@playwright/test";

// 核心产品 UX E2E：跨页结构、导航、响应式无横向溢出、媒体兜底、重启持久化。
// 驱动真实 web 页面（与 search/script/projects/pr06b 互补）。截图落在 SHOTS_DIR。
const SHOTS = process.env.SHOTS_DIR || "e2e/.artifacts";

async function horizontalOverflow(page: import("@playwright/test").Page): Promise<number> {
  return page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
}

async function visibleBrokenImages(page: import("@playwright/test").Page): Promise<number> {
  return page.evaluate(
    () =>
      Array.from(document.images).filter(
        (i) => i.complete && i.naturalWidth === 0 && i.offsetParent !== null,
      ).length,
  );
}

test("素材管理：处理链总览，首屏不泄漏容器路径", async ({ page }) => {
  await page.goto("/assets");
  await expect(page.getByRole("heading", { name: "素材统一管理" })).toBeVisible();
  await expect(page.getByTestId("upload-btn")).toBeVisible();
  await expect(page.locator("body")).not.toContainText("/app/source");
  await page.screenshot({ path: `${SHOTS}/core-01-assets.png` });
  // eslint-disable-next-line no-console
  console.log("CORE_UX_ASSETS_E2E_OK");
});

test("AI 镜头拆解：完整度面板 + 真实筛选侧栏", async ({ page }) => {
  await page.goto("/shots");
  await expect(page.getByTestId("shot-completeness")).toBeVisible();
  await expect(page.getByTestId("ai-filters")).toBeVisible();
  await expect(page.getByTestId("filter-product")).toBeVisible();
  await page.screenshot({ path: `${SHOTS}/core-02-shots.png` });
  // eslint-disable-next-line no-console
  console.log("CORE_UX_SHOTS_E2E_OK");
});

test("画面描述匹配：左右工作台结构", async ({ page }) => {
  await page.goto("/search?mode=description");
  await expect(page.getByTestId("tab-description")).toHaveAttribute("aria-selected", "true");
  await expect(page.getByTestId("desc-input")).toBeVisible();
  await expect(page.getByTestId("desc-match")).toBeVisible();
  await page.screenshot({ path: `${SHOTS}/core-03-description-match.png` });
  // eslint-disable-next-line no-console
  console.log("CORE_UX_DESCRIPTION_MATCH_E2E_OK");
});

test("脚本剪辑：列表页 + 新建脚本 Modal", async ({ page }) => {
  await page.goto("/script");
  await expect(page.getByRole("heading", { name: "脚本匹配与剪辑清单" })).toBeVisible();
  await expect(page.getByTestId("script-new-btn")).toBeVisible();
  await page.getByTestId("script-new-btn").click();
  await expect(page.getByTestId("script-name")).toBeVisible();
  await page.keyboard.press("Escape");
  await page.screenshot({ path: `${SHOTS}/core-04-script.png` });
  // eslint-disable-next-line no-console
  console.log("CORE_UX_SCRIPT_E2E_OK");
});

test("辅助页面：产品库 / 项目 / 导出 / 收藏 可达且成形", async ({ page }) => {
  await page.goto("/products");
  await expect(page.getByRole("heading", { name: "产品库" })).toBeVisible();
  await expect(page.getByTestId("product-search")).toBeVisible();

  await page.goto("/projects");
  await expect(page.getByTestId("nav-projects")).toHaveAttribute("aria-current", "page");

  await page.goto("/exports");
  await expect(page.getByTestId("nav-exports")).toBeVisible();

  await page.goto("/favorites");
  await expect(page.getByTestId("favorites")).toBeVisible();
  await page.screenshot({ path: `${SHOTS}/core-05-favorites.png` });
  // eslint-disable-next-line no-console
  console.log("CORE_UX_AUXILIARY_PAGES_E2E_OK");
});

test("导航：主链路点击可跳转", async ({ page }) => {
  await page.goto("/assets");
  await page.getByTestId("nav-search").click();
  await expect(page).toHaveURL(/\/search/);
  await page.getByTestId("nav-script").click();
  await expect(page).toHaveURL(/\/script/);
  await page.getByTestId("nav-projects").click();
  await expect(page).toHaveURL(/\/projects/);
  await page.getByTestId("nav-exports").click();
  await expect(page).toHaveURL(/\/exports/);
  // eslint-disable-next-line no-console
  console.log("CORE_UX_NAV_E2E_OK");
});

test("响应式：1366/1440/1920/移动 各页无横向溢出", async ({ page }) => {
  const viewports = [
    { w: 1366, h: 768 },
    { w: 1440, h: 900 },
    { w: 1920, h: 1080 },
    { w: 390, h: 844 },
  ];
  const routes = ["/assets", "/shots", "/search", "/script", "/products"];
  for (const v of viewports) {
    await page.setViewportSize({ width: v.w, height: v.h });
    for (const r of routes) {
      await page.goto(r);
      await page.waitForLoadState("networkidle").catch(() => {});
      const overflow = await horizontalOverflow(page);
      expect(overflow, `${r} @ ${v.w}x${v.h} 横向溢出 ${overflow}px`).toBeLessThanOrEqual(4);
    }
  }
  await page.setViewportSize({ width: 1440, height: 900 });
  // eslint-disable-next-line no-console
  console.log("CORE_UX_RESPONSIVE_E2E_OK");
});

test("媒体兜底：无可见破图（加载失败回退占位）", async ({ page }) => {
  for (const r of ["/shots", "/favorites"]) {
    await page.goto(r);
    await page.waitForLoadState("networkidle").catch(() => {});
    const broken = await visibleBrokenImages(page);
    expect(broken, `${r} 存在 ${broken} 张可见破图`).toBe(0);
  }
  await page.screenshot({ path: `${SHOTS}/core-06-media.png` });
  // eslint-disable-next-line no-console
  console.log("CORE_UX_MEDIA_FALLBACK_E2E_OK");
});

test("@persist 重启后核心页面仍可用", async ({ page }) => {
  await page.goto("/assets");
  await expect(page.getByRole("heading", { name: "素材统一管理" })).toBeVisible();
  await page.goto("/script");
  await expect(page.getByRole("heading", { name: "脚本匹配与剪辑清单" })).toBeVisible();
  // eslint-disable-next-line no-console
  console.log("CORE_UX_PERSIST_OK");
});
