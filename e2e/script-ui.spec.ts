import { expect, test, type APIRequestContext } from "@playwright/test";

// Gate C 脚本匹配真实页面 UI E2E：真实 web 页面 + 真实 API（FakeProvider + FakeEmbedding +
// Fake/规则拆段）。不写死结果、不 mock。期望标志：
// SCRIPT_UI_E2E_OK / SCRIPT_CANDIDATE_UI_E2E_OK / SCRIPT_LOCK_UI_E2E_OK /
// SCRIPT_EDIT_LIST_UI_E2E_OK / SCRIPT_CSV_UI_E2E_OK / SCRIPT_UI_PERSIST_OK
//
// 前置：docker compose 全栈已起、已播种合成数据并建索引（gate_c_e2e_seed.py）。

const API = process.env.API_BASE || "http://localhost:8000";
const SHOTS_DIR = process.env.SHOTS_DIR || "e2e/.artifacts";
const NAME = "gate-c-ui-script";
const SCRIPT_TEXT =
  "开场画面：展示产品整体外观。\n\n使用演示：手持操作画面清晰。\n\n卖点强调：突出便携轻巧。\n\n结尾引导：点击了解更多。";

async function findScriptId(request: APIRequestContext): Promise<number | null> {
  const res = await request.get(`${API}/api/scripts?page=1&page_size=100`);
  if (!res.ok()) return null;
  const body = await res.json();
  const item = (body.items ?? []).find((p: { name: string; id: number }) => p.name === NAME);
  return item?.id ?? null;
}

test("脚本匹配工作台：创建→拆段→匹配→候选→选择锁定→剪辑清单→CSV", async ({ page }) => {
  await page.goto("/script");
  await expect(page.getByRole("heading", { name: "脚本匹配与剪辑清单" })).toBeVisible();

  // 创建项目（粘贴脚本）→ 跳转工作台
  await page.getByTestId("script-name").fill(NAME);
  await page.getByTestId("script-raw").fill(SCRIPT_TEXT);
  await page.getByTestId("script-create").click();
  await expect(page.getByTestId("script-title")).toHaveText(NAME);

  // AI 拆段（自动=规则/Fake）→ 段落出现。可重复运行：若存在上轮残留锁定，勾选强制重拆。
  const forceBox = page.getByTestId("parse-force");
  if (await forceBox.isVisible().catch(() => false)) await forceBox.check();
  await page.getByTestId("parse-btn").click();
  await expect(page.getByTestId("segment-row").first()).toBeVisible();
  await page.screenshot({ path: `${SHOTS_DIR}/script-02-parsed.png`, fullPage: false });
  // eslint-disable-next-line no-console
  console.log("SCRIPT_UI_E2E_OK");

  // 全脚本匹配 → 第一段候选出现（真实 MiMo 逐段解析较慢，给足超时；CI Fake 很快）
  await page.getByTestId("match-all").click();
  await expect(page.getByTestId("candidate-card").first()).toBeVisible({ timeout: 90_000 });
  await page.screenshot({ path: `${SHOTS_DIR}/script-04-candidates.png`, fullPage: false });
  // eslint-disable-next-line no-console
  console.log("SCRIPT_CANDIDATE_UI_E2E_OK");

  // 选择第一候选 → 等待"已选择"（lock_version 刷新到位，避免与随后锁定竞态）→ 锁定 → 锁定横幅
  const firstCard = page.getByTestId("candidate-card").first();
  await firstCard.getByTestId("candidate-select").click();
  await expect(page.getByTestId("candidate-card").first()).toHaveAttribute("data-state", "selected");
  await page.getByTestId("candidate-card").first().getByTestId("candidate-lock").click();
  await expect(page.getByTestId("locked-banner")).toBeVisible();
  // 重匹配 → 代次增加且锁定不被覆盖
  await expect(page.getByTestId("panel-rematch")).toBeVisible();
  await page.getByTestId("panel-rematch").click();
  await expect(page.getByTestId("gen-switcher")).toBeVisible({ timeout: 30_000 });
  await expect(page.getByTestId("locked-banner")).toBeVisible();
  await page.screenshot({ path: `${SHOTS_DIR}/script-06-lock.png`, fullPage: false });
  // eslint-disable-next-line no-console
  console.log("SCRIPT_LOCK_UI_E2E_OK");

  // 剪辑清单 Tab
  await page.getByTestId("tab-editlist").click();
  await expect(page.getByTestId("editlist-row").first()).toBeVisible({ timeout: 20_000 });
  await page.screenshot({ path: `${SHOTS_DIR}/script-08-editlist.png`, fullPage: false });
  // eslint-disable-next-line no-console
  console.log("SCRIPT_EDIT_LIST_UI_E2E_OK");

  // CSV 导出 → 等待完成 → 下载按钮
  await page.getByTestId("export-csv").click();
  await expect(page.getByTestId("export-download")).toBeVisible({ timeout: 60_000 });
  await expect(page.getByTestId("export-download")).toHaveAttribute("href", /\/api\/scripts\/\d+\/exports\/\d+\/download/);
  // eslint-disable-next-line no-console
  console.log("SCRIPT_CSV_UI_E2E_OK");
});

test("@persist 重启后脚本项目/候选/锁定仍在", async ({ page, request }) => {
  const id = await findScriptId(request);
  expect(id).not.toBeNull();
  await page.goto(`/script/${id}`);
  await expect(page.getByTestId("script-title")).toHaveText(NAME);
  await expect(page.getByTestId("segment-row").first()).toBeVisible();
  // 上一轮锁定的段落应仍锁定（重匹配不覆盖、重启持久化）
  await expect(page.getByTestId("seg-locked").first()).toBeVisible();
  // eslint-disable-next-line no-console
  console.log("SCRIPT_UI_PERSIST_OK");
});
