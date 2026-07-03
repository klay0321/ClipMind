import { expect, test, type APIRequestContext } from "@playwright/test";

// PR-D 真实浏览器 UI E2E：统一使用记录中心（/usage-review）。
// 前置：docker compose 全栈已起，且 ci_pr_d_usage_review_e2e.py --mode seed-ui 已运行
// （栈内存在 PRD-E2E：1 条 proposed usage + 2 条 pending evidence + 1 条 confirmed）。
// 冻结语义验证：固定双提示、两类记录并列且标签明显不同、混选禁用批量、
// typed 批量 + 二次确认、clue 补录不默认选 Shot 不自动 confirmed；@persist 重启后保持。

const API = process.env.API_BASE || "http://localhost:8000";

async function apiJson(request: APIRequestContext, path: string): Promise<unknown> {
  const res = await request.get(`${API}${path}`);
  if (!res.ok()) throw new Error(`GET ${path} -> ${res.status()}`);
  return res.json();
}

interface SeedItems {
  proposed: { item_id: number } | null;
  pending: { item_id: number } | null;
}

async function findSeed(request: APIRequestContext): Promise<SeedItems> {
  const data = (await apiJson(
    request,
    "/api/usage-review/items?review_group=needs_review&q=PRD-E2E&page=1&page_size=50",
  )) as { items: { item_type: string; item_id: number }[] };
  return {
    proposed:
      data.items.find((i) => i.item_type === "final_video_usage") ?? null,
    pending:
      data.items.find((i) => i.item_type === "legacy_usage_evidence") ?? null,
  };
}

test.describe.serial("PR-D 统一使用记录中心 UI", () => {
  test("固定双提示 + 总览分离卡片 + 待审核两类并列", async ({ page, request }) => {
    const seed = await findSeed(request);
    test.skip(seed.proposed == null || seed.pending == null, "缺少 PRD-E2E 播种数据");

    await page.goto("/usage-review");
    await expect(page.getByTestId("formal-count-notice")).toContainText(
      "正式使用次数只来自已确认的成片与镜头血缘",
    );
    await expect(page.getByTestId("legacy-meaning-notice")).toContainText(
      "历史路径证据仅表示",
    );

    // 总览：分离卡片、无混合总数
    await page.getByTestId("tab-overview").click();
    await expect(page.getByTestId("card-confirmed")).toBeVisible();
    await expect(page.getByTestId("card-legacy-pending")).toBeVisible();
    await expect(page.locator("text=总使用次数")).toHaveCount(0);

    // 待审核：两类行并列，类型标签不同
    await page.getByTestId("tab-pending").click();
    const formalRow = page.getByTestId(
      `review-row-final_video_usage-${seed.proposed!.item_id}`,
    );
    const legacyRow = page.getByTestId(
      `review-row-legacy_usage_evidence-${seed.pending!.item_id}`,
    );
    await expect(formalRow).toBeVisible();
    await expect(formalRow).toContainText("正式血缘候选");
    await expect(legacyRow).toBeVisible();
    await expect(legacyRow).toContainText("历史弱证据");
    console.log("PR_D_UI_READ_MODEL_OK");
  });

  test("混选禁用批量并说明原因", async ({ page, request }) => {
    const seed = await findSeed(request);
    test.skip(seed.proposed == null || seed.pending == null, "缺少播种数据");
    await page.goto("/usage-review");
    await page
      .getByTestId(`select-final_video_usage-${seed.proposed!.item_id}`)
      .check();
    await page
      .getByTestId(`select-legacy_usage_evidence-${seed.pending!.item_id}`)
      .check();
    await expect(page.getByTestId("mixed-type-warning")).toContainText(
      "请分开批量处理",
    );
    await expect(page.getByTestId("bulk-confirm")).toHaveCount(0);
    console.log("PR_D_UI_MIXED_GUARD_OK");
  });

  test("legacy 批量接受（二次确认）→ confirmed 口径不变", async ({ page, request }) => {
    const seed = await findSeed(request);
    test.skip(seed.pending == null, "缺少播种数据");
    const summaryBefore = (await apiJson(request, "/api/usage-review/summary")) as {
      formal: { confirmed: number };
    };

    await page.goto("/usage-review");
    await page
      .getByTestId(`select-legacy_usage_evidence-${seed.pending!.item_id}`)
      .check();
    await page.getByTestId("bulk-accept").click();
    await page.getByRole("button", { name: "确认执行" }).click();
    await expect(page.getByTestId("bulk-result")).toContainText("成功 1");

    const summaryAfter = (await apiJson(request, "/api/usage-review/summary")) as {
      formal: { confirmed: number };
    };
    expect(summaryAfter.formal.confirmed).toBe(summaryBefore.formal.confirmed);
    console.log("PR_D_UI_LEGACY_BULK_OK");
  });

  test("formal 单条确认 + 详情事件时间线", async ({ page, request }) => {
    const seed = await findSeed(request);
    test.skip(seed.proposed == null, "缺少播种数据");
    const uid = seed.proposed!.item_id;

    await page.goto("/usage-review");
    await page.getByTestId(`detail-final_video_usage-${uid}`).click();
    await expect(page.getByTestId("review-detail")).toBeVisible();
    await expect(page.getByTestId("detail-events")).toContainText("人工添加候选");
    await page.keyboard.press("Escape");

    await page.getByTestId(`action-confirm-final_video_usage-${uid}`).click();
    await expect(
      page.getByTestId(`review-row-final_video_usage-${uid}`),
    ).toBeHidden();
    console.log("PR_D_UI_FORMAL_REVIEW_OK");
  });

  test("clue 补录：不默认选 Shot、创建 proposed 后需再次确认", async ({
    page,
    request,
  }) => {
    // 用挂在有镜头素材 A 上的证据（seed-ui 专门产出；无镜头素材不能补录）
    const data = (await apiJson(
      request,
      "/api/usage-review/items?item_type=legacy_usage_evidence&q=PRD-E2E-a-&page=1&page_size=10",
    )) as { items: { item_id: number }[] };
    test.skip(data.items.length === 0, "缺少 A 证据");
    const eid = data.items[0].item_id;

    await page.goto("/usage-review");
    await page.getByTestId("tab-legacy").click();
    await page.getByTestId(`clue-${eid}`).click();
    const submit = page.getByTestId("clue-submit");
    await expect(submit).toBeDisabled(); // 未人工选择前禁用
    // 人工选成片
    await page.getByTestId("clue-fv-search").fill("PRD-E2E");
    await page.locator('[data-testid^="clue-fv-option-"]').first().click();
    await expect(submit).toBeDisabled(); // 仍未选 Shot（绝不默认）
    // 选最后一个镜头（前两个已被 seed 的 usage 占用；且验证非默认选择）
    await page.locator('[data-testid^="clue-shot-"]').last().click();
    await expect(submit).toBeEnabled();
    await submit.click();
    await expect(page.getByTestId("clue-created")).toContainText(
      "尚未计入正式使用次数",
    );
    await page.getByTestId("clue-done").click();
    console.log("PR_D_UI_CLUE_OK");
    console.log("PR_D_UI_E2E_OK");
  });

  test("@persist 重启后中心状态保持", async ({ page, request }) => {
    await page.goto("/usage-review");
    await expect(page.getByTestId("formal-count-notice")).toBeVisible();
    await page.getByTestId("tab-processed").click();
    await expect(page.getByTestId("processed-table")).toBeVisible();
    const rows = page.getByTestId(/review-row-/);
    await expect(rows.first()).toBeVisible();
    const summary = (await apiJson(request, "/api/usage-review/summary")) as {
      formal: { confirmed: number };
      legacy: { accepted: number };
    };
    expect(summary.formal.confirmed).toBeGreaterThanOrEqual(1);
    expect(summary.legacy.accepted).toBeGreaterThanOrEqual(1);
    console.log("PR_D_UI_PERSIST_OK");
  });
});
