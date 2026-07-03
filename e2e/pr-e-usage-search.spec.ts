import { expect, test, type APIRequestContext, type Page } from "@playwright/test";

// PR-E 真实浏览器 UI E2E：使用感知检索与可解释排序（/search）。
// 前置：docker compose 全栈已起，且 ci_pr_e_usage_search_e2e.py --mode full 已运行
// （库内存在 PRE-E2E 数据 + "PRE-E2E-未使用优先-*" Saved Search）。
// 冻结语义验证：五档快捷模式、default 请求不携带 usage 字段（UI 侧 parity）、
// 非 default 重排 + 徽标 + 排序解释（绝不只显示推荐分）、only_never 无"正式使用"徽标、
// legacy 冻结文案不带数字、UI 保存/恢复 usage 条件；@persist 重启后保持。

const API = process.env.API_BASE || "http://localhost:8000";

async function findPreSaved(
  request: APIRequestContext,
): Promise<{ id: number; name: string } | null> {
  const res = await request.get(`${API}/api/saved-searches?page=1&page_size=100`);
  if (!res.ok()) return null;
  const body = (await res.json()) as { items: { id: number; name: string }[] };
  return body.items.find((i) => i.name.startsWith("PRE-E2E-")) ?? null;
}

/** 从真实 suggestions API 取一个可检索词（不硬编码任何真实业务词）。 */
async function pickTerm(request: APIRequestContext): Promise<string> {
  try {
    const res = await request.get(`${API}/api/search/suggestions?limit=20`);
    if (res.ok()) {
      const body = (await res.json()) as { items?: { value: string; type: string }[] };
      const items = body.items ?? [];
      const pref = items.find((i) => ["product", "scene", "action"].includes(i.type));
      if (pref) return pref.value;
      if (items[0]) return items[0].value;
    }
  } catch {
    /* 兜底 */
  }
  return "镜头";
}

/** 提交搜索并捕获发出的 /api/search/shots 请求体。 */
async function submitAndCapture(
  page: Page,
  action: () => Promise<void>,
): Promise<Record<string, unknown>> {
  const [req] = await Promise.all([
    page.waitForRequest(
      (r) => r.url().includes("/api/search/shots") && r.method() === "POST",
    ),
    action(),
  ]);
  return req.postDataJSON() as Record<string, unknown>;
}

test.describe.serial("PR-E 使用感知检索 UI", () => {
  test("五档快捷模式 + default 请求零 usage 字段 + 硬过滤徽标语义", async ({
    page,
    request,
  }) => {
    const term = await pickTerm(request);
    await page.goto("/search");
    await expect(page.getByRole("heading", { name: "智能匹配" })).toBeVisible();

    // 五档快捷模式渲染；default 默认选中
    for (const m of [
      "default",
      "prefer_unused",
      "only_never_confirmed",
      "exclude_high_frequency",
      "least_recently_used",
    ]) {
      await expect(page.getByTestId(`usage-mode-${m}`)).toBeVisible();
    }
    await expect(page.getByTestId("usage-mode-default")).toHaveAttribute(
      "aria-pressed",
      "true",
    );

    // default 提交：请求体必须不携带任何 usage 字段（UI 侧 parity 保证）
    await page.getByTestId("search-input").fill(term);
    const defaultBody = await submitAndCapture(page, () =>
      page.getByTestId("search-submit").click(),
    );
    expect(defaultBody).not.toHaveProperty("usage_mode");
    expect(defaultBody).not.toHaveProperty("usage_preset");
    expect(defaultBody).not.toHaveProperty("include_usage_explanation");
    await expect(page.getByTestId("results-meta")).toBeVisible();

    // 切"优先未使用"：立即重新提交且携带 usage_mode；结果卡出现使用徽标
    const preferBody = await submitAndCapture(page, () =>
      page.getByTestId("usage-mode-prefer_unused").click(),
    );
    expect(preferBody.usage_mode).toBe("prefer_unused");
    await expect(page.getByTestId("usage-mode-prefer_unused")).toHaveAttribute(
      "aria-pressed",
      "true",
    );
    await expect(page.getByTestId("results-meta")).toBeVisible();
    await expect(page.locator('[data-testid^="usage-badge-"]').first()).toBeVisible();

    // 切"只看从未正式使用"：结果绝不出现"正式使用 N 次"徽标
    const onlyBody = await submitAndCapture(page, () =>
      page.getByTestId("usage-mode-only_never_confirmed").click(),
    );
    expect(onlyBody.usage_mode).toBe("only_never_confirmed");
    await expect(page.getByTestId("results-meta")).toBeVisible();
    await expect(page.locator('[data-testid^="usage-badge-"]').first()).toBeVisible();
    await expect(page.getByTestId("usage-badge-confirmed")).toHaveCount(0);

    console.log("PR_E_UI_E2E_OK");
  });

  test("Saved Search 恢复 usage 条件 + 排序解释 + legacy 冻结文案", async ({
    page,
    request,
  }) => {
    const saved = await findPreSaved(request);
    test.skip(saved == null, "缺少 PRE-E2E Saved Search（先跑 API E2E full）");

    await page.goto("/search");
    await page.getByTestId("toggle-saved-search").click();
    await expect(page.getByTestId("saved-search-panel")).toBeVisible();
    await Promise.all([
      page.waitForRequest(
        (r) => r.url().includes("/api/search/shots") && r.method() === "POST",
      ),
      page.getByTestId(`run-saved-${saved!.id}`).click(),
    ]);
    // usage 条件从 Saved Search 恢复：模式 pill 选中
    await expect(page.getByTestId("usage-mode-prefer_unused")).toHaveAttribute(
      "aria-pressed",
      "true",
    );
    await expect(page.getByTestId("results-meta")).toBeVisible();

    // 排序解释：base 相关度 + 调整项 + 最终分数三段齐全（绝不只显示一个推荐分）
    const explain = page.getByTestId("usage-explanation").first();
    await expect(explain).toBeVisible();
    await expect(explain).toContainText("语义相关度");
    await expect(explain).toContainText("最终分数");

    // legacy 冻结文案：历史上可能使用过（次数未知），绝不带数字
    const legacyBadge = page.getByTestId("usage-badge-legacy").first();
    await expect(legacyBadge).toBeVisible();
    await expect(legacyBadge).toContainText("历史上可能使用过（次数未知）");
    expect(await legacyBadge.textContent()).not.toMatch(/\d/);

    // 高级筛选中的 usage 控件可见可交互
    await page.getByTestId("advanced-filters-toggle").click();
    await expect(page.getByTestId("usage-advanced-filters")).toBeVisible();
    await expect(page.getByTestId("usage-max-count")).toBeVisible();

    // UI 保存一份新的 usage 搜索（供 @persist 复核）
    const uiName = `PRE-UI-${Date.now()}`;
    await page.getByTestId("save-search").click();
    await page.locator("#saved-search-name").fill(uiName);
    await page.getByTestId("confirm-save-search").click();
    await expect(page.getByTestId("saved-search-list")).toContainText(uiName);

    console.log("PR_E_UI_EXPLANATION_OK");
  });

  test("@persist 重启后 Saved Search 的 usage 条件仍可恢复", async ({
    page,
    request,
  }) => {
    const saved = await findPreSaved(request);
    test.skip(saved == null, "缺少 PRE-E2E Saved Search");

    await page.goto("/search");
    await page.getByTestId("toggle-saved-search").click();
    const body = await submitAndCapture(page, () =>
      page.getByTestId(`run-saved-${saved!.id}`).click(),
    );
    expect(body.usage_mode).toBe("prefer_unused");
    expect(body.exclude_recently_used_days).toBe(60);
    await expect(page.getByTestId("usage-mode-prefer_unused")).toHaveAttribute(
      "aria-pressed",
      "true",
    );
    await expect(page.getByTestId("results-meta")).toBeVisible();
    console.log("PR_E_UI_PERSIST_OK");
  });
});
