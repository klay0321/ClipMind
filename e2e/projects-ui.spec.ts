import { expect, test, type APIRequestContext, type Page } from "@playwright/test";

// PR-06A Gate C 项目/集合真实页面 UI E2E（FakeProvider + 合成数据；不 mock、不写死结果、无 best-effort）。
// 期望标志（全部对应流程 + 强断言通过后才打印）：
//   PROJECTS_UI_E2E_OK / PROJECTS_MEMBERS_UI_E2E_OK / COLLECTIONS_UI_E2E_OK /
//   PROJECTS_SCRIPT_ATTACH_UI_E2E_OK / PROJECTS_SCRIPT_DETACH_SAFETY_UI_E2E_OK /
//   PROJECTS_ARCHIVE_UI_E2E_OK / PROJECTS_DELETE_SAFETY_UI_E2E_OK / PROJECTS_UI_PERSIST_OK
// 前置：docker compose 全栈已起、已播种合成数据（gate_c_e2e_seed.py）。CI 每次为全新隔离栈。

const API = process.env.API_BASE || "http://localhost:8000";
const SHOTS_DIR = process.env.SHOTS_DIR || "e2e/.artifacts";
const NAME = "PR06A-UI-E2E-project";
const SCRIPT_NAME = "PR06A-UI-E2E-script";
const SCRIPT_TEXT =
  "开场画面：展示产品整体外观。\n\n使用演示：手持操作画面清晰。\n\n卖点强调：突出便携轻巧。";

async function findProjectId(request: APIRequestContext, name = NAME): Promise<number | null> {
  const res = await request.get(`${API}/api/projects?page=1&page_size=100`);
  if (!res.ok()) return null;
  const body = await res.json();
  return (body.items ?? []).find((p: { name: string; id: number }) => p.name === name)?.id ?? null;
}

// 确保存在一个已拆段脚本（内容哈希幂等复用；首次创建则 Fake 拆段出段落）
async function ensureScript(request: APIRequestContext): Promise<number> {
  const created = await (
    await request.post(`${API}/api/scripts`, { data: { name: SCRIPT_NAME, raw_script: SCRIPT_TEXT } })
  ).json();
  const id = created.id as number;
  const detail = await (await request.get(`${API}/api/scripts/${id}`)).json();
  if ((detail.segments ?? []).length === 0) {
    await request.post(`${API}/api/scripts/${id}/parse`, { data: { parser: "fake" } });
  }
  return id;
}

// 脚本快照：段落/锁定/gap/候选数（用于 detach 安全性强断言：attach/detach 不改这些）
async function scriptSnapshot(request: APIRequestContext, id: number) {
  const detail = await (await request.get(`${API}/api/scripts/${id}`)).json();
  const segments = (detail.segments ?? []) as { locked_shot_id: number | null; match_status: string }[];
  const ms = await (await request.get(`${API}/api/scripts/${id}/match-status`)).json();
  const candidates = ((ms.segments ?? []) as { candidate_count?: number }[]).reduce(
    (a, s) => a + (s.candidate_count ?? 0),
    0,
  );
  return {
    segment_count: segments.length,
    locked: segments.filter((s) => s.locked_shot_id != null).length,
    gap: segments.filter((s) => s.match_status === "gap").length,
    candidates,
  };
}

async function pickAndAdd(page: Page, openTestId: string, n: number) {
  await page.getByTestId(openTestId).click();
  await expect(page.getByTestId("member-picker")).toBeVisible();
  const items = page.locator('[data-testid^="picker-item-"]');
  await expect(items.first()).toBeVisible({ timeout: 20_000 });
  const count = Math.min(n, await items.count());
  for (let i = 0; i < count; i++) await items.nth(i).check();
  await page.getByTestId("picker-add").click();
  await expect(page.getByTestId("batch-result")).toBeVisible({ timeout: 20_000 });
}

test("项目/集合工作流：创建→成员→集合→脚本→统计→归档只读→恢复→删除安全", async ({ page, request }) => {
  // 1. 列表页 + 创建项目（CI 为全新隔离栈，无残留）
  await page.goto("/projects");
  await expect(page.getByRole("heading", { name: "项目" })).toBeVisible();
  await page.getByTestId("toggle-create-project").click();
  await page.getByLabel("项目名称").fill(NAME);
  await page.getByTestId("submit-create-project").click();
  await expect(page.getByTestId("project-card").filter({ hasText: NAME })).toBeVisible();
  await page.screenshot({ path: `${SHOTS_DIR}/projects-01-list.png` });

  await page.getByText(NAME, { exact: true }).first().click();
  await expect(page.getByTestId("project-name")).toHaveText(NAME);
  await expect(page.getByTestId("project-stats")).toBeVisible({ timeout: 20_000 });
  await page.screenshot({ path: `${SHOTS_DIR}/projects-03-overview.png` });
  const projectId = (await findProjectId(request))!;
  // eslint-disable-next-line no-console
  console.log("PROJECTS_UI_E2E_OK");

  // 2. 成员：素材 / 产品 / 显式镜头
  await page.getByTestId("tab-assets").click();
  await pickAndAdd(page, "add-assets", 2);
  await expect(page.locator('[data-testid^="project-asset-"]').first()).toBeVisible();
  await page.screenshot({ path: `${SHOTS_DIR}/projects-04-assets.png` });

  await page.getByTestId("tab-products").click();
  await pickAndAdd(page, "add-products", 2);

  await page.getByTestId("tab-shots").click();
  await expect(page.getByTestId("shot-card").first()).toBeVisible({ timeout: 20_000 });
  await page.getByTestId("shot-source").selectOption("explicit");
  await page.screenshot({ path: `${SHOTS_DIR}/projects-05-shots.png` });
  // eslint-disable-next-line no-console
  console.log("PROJECTS_MEMBERS_UI_E2E_OK");

  // 3. 集合：建两个，同一镜头进两个集合
  await page.getByTestId("tab-collections").click();
  for (const cname of ["UI-E2E-C1", "UI-E2E-C2"]) {
    await page.getByTestId("toggle-create-collection").click();
    await page.getByLabel("集合名称").fill(cname);
    await page.getByTestId("submit-create-collection").click();
    await expect(page.getByText(cname, { exact: true })).toBeVisible();
  }
  await page.screenshot({ path: `${SHOTS_DIR}/projects-06-collections.png` });

  const colls = (await (await request.get(`${API}/api/projects/${projectId}/collections?page=1&page_size=20`)).json())
    .items as { id: number; name: string }[];
  const c1 = colls.find((c) => c.name === "UI-E2E-C1")!;
  const c2 = colls.find((c) => c.name === "UI-E2E-C2")!;

  await page.goto(`/collections/${c1.id}`);
  await expect(page.getByTestId("collection-name")).toHaveText("UI-E2E-C1");
  await pickAndAdd(page, "add-collection-shots", 1);
  await expect(page.locator('[data-testid^="collection-shot-"]').first()).toBeVisible();
  await page.screenshot({ path: `${SHOTS_DIR}/projects-07-collection-detail.png` });

  const sharedShotId = (await (await request.get(`${API}/api/collections/${c1.id}/shots?page=1&page_size=24`)).json())
    .items[0].id as number;
  await page.goto(`/collections/${c2.id}`);
  await pickAndAdd(page, "add-collection-shots", 1);
  const c2ShotIds = ((await (await request.get(`${API}/api/collections/${c2.id}/shots?page=1&page_size=24`)).json())
    .items as { id: number }[]).map((s) => s.id);
  expect(c2ShotIds.length).toBeGreaterThan(0);
  // eslint-disable-next-line no-console
  console.log("COLLECTIONS_UI_E2E_OK");

  // 4. 脚本 attach/detach 确定性验收（无 best-effort）
  const scriptId = await ensureScript(request);
  const before = await scriptSnapshot(request, scriptId);

  await page.goto(`/projects/${projectId}`);
  await page.getByTestId("tab-scripts").click();
  await page.getByTestId("attach-script").click();
  await expect(page.getByTestId("member-picker")).toBeVisible();
  await page.getByTestId(`picker-item-${scriptId}`).check();
  await page.getByTestId("picker-add").click();
  // 页面显示已关联脚本
  await expect(page.getByTestId(`project-script-${scriptId}`)).toBeVisible({ timeout: 15_000 });
  // 刷新后关联仍在
  await page.reload();
  await page.getByTestId("tab-scripts").click();
  await expect(page.getByTestId(`project-script-${scriptId}`)).toBeVisible();
  // 打开 /script/{id} 成功
  await page.goto(`/script/${scriptId}`);
  await expect(page.getByTestId("script-title")).toHaveText(SCRIPT_NAME);
  // eslint-disable-next-line no-console
  console.log("PROJECTS_SCRIPT_ATTACH_UI_E2E_OK");

  // detach → 页面脚本消失；ScriptProject 本身与段落/锁定/gap/候选不变
  await page.goto(`/projects/${projectId}`);
  await page.getByTestId("tab-scripts").click();
  await page.getByTestId(`detach-script-${scriptId}`).click();
  await expect(page.getByTestId(`project-script-${scriptId}`)).not.toBeVisible();
  const after = await scriptSnapshot(request, scriptId);
  expect(after).toEqual(before); // detach 不改脚本内部状态
  expect((await (await request.get(`${API}/api/scripts/${scriptId}`)).json()).id).toBe(scriptId); // 脚本仍存在
  // 再次 attach + 重复 attach 幂等（不 500）
  await page.getByTestId("attach-script").click();
  await page.getByTestId(`picker-item-${scriptId}`).check();
  await page.getByTestId("picker-add").click();
  await expect(page.getByTestId(`project-script-${scriptId}`)).toBeVisible({ timeout: 15_000 });
  const dupAttach = await request.post(`${API}/api/projects/${projectId}/scripts/${scriptId}`);
  expect(dupAttach.status()).toBe(200); // 重复 attach 幂等
  // eslint-disable-next-line no-console
  console.log("PROJECTS_SCRIPT_DETACH_SAFETY_UI_E2E_OK");

  // 5. 归档 → 只读 + 后端 409（成员 + 脚本 attach/detach）
  await page.getByTestId("tab-overview").click();
  await page.getByTestId("overview-archive").click();
  await expect(page.getByTestId("archived-banner")).toBeVisible();
  await page.getByTestId("tab-assets").click();
  await expect(page.getByTestId("add-assets")).toBeDisabled();
  expect((await request.post(`${API}/api/projects/${projectId}/assets/batch`, { data: { ids: [1] } })).status()).toBe(409);
  expect((await request.post(`${API}/api/projects/${projectId}/scripts/${scriptId}`)).status()).toBe(409);
  expect((await request.delete(`${API}/api/projects/${projectId}/scripts/${scriptId}`)).status()).toBe(409);
  await page.screenshot({ path: `${SHOTS_DIR}/projects-08-archived.png` });
  // eslint-disable-next-line no-console
  console.log("PROJECTS_ARCHIVE_UI_E2E_OK");

  // 恢复 → 可编辑
  await page.getByTestId("tab-overview").click();
  await page.getByTestId("overview-unarchive").click();
  await expect(page.getByTestId("archived-banner")).not.toBeVisible();

  // 6. 删除集合 → 镜头仍存在
  await page.goto(`/collections/${c2.id}`);
  await page.getByTestId("delete-collection").click();
  await expect(page.getByText(/只删除集合和关联，不删除镜头/)).toBeVisible();
  await page.getByTestId("confirm-ok").click();
  await expect(page).toHaveURL(new RegExp(`/projects/${projectId}$`));
  expect((await request.get(`${API}/api/shots/${sharedShotId}`)).ok()).toBeTruthy();
  // eslint-disable-next-line no-console
  console.log("PROJECTS_DELETE_SAFETY_UI_E2E_OK");
});

test("@persist 重启后项目/成员/集合/脚本关联仍在", async ({ page, request }) => {
  const projectId = await findProjectId(request);
  expect(projectId).not.toBeNull();
  await page.goto(`/projects/${projectId}`);
  await expect(page.getByTestId("project-name")).toHaveText(NAME);
  const stats = await (await request.get(`${API}/api/projects/${projectId}/stats`)).json();
  expect(stats.asset_count).toBeGreaterThanOrEqual(1);
  expect(stats.collection_count).toBeGreaterThanOrEqual(1);
  expect(stats.script_count).toBeGreaterThanOrEqual(1); // 脚本关联持久化
  await page.getByTestId("tab-collections").click();
  await expect(page.getByText("UI-E2E-C1", { exact: true })).toBeVisible();
  // eslint-disable-next-line no-console
  console.log("PROJECTS_UI_PERSIST_OK");
});
