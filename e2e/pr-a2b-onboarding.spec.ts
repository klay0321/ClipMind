import { expect, test, type APIRequestContext } from "@playwright/test";

// PR-A2 Gate B 真实浏览器 UI E2E：产品入驻治理。
// 创建产品 → 配置策略 → incomplete → 补属性/参考图 → complete → 提交 → 批准
// → 建混淆关系 → 查看变更历史 → 刷新 → （@persist 重启后）状态仍在。
// 全部中性随机名（非公司产品）；参考图为内存合成 PNG。

const API = process.env.API_BASE || "http://localhost:8000";

function rnd(): string {
  return Math.random().toString(36).slice(2, 8);
}

// 合成 1×1 PNG（不同颜色 → 不同 sha256）
function png(r: number, g: number, b: number): Buffer {
  const crcTable: number[] = [];
  for (let n = 0; n < 256; n++) {
    let c = n;
    for (let k = 0; k < 8; k++) c = c & 1 ? 0xedb88320 ^ (c >>> 1) : c >>> 1;
    crcTable[n] = c >>> 0;
  }
  const crc32 = (buf: Buffer): number => {
    let c = 0xffffffff;
    for (const byte of buf) c = crcTable[(c ^ byte) & 0xff] ^ (c >>> 8);
    return (c ^ 0xffffffff) >>> 0;
  };
  const chunk = (typ: string, data: Buffer): Buffer => {
    const body = Buffer.concat([Buffer.from(typ, "ascii"), data]);
    const len = Buffer.alloc(4);
    len.writeUInt32BE(data.length);
    const crc = Buffer.alloc(4);
    crc.writeUInt32BE(crc32(body));
    return Buffer.concat([len, body, crc]);
  };
  const sig = Buffer.from([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a]);
  const ihdrData = Buffer.alloc(13);
  ihdrData.writeUInt32BE(1, 0);
  ihdrData.writeUInt32BE(1, 4);
  ihdrData[8] = 8;
  ihdrData[9] = 2;
  // 未压缩 zlib 存储块：0x78 0x01 + 最终存储块头 + 数据 + adler32
  const raw = Buffer.from([0, r, g, b]);
  const adler = (() => {
    let a = 1,
      bsum = 0;
    for (const byte of raw) {
      a = (a + byte) % 65521;
      bsum = (bsum + a) % 65521;
    }
    return ((bsum << 16) | a) >>> 0;
  })();
  const deflate = Buffer.concat([
    Buffer.from([0x78, 0x01, 0x01, raw.length & 0xff, (raw.length >> 8) & 0xff]),
    Buffer.from([(~raw.length & 0xff) >>> 0, ((~raw.length >> 8) & 0xff) >>> 0]),
    raw,
    (() => {
      const bfr = Buffer.alloc(4);
      bfr.writeUInt32BE(adler);
      return bfr;
    })(),
  ]);
  return Buffer.concat([
    sig,
    chunk("IHDR", ihdrData),
    chunk("IDAT", deflate),
    chunk("IEND", Buffer.alloc(0)),
  ]);
}

async function api(request: APIRequestContext, method: "get" | "post" | "put" | "patch",
                   path: string, data?: unknown) {
  const res = await request[method](`${API}${path}`, data ? { data } : undefined);
  expect(res.status(), `${method} ${path}: ${await res.text()}`).toBeLessThan(300);
  return res.json();
}

async function uploadRef(request: APIRequestContext, familyId: number,
                         buf: Buffer, angle: string) {
  const res = await request.post(`${API}/api/product-reference-assets`, {
    multipart: {
      target_level: "family",
      target_id: String(familyId),
      angle,
      files: { name: `${rnd()}.png`, mimeType: "image/png", buffer: buf },
    },
  });
  expect(res.status(), await res.text()).toBe(201);
  return res.json();
}

test("PR-A2B 治理：策略/incomplete→complete/提交批准/混淆/变更历史/刷新持久", async ({
  page,
  request,
}) => {
  const tag = `B1UI${rnd()}`;
  // 1) API 造数：active 分类 + 产品 + 激活策略（2 图 + front + 1 identity 属性 + 主图）
  const cat = await api(request, "post", "/api/product-categories", { name_zh: `${tag}类` });
  await api(request, "post", `/api/product-categories/${cat.id}/status`, { status: "active" });
  const fam = await api(request, "post", "/api/product-families", {
    name_zh: `${tag}产品`, category_id: cat.id,
  });
  const pol = await api(request, "post", "/api/product-readiness-policies", {
    category_id: cat.id, name: `${tag}策略`, min_reference_count: 2,
    min_identity_attribute_count: 1, require_primary_reference: true,
    required_angles: ["front"],
  });
  await api(request, "post", `/api/product-readiness-policies/${pol.id}/activate`);

  // 2) UI：打开产品 → 完整度 Tab → incomplete + 缺失项可见
  await page.goto("/products");
  await expect(page.getByRole("heading", { name: "产品目录" })).toBeVisible();
  await page.getByTestId("tree-panel").getByText(`${tag}产品`).first().click();
  await expect(page.getByTestId("detail-name")).toHaveText(`${tag}产品`);
  await page.getByTestId("detail-tab-readiness").click();
  await expect(page.getByTestId("readiness-panel")).toBeVisible();
  await expect(page.getByTestId("readiness-missing")).toBeVisible();
  // eslint-disable-next-line no-console
  console.log("PR_A2B_UI_READINESS_OK");

  // 3) API 补资料：identity 属性（active）+ 值 + 2 图（front）+ 主图
  const def = await api(request, "post", "/api/product-attribute-definitions", {
    name_zh: `${tag}身份属性`, category_id: cat.id,
    value_type: "text", identity_relevant: true,
  });
  await api(request, "post", `/api/product-attribute-definitions/${def.id}/status`, {
    status: "active",
  });
  await api(request, "put", "/api/product-attribute-values", {
    definition_id: def.id, target_level: "family", target_id: fam.id, value: "样例值",
  });
  const up1 = await uploadRef(request, fam.id, png(200, 30, 30), "front");
  await uploadRef(request, fam.id, png(30, 200, 30), "front");
  await api(request, "post", `/api/product-reference-assets/${up1.created[0].id}/primary`);

  // 4) UI：重新评估 → complete
  await page.getByTestId("readiness-evaluate").click();
  await expect(page.getByTestId("readiness-complete")).toContainText(/完整|100/);

  // 5) UI：入驻审核 → 声明可见 → 提交 → 批准
  await page.getByTestId("detail-tab-onboarding").click();
  await expect(page.getByTestId("onboarding-permission-notice")).toContainText(
    "当前为可信内网人工审核，尚未启用用户权限",
  );
  await page.getByTestId("onboarding-submit").click();
  await expect(page.getByTestId("onboarding-status")).toContainText(/待人工审核|ready/);
  await page.getByTestId("onboarding-approve").click();
  await expect(page.getByTestId("onboarding-status")).toContainText(/已批准|approved/);
  // eslint-disable-next-line no-console
  console.log("PR_A2B_UI_ONBOARDING_OK");

  // 6) 混淆关系：另建同层级产品 → UI 添加关系
  const other = await api(request, "post", "/api/product-families", {
    name_zh: `${tag}相近品`, category_id: cat.id,
  });
  await page.getByTestId("detail-tab-confusions").click();
  await expect(page.getByTestId("confusions-panel")).toBeVisible();
  await page.getByTestId("confusion-add").click();
  // 目标候选为 <select>：先搜索缩小范围，再按已知 id 选择（不依赖 code 文案）
  await page.getByTestId("confusion-search").fill(`${tag}相近品`);
  await page.getByTestId("confusion-target-select").selectOption(String(other.id));
  await page.getByTestId("confusion-submit").click();
  await expect(page.getByTestId("confusions-panel")).toContainText(`${tag}相近品`);
  // eslint-disable-next-line no-console
  console.log("PR_A2B_UI_CONFUSION_OK");

  // 7) 变更历史：至少含 create/update 事件
  await page.getByTestId("detail-tab-history").click();
  await expect(page.getByTestId("history-panel")).toBeVisible();
  await expect(page.getByTestId("history-panel").locator('[data-testid^="revision-row-"]').first())
    .toBeVisible();
  // eslint-disable-next-line no-console
  console.log("PR_A2B_UI_REVISION_OK");

  // 8) 刷新持久：审核状态仍 approved
  await page.reload();
  await page.getByTestId("tree-panel").getByText(`${tag}产品`).first().click();
  await page.getByTestId("detail-tab-onboarding").click();
  await expect(page.getByTestId("onboarding-status")).toContainText(/已批准|approved/);
  // eslint-disable-next-line no-console
  console.log("PR_A2B_UI_E2E_OK");
});

test("@persist 重启后审核状态与变更历史仍在", async ({ page, request }) => {
  // 找主流程创建的 approved 产品（B1UI 前缀）
  const res = await request.get(`${API}/api/product-onboarding-reviews?status=approved`);
  expect(res.ok()).toBeTruthy();
  const body = await res.json();
  expect(body.total).toBeGreaterThanOrEqual(1);
  const withFamily = body.items.find((it: { family_id: number | null }) => it.family_id != null);
  expect(withFamily).toBeTruthy();
  const fam = await (await request.get(
    `${API}/api/product-families/${withFamily.family_id}`,
  )).json();

  await page.goto("/products");
  await page.getByTestId("tree-panel").getByText(fam.name_zh).first().click();
  await page.getByTestId("detail-tab-onboarding").click();
  await expect(page.getByTestId("onboarding-status")).toContainText(/已批准|approved/);
  await page.getByTestId("detail-tab-history").click();
  await expect(page.getByTestId("history-panel").locator('[data-testid^="revision-row-"]').first())
    .toBeVisible();
  // eslint-disable-next-line no-console
  console.log("PR_A2B_UI_PERSIST_OK");
});
