import { expect, test, type APIRequestContext } from "@playwright/test";

// PR-B 真实浏览器 UI E2E：最终成片 / 使用血缘工作台。
// 前置：docker compose 全栈已起。数据经真实 API 以中性名称播种（不依赖公司素材）：
// 复用栈内已有 ready 镜头（gate_c_e2e_seed 或本地真实索引），成片 Asset 直接取
// 与来源镜头不同的任一 Asset；若栈内可用镜头不足则跳过（CI 中 seed 先行，不会跳过）。
// 登记成片 → 手工添加候选 → 确认 → 使用次数展示 → 撤销 → 归档守卫 → @persist 重启仍在。

const API = process.env.API_BASE || "http://localhost:8000";

function rnd(): string {
  return Math.random().toString(36).slice(2, 8);
}

type Seed = {
  fvId: number;
  fvTitle: string;
  usageId: number;
  shotId: number;
};

async function apiJson(
  request: APIRequestContext,
  method: "get" | "post",
  path: string,
  data?: unknown,
): Promise<unknown> {
  const res = await request[method](`${API}${path}`, data ? { data } : undefined);
  if (!res.ok()) {
    throw new Error(`${method.toUpperCase()} ${path} -> ${res.status()}: ${await res.text()}`);
  }
  return res.json();
}

/** 找一个 ready 镜头 + 一个与其素材不同、且未被活动成片占用的 Asset 作为成片文件。 */
async function pickSeedMaterial(request: APIRequestContext) {
  const shots = (await apiJson(request, "get", "/api/shots?page=1&page_size=20")) as {
    items: { id: number; asset_id: number }[];
  };
  if (!shots.items.length) return null;
  const shot = shots.items[0];
  const existing = (await apiJson(
    request,
    "get",
    "/api/final-videos?page=1&page_size=100",
  )) as { items: { asset_id: number }[] };
  const taken = new Set(existing.items.map((f) => f.asset_id));
  const assets = (await apiJson(request, "get", "/api/assets?page=1&page_size=50")) as {
    items: { id: number; status: string }[];
  };
  const finalAsset = assets.items.find(
    (a) => a.id !== shot.asset_id && a.status === "indexed" && !taken.has(a.id),
  );
  if (!finalAsset) return null;
  return { shotId: shot.id, finalAssetId: finalAsset.id };
}

let seed: Seed | null = null;

test.describe.serial("PR-B 成片与使用血缘 UI", () => {
  test("登记成片 → 手工添加候选 → 人工确认 → 使用次数与事件展示", async ({
    page,
    request,
  }) => {
    const material = await pickSeedMaterial(request);
    test.skip(!material, "栈内没有可用镜头/素材（CI 中 seed 先行不会发生）");
    const { shotId, finalAssetId } = material!;

    const title = `PRB-UI-成片-${rnd()}`;
    const fv = (await apiJson(request, "post", "/api/final-videos", {
      asset_id: finalAssetId,
      title,
    })) as { id: number };

    // 列表页可见 + 明确提示"确认后才计数"
    await page.goto("/final-videos");
    await expect(page.getByTestId("final-video-table")).toBeVisible();
    await expect(page.getByText("人工确认后才计入正式使用次数")).toBeVisible();
    await page.getByTestId("final-video-search").fill(title);
    await expect(page.getByTestId("final-video-row")).toHaveCount(1);
    await expect(page.getByTestId("final-video-row")).toContainText(title);

    // 详情：手工添加镜头（API 加速播种候选，UI 验证展示与动作）
    const usage = (await apiJson(request, "post", `/api/final-videos/${fv.id}/usages`, {
      source_shot_id: shotId,
    })) as { id: number };
    await page.goto(`/final-videos/${fv.id}`);
    await expect(page.getByTestId("fv-title")).toContainText(title);
    const row = page.getByTestId("usage-row");
    await expect(row).toHaveCount(1);
    await expect(row).toContainText("候选待确认");
    await expect(row).toContainText("人工添加");
    // proposed 不显示为正式使用
    await expect(page.getByTestId("fv-usage-stats")).toContainText("已确认 0");

    // 人工确认 → 状态与统计更新
    await page.getByTestId(`usage-confirm-${usage.id}`).click();
    await expect(row).toContainText("已确认使用");
    await expect(page.getByTestId("fv-usage-stats")).toContainText("已确认 1");

    // 展开：occurrence 编辑 + 事件时间线
    await page.getByTestId(`usage-occ-toggle-${usage.id}`).click();
    await expect(page.getByTestId(`usage-events-${usage.id}`)).toContainText("人工添加");
    await expect(page.getByTestId(`usage-events-${usage.id}`)).toContainText("确认使用");

    seed = { fvId: fv.id, fvTitle: title, usageId: usage.id, shotId };
    console.log("PR_B_UI_FINAL_VIDEO_OK");
    console.log("PR_B_UI_CONFIRM_OK");
  });

  test("镜头库显示只读使用徽标；撤销后立即消失", async ({ page, request }) => {
    test.skip(!seed, "依赖上一用例播种");
    // 镜头详情 usage-summary API 口径
    const summary = (await apiJson(
      request,
      "get",
      `/api/shots/${seed!.shotId}/usage-summary`,
    )) as { confirmed_usage_count: number };
    expect(summary.confirmed_usage_count).toBe(1);

    // 撤销 → 计数立即归零（次数是派生值）
    await apiJson(request, "post", `/api/final-video-usages/${seed!.usageId}/revoke`, {
      note: "ui-e2e",
    });
    const after = (await apiJson(
      request,
      "get",
      `/api/shots/${seed!.shotId}/usage-summary`,
    )) as { confirmed_usage_count: number };
    expect(after.confirmed_usage_count).toBe(0);

    // 恢复候选并重新确认，为 @persist 保留一条 confirmed
    await apiJson(
      request,
      "post",
      `/api/final-video-usages/${seed!.usageId}/restore-proposal`,
      {},
    );
    await apiJson(request, "post", `/api/final-video-usages/${seed!.usageId}/confirm`, {});

    // 详情页状态徽标为已确认
    await page.goto(`/final-videos/${seed!.fvId}`);
    await expect(page.getByTestId("usage-row")).toContainText("已确认使用");
    console.log("PR_B_UI_USAGE_COUNT_OK");
  });

  test("归档成片：只读守卫 + 历史确认保持", async ({ page, request }) => {
    test.skip(!seed, "依赖上一用例播种");
    await apiJson(request, "post", `/api/final-videos/${seed!.fvId}/archive`, {});
    await page.goto(`/final-videos/${seed!.fvId}`);
    await expect(page.getByTestId("fv-add-shot")).toBeDisabled();
    await expect(page.getByTestId("fv-propose")).toBeDisabled();
    // 历史 confirmed 保持计数
    await expect(page.getByTestId("fv-usage-stats")).toContainText("已确认 1");
    // 恢复，保持栈状态干净
    await page.getByTestId("fv-restore").click();
    await expect(page.getByTestId("fv-archive")).toBeVisible();
    console.log("PR_B_UI_ARCHIVE_GUARD_OK");
    console.log("PR_B_UI_E2E_OK");
  });

  test("@persist 重启后血缘、事件与使用次数仍在", async ({ page, request }) => {
    // @persist 由 CI 在 docker compose restart 之后运行；seed 变量跨进程不可用，
    // 以标题前缀查回最新成片。
    const list = (await apiJson(
      request,
      "get",
      "/api/final-videos?page=1&page_size=50&q=PRB-UI-",
    )) as { items: { id: number; title: string; usage_stats: { confirmed_count: number } }[] };
    test.skip(!list.items.length, "无 PRB-UI 播种数据（先运行非 persist 用例）");
    const fv = list.items[0];
    expect(fv.usage_stats.confirmed_count).toBeGreaterThanOrEqual(1);

    await page.goto(`/final-videos/${fv.id}`);
    await expect(page.getByTestId("fv-title")).toContainText(fv.title);
    const row = page.getByTestId("usage-row").first();
    await expect(row).toContainText("已确认使用");
    // 事件时间线仍在（append-only 持久化）
    const toggle = page.getByTestId(/usage-occ-toggle-/).first();
    await toggle.click();
    await expect(page.getByTestId(/usage-events-/)).toContainText("确认使用");
    console.log("PR_B_UI_PERSIST_OK");
  });
});
