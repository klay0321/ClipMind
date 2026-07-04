import { expect, test, type APIRequestContext } from "@playwright/test";
import { deflateSync } from "node:zlib";

// PR-F 真实浏览器 UI E2E：产品视觉识别实验（/product-visual-experiments）。
// 前置：栈 VISUAL_RECOGNITION_ENABLED=true + VISUAL_EMBEDDING_PROVIDER=fake，
// 且 ci_pr_f_visual_e2e.py --mode full 已运行（PRF-E2E 产品/参考图/confusion 在库）。
// 冻结语义：固定实验提示、状态如实显示 fake provider、coverage 资格、
// Top-K 与解释、ambiguous 混淆警告、未自动写产品；@persist 重启后保持。

const API = process.env.API_BASE || "http://localhost:8000";

function crc32(buf: Buffer): number {
  let c: number;
  const table: number[] = [];
  for (let n = 0; n < 256; n++) {
    c = n;
    for (let k = 0; k < 8; k++) c = c & 1 ? 0xedb88320 ^ (c >>> 1) : c >>> 1;
    table[n] = c >>> 0;
  }
  let crc = 0xffffffff;
  for (const b of buf) crc = table[(crc ^ b) & 0xff] ^ (crc >>> 8);
  return (crc ^ 0xffffffff) >>> 0;
}

/** 合法 1×1 PNG + 尾部 FAKE:<token>: 标记（与 API E2E 同一约定）。 */
function makePng(token: string): Buffer {
  const chunk = (type: string, data: Buffer) => {
    const t = Buffer.from(type, "ascii");
    const len = Buffer.alloc(4);
    len.writeUInt32BE(data.length);
    const crc = Buffer.alloc(4);
    crc.writeUInt32BE(crc32(Buffer.concat([t, data])));
    return Buffer.concat([len, t, data, crc]);
  };
  const sig = Buffer.from([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a]);
  const ihdr = Buffer.alloc(13);
  ihdr.writeUInt32BE(1, 0);
  ihdr.writeUInt32BE(1, 4);
  ihdr[8] = 8;
  ihdr[9] = 2;
  const idat = deflateSync(Buffer.from([0, 120, 120, 120]));
  return Buffer.concat([
    sig,
    chunk("IHDR", ihdr),
    chunk("IDAT", idat),
    chunk("IEND", Buffer.alloc(0)),
    Buffer.from(`FAKE:${token}:ui`, "ascii"),
  ]);
}

/** 从 PRF-E2E family code 提取 tag（约定 PRF-E2E-A-<tag>）。 */
async function findPrfTag(request: APIRequestContext): Promise<string | null> {
  const res = await request.get(`${API}/api/product-families?page=1&page_size=100`);
  if (!res.ok()) return null;
  const body = (await res.json()) as { items: { code: string }[] };
  const fam = body.items.find((i) => i.code.startsWith("PRF-E2E-A-"));
  return fam ? fam.code.split("PRF-E2E-A-")[1] : null;
}

test.describe.serial("PR-F 产品视觉识别实验 UI", () => {
  test("状态/覆盖/上传候选/混淆警告/零自动写", async ({ page, request }) => {
    const tag = await findPrfTag(request);
    test.skip(tag == null, "缺少 PRF-E2E 播种数据（先跑 API E2E full）");

    await page.goto("/product-visual-experiments");
    // 固定实验提示（冻结文案）
    await expect(page.getByTestId("visual-experimental-notice")).toContainText(
      "这是实验性视觉候选，不会自动修改产品归属。候选结果必须由人工核对。",
    );
    // 状态卡：如实显示 fake provider（绝不冒充真实模型）
    await expect(page.getByTestId("visual-enabled")).toContainText("已开启");
    await expect(page.getByTestId("visual-provider")).toContainText("fake");
    // coverage：PRF 产品 A 合格且合格图数 4
    await expect(page.getByTestId("visual-coverage-card")).toContainText("参考图覆盖");
    const covRes = await request.get(
      `${API}/api/product-visual-experiments/reference-coverage`,
    );
    const cov = (await covRes.json()) as {
      items: { family_code: string; eligible: boolean; reference_count: number }[];
    };
    const famA = cov.items.find((i) => i.family_code === `PRF-E2E-A-${tag}`);
    expect(famA?.eligible).toBe(true);
    expect(famA?.reference_count).toBe(4);

    // 零自动写基线：asset_product 数量
    const beforeRes = await request.get(`${API}/api/products?page=1&page_size=1`);
    const beforeTotal = beforeRes.ok()
      ? ((await beforeRes.json()) as { total?: number }).total ?? null
      : null;

    // 上传候选实验：C 族 token → candidate；A 族 token → ambiguous + 混淆警告
    await page
      .getByTestId("visual-upload-input")
      .setInputFiles({ name: "q.png", mimeType: "image/png", buffer: makePng(`pc${tag}`) });
    await page.getByTestId("visual-run-upload").click();
    await expect(page.getByTestId("visual-candidate-result")).toBeVisible();
    await expect(page.getByTestId("visual-decision")).toContainText("候选");
    await expect(
      page.locator('[data-testid^="visual-candidate-"]').first(),
    ).toContainText("score=");

    await page
      .getByTestId("visual-upload-input")
      .setInputFiles({ name: "q2.png", mimeType: "image/png", buffer: makePng(`pa${tag}`) });
    await page.getByTestId("visual-run-upload").click();
    await expect(page.getByTestId("visual-decision")).toContainText("歧义");
    await expect(page.getByTestId("visual-confusion-warning")).toContainText("区分特征");
    await expect(page.getByTestId("visual-confusion-warning")).toContainText("接口位置");

    // 未自动写产品（products total 不变）
    if (beforeTotal != null) {
      const afterRes = await request.get(`${API}/api/products?page=1&page_size=1`);
      const afterTotal = ((await afterRes.json()) as { total?: number }).total ?? null;
      expect(afterTotal).toBe(beforeTotal);
    }
    console.log("PR_F_UI_E2E_OK");
  });

  test("@persist 重启后状态与候选保持", async ({ page, request }) => {
    const tag = await findPrfTag(request);
    test.skip(tag == null, "缺少 PRF-E2E 播种数据");
    await page.goto("/product-visual-experiments");
    await expect(page.getByTestId("visual-enabled")).toContainText("已开启");
    await expect(page.getByTestId("visual-provider")).toContainText("fake");
    await page
      .getByTestId("visual-upload-input")
      .setInputFiles({ name: "q.png", mimeType: "image/png", buffer: makePng(`pc${tag}`) });
    await page.getByTestId("visual-run-upload").click();
    await expect(page.getByTestId("visual-decision")).toContainText("候选");
    console.log("PR_F_UI_PERSIST_OK");
  });
});
