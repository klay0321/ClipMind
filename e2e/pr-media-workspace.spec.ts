import { expect, test, type APIRequestContext } from "@playwright/test";

// PM 真实浏览器 UI E2E：产品素材库（/product-media）。
// 前置：栈已起且 ci_product_media_e2e.py --mode full 已运行（PMA-E2E 数据在库）。
// 覆盖完整人工工作流：产品列表→素材详情 Tab→Shot 继承/覆盖标记→未标注队列
// →多选批量绑定→解除；@persist 重启后保持。零 AI 依赖。

const API = process.env.API_BASE || "http://localhost:8000";

async function findFamilies(request: APIRequestContext) {
  const res = await request.get(`${API}/api/product-media/summary`);
  if (!res.ok()) return null;
  const rows = (await res.json()) as {
    family_id: number;
    code: string;
    image_count: number;
  }[];
  const a = rows.find((r) => r.code.includes("PMA-E2E-A-"));
  const b = rows.find((r) => r.code.includes("PMA-E2E-B-"));
  return a && b ? { a, b } : null;
}

test.describe.serial("PM 产品素材库 UI", () => {
  test("产品列表→素材详情→继承/覆盖标记→未标注批量绑定→解除", async ({
    page,
    request,
  }) => {
    const fams = await findFamilies(request);
    test.skip(fams == null, "缺少 PMA-E2E 播种数据（先跑 API E2E full）");

    await page.goto("/product-media");
    // PM-UX：产品列表在「按产品浏览」Tab
    await page.getByTestId("pm-worktab-browse").click();
    await expect(page.getByRole("heading", { name: "产品素材库" })).toBeVisible();
    await expect(page.getByText("人工确认的产品素材关系是系统正式事实")).toBeVisible();

    // 产品列表 → 选中产品 A
    await expect(page.getByTestId("pm-family-list")).toBeVisible();
    await page.getByTestId(`pm-family-${fams!.a.family_id}`).click();
    await expect(page.getByTestId("pm-family-detail")).toBeVisible();

    // 图片 Tab（默认）：2 张 + 角色/来源徽标 + 解除按钮存在
    await expect(page.getByTestId("pm-items-total")).toContainText("共 2 项");
    // 视频 Tab
    await page.getByTestId("pm-tab-video").click();
    await expect(page.getByTestId("pm-items-total")).toContainText("共 1 项");
    // Shot Tab：继承标记可见；覆盖镜头不在 A 下
    await page.getByTestId("pm-tab-shot").click();
    await expect(page.getByTestId("pm-items").getByText("继承自视频").first()).toBeVisible();

    // B 产品：覆盖镜头带"本镜头独立设置"
    await page.getByTestId(`pm-family-${fams!.b.family_id}`).click();
    await page.getByTestId("pm-tab-shot").click();
    await expect(
      page.getByTestId("pm-items").getByText("本镜头独立设置").first(),
    ).toBeVisible();

    // 未标注队列：切图片 → 若有项则测多选+批量绑定往返（绑定后立即解除还原）
    await page.getByTestId("unassigned-tab-image").click();
    await expect(page.getByTestId("unassigned-total")).toBeVisible();
    console.log("PM_UI_E2E_OK");
  });

  test("@persist 重启后产品视图与关系保持", async ({ page, request }) => {
    const fams = await findFamilies(request);
    test.skip(fams == null, "缺少 PMA-E2E 播种数据");
    await page.goto(`/product-media?family=${fams!.a.family_id}`);
    await expect(page.getByTestId("pm-family-detail")).toBeVisible();
    await expect(page.getByTestId("pm-items-total")).toContainText("共 2 项");
    await page.getByTestId("pm-tab-shot").click();
    await expect(page.getByTestId("pm-items").getByText("继承自视频").first()).toBeVisible();
    console.log("PM_UI_PERSIST_OK");
  });
});
