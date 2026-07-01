import { deflateSync } from "node:zlib";

import { expect, test, type APIRequestContext, type Page } from "@playwright/test";

// PR-A2 Gate A 真实浏览器 UI E2E（驱动真实 /products + 真实 API + Postgres）。
// 覆盖：动态属性定义与填值、参考图上传/角度/主图、诚实声明、刷新与重启持久化。
// 全部中性随机名与**内存合成 PNG**（不使用公司素材）。

const API = process.env.API_BASE || "http://localhost:8000";
const SHOTS = process.env.SHOTS_DIR || "e2e/.artifacts";

function rnd(): string {
  return Math.random().toString(36).slice(2, 8);
}

// 生成有效 1×1 RGB PNG（不同颜色→不同 sha256），Node zlib，无外部依赖。
function png(r: number, g: number, b: number): Buffer {
  const u32 = (n: number) => Buffer.from([(n >>> 24) & 255, (n >>> 16) & 255, (n >>> 8) & 255, n & 255]);
  const crc = (buf: Buffer) => {
    let c = ~0;
    for (const byte of buf) {
      c ^= byte;
      for (let i = 0; i < 8; i++) c = (c >>> 1) ^ (0xedb88320 & -(c & 1));
    }
    return (~c) >>> 0;
  };
  const chunk = (type: string, data: Buffer) => {
    const t = Buffer.concat([Buffer.from(type, "ascii"), data]);
    return Buffer.concat([u32(data.length), t, u32(crc(t))]);
  };
  const sig = Buffer.from([137, 80, 78, 71, 13, 10, 26, 10]);
  const ihdr = chunk("IHDR", Buffer.concat([u32(1), u32(1), Buffer.from([8, 2, 0, 0, 0])]));
  const idat = chunk("IDAT", deflateSync(Buffer.from([0, r, g, b])));
  return Buffer.concat([sig, ihdr, idat, chunk("IEND", Buffer.alloc(0))]);
}

async function activeFamily(request: APIRequestContext, tag: string): Promise<number> {
  const cat = await (await request.post(`${API}/api/product-categories`, {
    data: { name_zh: `${tag}类` },
  })).json();
  await request.post(`${API}/api/product-categories/${cat.id}/status`, { data: { status: "active" } });
  const fam = await (await request.post(`${API}/api/product-families`, {
    data: { name_zh: `${tag}产品`, category_id: cat.id },
  })).json();
  await request.post(`${API}/api/product-families/${fam.id}/status`, { data: { status: "active" } });
  return fam.id;
}

async function selectFamily(page: Page, famName: string): Promise<void> {
  await page.goto("/products");
  await expect(page.getByRole("heading", { name: "产品目录" })).toBeVisible();
  await page.getByTestId("tree-panel").getByText(famName).first().click();
  await expect(page.getByTestId("detail-name")).toHaveText(famName);
}

test("PR-A2 属性+参考图：定义/填值/上传/角度/主图/诚实声明/刷新持久化", async ({ page, request }) => {
  const tag = `A2UI${rnd()}`;
  const famName = `${tag}产品`;
  await activeFamily(request, tag);
  await selectFamily(page, famName);

  // 1) 产品属性 Tab：新建文本属性定义 + 填值
  await page.getByTestId("detail-tab-attributes").click();
  await expect(page.getByTestId("attributes-tab")).toBeVisible();
  await page.getByTestId("empty-create-attr-def").click();
  await expect(page.getByTestId("attr-def-dialog")).toBeVisible();
  await page.getByTestId("attr-def-name").fill(`${tag}属性`);
  await page.getByTestId("attr-def-type").selectOption("text");
  await page.getByTestId("submit-attr-def").click();
  // 定义出现后，填该属性值并保存
  const input = page.getByTestId("attributes-tab").locator('[data-testid^="attr-input-"]').first();
  await expect(input).toBeVisible();
  await input.fill("端到端值");
  await page.getByTestId("attributes-tab").locator('[data-testid^="attr-save-"]').first().click();
  // eslint-disable-next-line no-console
  console.log("PR_A2A_UI_ATTRIBUTE_OK");

  // 2) 参考图库 Tab：诚实声明 + 上传合成图 + 角度 + 主图
  await page.getByTestId("detail-tab-references").click();
  await expect(page.getByTestId("reference-gallery")).toBeVisible();
  await expect(page.getByTestId("ref-recognition-notice")).toContainText("自动产品识别尚未启用");

  await page.getByTestId("ref-file-input").setInputFiles({
    name: "a.png", mimeType: "image/png", buffer: png(200, 20, 20),
  });
  const card = page.getByTestId("ref-grid").locator('[data-testid^="ref-card-"]').first();
  await expect(card).toBeVisible({ timeout: 30_000 });
  // 改角度
  await page.getByTestId("ref-grid").locator('[data-testid^="ref-angle-"]').first().selectOption("back");
  // 设主图
  await page.getByTestId("ref-grid").locator('[data-testid^="ref-set-primary-"]').first().click();
  await expect(page.getByTestId("ref-grid").locator('[data-testid^="ref-primary-badge-"]').first()).toBeVisible();
  // 绝不显示虚假相似度/识别结果
  await expect(page.getByTestId("reference-gallery")).not.toContainText("相似度");
  await expect(page.getByTestId("reference-gallery")).not.toContainText("已识别");
  // eslint-disable-next-line no-console
  console.log("PR_A2A_UI_REFERENCE_OK");

  // 3) 刷新后属性值与参考图仍在
  await page.reload();
  await page.getByTestId("tree-panel").getByText(famName).first().click();
  await page.getByTestId("detail-tab-references").click();
  await expect(
    page.getByTestId("ref-grid").locator('[data-testid^="ref-card-"]').first(),
  ).toBeVisible();
  await page.getByTestId("detail-tab-attributes").click();
  await expect(
    page.getByTestId("attributes-tab").locator('[data-testid^="attr-input-"]').first(),
  ).toHaveValue("端到端值");

  await page.screenshot({ path: `${SHOTS}/pr-a2a.png` });
  // eslint-disable-next-line no-console
  console.log("PR_A2A_UI_E2E_OK");
});

test("@persist 重启后动态属性与参考图仍可用", async ({ page, request }) => {
  const tag = `A2PST${rnd()}`;
  const famName = `${tag}产品`;
  const fid = await activeFamily(request, tag);
  // 经 API 建属性定义+值+参考图（写入 DB/磁盘），重启的 web/api 应立即可读
  const def = await (await request.post(`${API}/api/product-attribute-definitions`, {
    data: { name_zh: `${tag}属性`, category_id: null, value_type: "text" },
  })).json();
  await request.put(`${API}/api/product-attribute-values`, {
    data: { definition_id: def.id, target_level: "family", target_id: fid, value: "重启值" },
  });
  await request.post(`${API}/api/product-reference-assets`, {
    multipart: {
      target_level: "family", target_id: String(fid), angle: "front",
      files: { name: "p.png", mimeType: "image/png", buffer: png(10, 200, 30) },
    },
  });

  await selectFamily(page, famName);
  await page.getByTestId("detail-tab-references").click();
  await expect(
    page.getByTestId("ref-grid").locator('[data-testid^="ref-card-"]').first(),
  ).toBeVisible();
  await page.getByTestId("detail-tab-attributes").click();
  await expect(
    page.getByTestId("attributes-tab").locator('[data-testid^="attr-input-"]').first(),
  ).toHaveValue("重启值");
  // eslint-disable-next-line no-console
  console.log("PR_A2A_UI_PERSIST_OK");
});
