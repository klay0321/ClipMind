import { expect, test, type APIRequestContext } from "@playwright/test";

// PR-C Gate B 真实浏览器 UI E2E：历史使用证据中心（/usage-evidence）+ Asset 弱证据面板。
// 前置：docker compose 全栈已起，且 ci_pr_c_b_legacy_e2e.py --mode full 已运行
// （栈内存在 PRCB-E2E 规则两条、A=accepted / B=rejected 证据、A 有 confirmed usage）。
// 冻结语义验证：固定警示文案、弱证据绝不显示"已使用 N 次"、预览先于导入、
// 审核动作真实生效；@persist 重启后规则/证据/派生状态仍在。

const API = process.env.API_BASE || "http://localhost:8000";

async function apiJson(request: APIRequestContext, path: string): Promise<unknown> {
  const res = await request.get(`${API}${path}`);
  if (!res.ok()) throw new Error(`GET ${path} -> ${res.status()}`);
  return res.json();
}

async function findAsset(request: APIRequestContext, prefix: string): Promise<number | null> {
  const data = (await apiJson(
    request,
    `/api/assets?page=1&page_size=50&q=${encodeURIComponent(prefix)}`,
  )) as { items: { id: number; filename: string }[] };
  const hit = data.items.find((a) => a.filename.startsWith(prefix));
  return hit?.id ?? null;
}

async function findSeedRule(
  request: APIRequestContext,
): Promise<{ id: number; name: string } | null> {
  const data = (await apiJson(request, "/api/legacy-usage-rules")) as {
    items: { id: number; name: string; pattern: string }[];
  };
  const hit = data.items.find((r) => r.name.startsWith("PRCB-E2E-目录标记"));
  return hit ?? null;
}

async function evidenceIdFor(
  request: APIRequestContext,
  assetId: number,
): Promise<number | null> {
  const data = (await apiJson(
    request,
    `/api/legacy-usage-evidence?page=1&page_size=20&asset_id=${assetId}`,
  )) as { items: { id: number; review_status: string }[] };
  return data.items[0]?.id ?? null;
}

test.describe.serial("PR-C Gate B 历史使用证据 UI", () => {
  test("规则管理：受控规则可见 + 新建白名单规则", async ({ page, request }) => {
    const seedRule = await findSeedRule(request);
    test.skip(seedRule == null, "缺少 PRCB-E2E 播种数据（先运行 API E2E full）");

    await page.goto("/usage-evidence");
    await expect(page.getByRole("heading", { name: "历史使用证据" })).toBeVisible();
    await page.getByTestId("tab-rules").click();
    await expect(page.getByTestId(`rule-row-${seedRule!.id}`)).toBeVisible();
    await expect(page.getByText("不支持自由正则表达式")).toBeVisible();

    // 新建规则：只有白名单下拉，无正则输入
    const uiPattern = `ui-marker-${Date.now()}`;
    await page.getByTestId("create-rule-button").click();
    await page.getByTestId("rule-name-input").fill(`PRCB-E2E-UI规则-${uiPattern}`);
    await page.getByTestId("rule-target-select").selectOption("filename");
    await page.getByTestId("rule-operator-select").selectOption("contains");
    await page.getByTestId("rule-pattern-input").fill(uiPattern);
    await page.getByTestId("rule-form-submit").click();
    await expect(page.getByTestId("rules-table")).toContainText(uiPattern);
    console.log("PR_C_B_UI_RULES_OK");
  });

  test("导入任务：只读预览 → 固定警示 → 正式导入", async ({ page, request }) => {
    const seedRule = await findSeedRule(request);
    test.skip(seedRule == null, "缺少 PRCB-E2E 播种数据");

    await page.goto("/usage-evidence");
    await page.getByTestId("tab-imports").click();
    await page.getByTestId("open-preview-button").click();
    // 只勾选播种目录规则（tag 隔离，不误伤其他数据）
    await page.getByTestId(`preview-rule-${seedRule!.id}`).check();
    await page.getByTestId("run-preview-button").click();
    await expect(page.getByTestId("preview-result")).toBeVisible();
    await expect(page.getByTestId("import-warning")).toContainText(
      "本操作只创建历史使用证据，不会修改文件、不会创建正式使用次数、不会绑定最终成片",
    );
    await page.getByTestId("confirm-import-button").click();
    // 运行列表出现新任务并最终完成（幂等：existing 而非新建）
    await expect(page.getByTestId("import-runs-table")).toBeVisible();
    await expect(
      page.getByTestId("import-runs-table").locator("tr", { hasText: "已完成" }).first(),
    ).toBeVisible({ timeout: 60_000 });
    console.log("PR_C_B_UI_IMPORT_OK");
  });

  test("审核：重置 → 待审核（固定警示）→ 接受 → 已审核", async ({ page, request }) => {
    const assetB = await findAsset(request, "PRCB-E2E-b-");
    test.skip(assetB == null, "缺少 PRCB-E2E 播种数据");
    const eid = await evidenceIdFor(request, assetB!);
    test.skip(eid == null, "缺少 B 证据");

    await page.goto("/usage-evidence");
    // B 在已审核（rejected）列表 → 重置回待审
    await page.getByTestId("tab-reviewed").click();
    await page.getByTestId("reviewed-filter").selectOption("rejected");
    await expect(page.getByTestId(`evidence-row-${eid}`)).toBeVisible();
    await page.getByTestId(`reset-evidence-${eid}`).click();
    await expect(page.getByTestId(`evidence-row-${eid}`)).toBeHidden();

    // 待审核：固定接受警示 + 单条接受
    await page.getByTestId("tab-pending").click();
    await expect(page.getByTestId("accept-warning")).toContainText(
      "接受历史证据不等于确认使用次数，也不等于确认对应成片或具体镜头",
    );
    await expect(page.getByTestId(`evidence-row-${eid}`)).toBeVisible();
    await page.getByTestId(`accept-evidence-${eid}`).click();
    await expect(page.getByTestId(`evidence-row-${eid}`)).toBeHidden();

    // 已审核（accepted）出现
    await page.getByTestId("tab-reviewed").click();
    await page.getByTestId("reviewed-filter").selectOption("accepted");
    await expect(page.getByTestId(`evidence-row-${eid}`)).toBeVisible();
    console.log("PR_C_B_UI_REVIEW_OK");
  });

  test("Asset 详情弱证据面板：历史上用过（次数未知），绝不显示已使用 N 次", async ({
    page,
    request,
  }) => {
    const assetA = await findAsset(request, "PRCB-E2E-a-");
    test.skip(assetA == null, "缺少 PRCB-E2E 播种数据");

    await page.goto("/assets");
    await page.getByLabel("搜索文件名").fill("PRCB-E2E-a-");
    const row = page.locator("tbody tr", { hasText: "PRCB-E2E-a-" }).first();
    await expect(row).toBeVisible();
    await row.getByLabel(/更多操作/).click();
    await page.getByText("查看详情").click();

    const panel = page.getByTestId("asset-legacy-panel");
    await expect(panel).toBeVisible();
    await expect(page.getByTestId("asset-legacy-state")).toContainText(
      "历史上用过（次数未知）",
    );
    await expect(panel).toContainText("不计入正式使用统计");
    // 弱证据绝不显示为确认次数
    await expect(panel).not.toContainText(/已使用 \d+ 次/);
    console.log("PR_C_B_UI_E2E_OK");
  });

  test("@persist 重启后规则/证据/派生状态仍在", async ({ page, request }) => {
    const seedRule = await findSeedRule(request);
    test.skip(seedRule == null, "缺少 PRCB-E2E 播种数据");

    await page.goto("/usage-evidence");
    await page.getByTestId("tab-rules").click();
    await expect(page.getByTestId(`rule-row-${seedRule!.id}`)).toBeVisible();

    await page.getByTestId("tab-reviewed").click();
    await page.getByTestId("reviewed-filter").selectOption("accepted");
    await expect(page.getByTestId("evidence-table")).toBeVisible();
    const acceptedRows = page.getByTestId(/evidence-row-/);
    await expect(acceptedRows.first()).toBeVisible();

    const assetA = await findAsset(request, "PRCB-E2E-a-");
    if (assetA != null) {
      const summary = (await apiJson(request, `/api/assets/${assetA}/usage-summary`)) as {
        legacy_usage_state: string;
        confirmed_usage_count: number;
      };
      expect(summary.legacy_usage_state).toBe("legacy_used_unknown");
      expect(summary.confirmed_usage_count).toBe(1);
    }
    console.log("PR_C_B_UI_PERSIST_OK");
  });
});
