import { expect, test, type APIRequestContext, type Page } from "@playwright/test";

// PR-A1 通用产品目录 真实浏览器 UI E2E（驱动真实 web /products + 真实 API + Postgres）。
// 覆盖：四层创建/激活、别名、搜索、更名、旧名解析、归档/恢复、子级合并守卫、
// 跨 family 同 variant code、刷新持久化、无横向溢出、无固定 seed 产品。
// 全部使用中性随机名（非公司真实产品）。

const API = process.env.API_BASE || "http://localhost:8000";
const SHOTS = process.env.SHOTS_DIR || "e2e/.artifacts";

function rnd(): string {
  // 中性随机后缀；避免固定名导致跨运行冲突
  return Math.random().toString(36).slice(2, 8);
}

async function horizontalOverflow(page: Page): Promise<number> {
  return page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
}

async function createFamily(request: APIRequestContext, name: string): Promise<number> {
  const r = await request.post(`${API}/api/product-families`, { data: { name_zh: name } });
  expect(r.status(), await r.text()).toBe(201);
  return (await r.json()).id;
}

test("PR-A1 目录：四层创建/激活/别名/更名/旧名/归档恢复/子级合并守卫/跨family同码", async ({
  page,
  request,
}) => {
  const tag = `A1UI${rnd()}`;
  const catName = `${tag}类`;
  const famName = `${tag}产品`;
  const varName = `${tag}型号`;
  const skuName = `${tag}SKU`;
  const aliasName = `${tag}别名`;

  await page.goto("/products");
  await expect(page.getByRole("heading", { name: "产品目录" })).toBeVisible();

  // 无固定 seed：目录内容全部来自 API，不含硬编码占位产品名
  await expect(page.locator("body")).not.toContainText("示例产品");

  // 桌面宽度无横向溢出
  expect(await horizontalOverflow(page)).toBeLessThanOrEqual(4);

  // 1) 向导新建 分类→产品→型号→SKU→别名，保存并启用（激活 分类 + 产品）
  await page.getByTestId("open-create-wizard").click();
  await page.getByTestId("cat-mode-new").click();
  await page.getByTestId("wizard-new-category").fill(catName);
  await page.getByTestId("wizard-next-category").click();
  await page.getByTestId("wizard-family-name").fill(famName);
  await page.getByTestId("wizard-next-family").click();
  await page.getByTestId("wizard-variant-name").fill(varName);
  await page.getByTestId("wizard-next-variant").click();
  await page.getByTestId("wizard-sku-name").fill(skuName);
  await page.getByTestId("wizard-sku-code").fill(`${tag}-SK1`);
  await page.getByTestId("wizard-next-sku").click();
  await page.getByTestId("wizard-alias").fill(aliasName);
  await page.getByTestId("wizard-save-active").click();

  // 创建后自动选中 family，且为 active（分类链已激活）
  await expect(page.getByTestId("entity-detail")).toBeVisible();
  await expect(page.getByTestId("detail-name")).toHaveText(famName);
  await expect(
    page.getByTestId("entity-detail").getByTestId("catalog-status-active"),
  ).toBeVisible();

  // 2) 逐层激活 变体、SKU（四层统一生命周期；变体需 family active、SKU 需 variant active）
  await page.getByTestId("child-list").getByText(varName).click();
  await expect(page.getByTestId("detail-name")).toHaveText(varName);
  await page.getByTestId("status-to-active").click();
  await expect(
    page.getByTestId("entity-detail").getByTestId("catalog-status-active"),
  ).toBeVisible();

  await page.getByTestId("child-list").getByText(skuName).click();
  await expect(page.getByTestId("detail-name")).toHaveText(skuName);
  await page.getByTestId("status-to-active").click();
  await expect(
    page.getByTestId("entity-detail").getByTestId("catalog-status-active"),
  ).toBeVisible();
  // eslint-disable-next-line no-console
  console.log("PR_A1_UI_ALL_LEVEL_ACTIVATE_OK");

  // 3) 搜索命中新产品（名称/编码/别名走 API 检索）
  await page.getByTestId("catalog-search-input").fill(famName);
  await expect(page.getByTestId("catalog-search-results")).toBeVisible();
  await expect(page.getByTestId("catalog-search-results")).toContainText(famName);
  await page.getByTestId("catalog-search-input").fill("");

  // 4) 更名（不改编码），旧名经 resolve 仍指向该产品
  await page.getByTestId("tree-panel").getByText(famName).first().click();
  await expect(page.getByTestId("detail-name")).toHaveText(famName);
  await page.getByTestId("edit-node").click();
  const renamed = `${famName}改`;
  await page.getByTestId("rename-zh").fill(renamed);
  await page.getByTestId("save-rename").click();
  await expect(page.getByTestId("detail-name")).toHaveText(renamed);

  const rr = await request.get(
    `${API}/api/product-catalog/resolve?value=${encodeURIComponent(famName)}`,
  );
  expect(rr.ok()).toBeTruthy();
  const rb = await rr.json();
  expect(rb.status).toBe("resolved");
  expect(rb.canonical?.name_zh).toBe(renamed);
  // eslint-disable-next-line no-console
  console.log("PR_A1_UI_RENAME_OLDNAME_OK");

  // 5) 归档→只读→恢复
  await page.getByTestId("archive-node").click();
  await page.getByRole("button", { name: "确认归档" }).click();
  await expect(page.getByTestId("readonly-banner")).toBeVisible();
  await page.getByTestId("restore-node").click();
  await expect(page.getByTestId("readonly-banner")).toBeHidden();

  // 6) 子级合并守卫：family 仍有活跃变体 → 合并被拒（409），树与子级不变
  const targetName = `${tag}目标`;
  const targetId = await createFamily(request, targetName);
  await page.getByTestId("tree-panel").getByText(renamed).first().click();
  await page.getByTestId("open-merge").click();
  // 目标候选按已知 family id（value）选择，避免依赖后端生成的 code 文案
  await page.getByTestId("merge-target").selectOption(String(targetId));
  await page.getByTestId("submit-merge").click();
  await expect(page.getByTestId("catalog-error")).toContainText("变体");
  // 源产品未被合并（仍非 merged）：关闭对话框后详情仍为源产品
  await page.getByRole("button", { name: "取消" }).click();
  await expect(page.getByTestId("detail-name")).toHaveText(renamed);
  // eslint-disable-next-line no-console
  console.log("PR_A1_UI_CHILD_MERGE_GUARD_OK");

  // 7) 跨 family 同一 variant code 可复用（family 作用域唯一）——经真实 API 断言
  const fa = await createFamily(request, `${tag}FA`);
  const fb = await createFamily(request, `${tag}FB`);
  const va = await request.post(`${API}/api/product-variants`, {
    data: { family_id: fa, name_zh: `${tag}vA`, code: "standard" },
  });
  const vb = await request.post(`${API}/api/product-variants`, {
    data: { family_id: fb, name_zh: `${tag}vB`, code: "standard" },
  });
  expect(va.status()).toBe(201);
  expect(vb.status()).toBe(201);
  // 同 family 内重复则冲突
  const vdup = await request.post(`${API}/api/product-variants`, {
    data: { family_id: fa, name_zh: `${tag}vA2`, code: "STANDARD" },
  });
  expect(vdup.status()).toBe(409);
  // eslint-disable-next-line no-console
  console.log("PR_A1_UI_SCOPED_CODE_OK");

  // 8) 刷新持久化：重新加载后产品仍在树中、无横向溢出
  await page.reload();
  await expect(page.getByRole("heading", { name: "产品目录" })).toBeVisible();
  await expect(page.getByTestId("tree-panel").getByText(renamed).first()).toBeVisible();
  expect(await horizontalOverflow(page)).toBeLessThanOrEqual(4);

  await page.screenshot({ path: `${SHOTS}/pr-a1-catalog.png` });
  // eslint-disable-next-line no-console
  console.log("PR_A1_UI_E2E_OK");
});

test("@persist 重启后目录仍可用且新建产品可解析", async ({ page, request }) => {
  const tag = `A1PST${rnd()}`;
  const name = `${tag}产品`;
  // 经真实 API 新建（写入 Postgres），重启的 web/api 应立即可读
  await createFamily(request, name);

  await page.goto("/products");
  await expect(page.getByRole("heading", { name: "产品目录" })).toBeVisible();
  await expect(page.getByTestId("tree-panel").getByText(name).first()).toBeVisible();

  const rr = await request.get(
    `${API}/api/product-catalog/resolve?value=${encodeURIComponent(name)}`,
  );
  expect(rr.ok()).toBeTruthy();
  expect((await rr.json()).status).toBe("resolved");
  // eslint-disable-next-line no-console
  console.log("PR_A1_UI_PERSIST_OK");
});
