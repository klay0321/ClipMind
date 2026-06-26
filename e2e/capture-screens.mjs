// 用 Playwright 真实页面截取 Gate C 的 6 张证据图（1440×900）。合成/测试数据，无任何密钥。
// 用法：WEB_BASE=http://localhost:3300 API_BASE=http://localhost:8300 OUT=e2e/.artifacts node e2e/capture-screens.mjs
import { chromium } from "@playwright/test";
import { mkdirSync } from "node:fs";

const WEB = process.env.WEB_BASE || "http://localhost:3000";
const API = process.env.API_BASE || "http://localhost:8000";
const OUT = process.env.OUT || "e2e/.artifacts";
mkdirSync(OUT, { recursive: true });

async function pickTerm() {
  try {
    const r = await fetch(`${API}/api/search/suggestions?limit=20`);
    if (r.ok) {
      const b = await r.json();
      const pref = (b.items || []).find((i) => ["product", "scene", "action"].includes(i.type));
      if (pref) return pref.value;
      if (b.items?.[0]) return b.items[0].value;
    }
  } catch {}
  return "镜头";
}

const shot = async (page, name) => {
  await page.screenshot({ path: `${OUT}/${name}.png` });
  // eslint-disable-next-line no-console
  console.log(`SHOT ${name}`);
};

const main = async () => {
  const term = await pickTerm();
  const browser = await chromium.launch();
  const page = await browser.newPage({ viewport: { width: 1440, height: 900 } });

  // 01 搜索工作台总览
  await page.goto(`${WEB}/search`, { waitUntil: "networkidle" });
  await page.getByRole("heading", { name: "智能搜索" }).waitFor();
  await shot(page, "01-search-overview");

  // 02 自然语言搜索结果
  await page.getByTestId("search-input").fill(term);
  await page.getByTestId("search-submit").click();
  await page.getByTestId("results-meta").waitFor({ timeout: 30000 });
  await page.getByTestId("search-result-card").first().waitFor({ timeout: 30000 });
  await shot(page, "02-search-results");

  // 03 高级筛选展开
  await page.getByTestId("advanced-filters-toggle").click();
  await page.getByTestId("filter-scenes").waitFor();
  await shot(page, "03-advanced-filters");
  await page.getByTestId("advanced-filters-toggle").click();

  // 04 镜头匹配详情（抽屉）—— 点击卡片标题区（明确可交互），避免点到非交互留白
  await page.getByTitle("查看匹配详情").first().click();
  await page.getByTestId("result-drawer").waitFor();
  await page.getByTestId("drawer-detail-link").waitFor();
  await page.waitForTimeout(600);
  await shot(page, "04-match-detail");
  await page.getByTestId("drawer-close").click();

  // 05 画面描述匹配
  await page.goto(`${WEB}/search?mode=description`, { waitUntil: "networkidle" });
  await page.getByTestId("desc-input").fill(term);
  await page.getByTestId("desc-match").click();
  await page.getByTestId("desc-meta").waitFor({ timeout: 30000 });
  await page.getByTestId("match-result-row").first().waitFor({ timeout: 30000 });
  await shot(page, "05-description-match");

  // 06 索引状态 / degraded（展开索引状态详情，展示真实数字）
  await page.goto(`${WEB}/search`, { waitUntil: "networkidle" });
  await page.getByTestId("index-status").locator("button").first().click();
  await page.getByTestId("index-status-detail").waitFor();
  await shot(page, "06-index-status");

  await browser.close();
  // eslint-disable-next-line no-console
  console.log("CAPTURE_DONE");
};

main().catch((e) => {
  // eslint-disable-next-line no-console
  console.error(e);
  process.exit(1);
});
