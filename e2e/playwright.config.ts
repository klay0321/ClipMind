import { defineConfig } from "@playwright/test";

// 驱动真实运行的 web 容器（默认 http://localhost:3000）。截图按 1440×900 桌面尺寸。
export default defineConfig({
  testDir: ".",
  testMatch: /.*\.spec\.ts/,
  timeout: 90_000,
  expect: { timeout: 30_000 },
  fullyParallel: false,
  workers: 1,
  reporter: [["list"]],
  use: {
    baseURL: process.env.WEB_BASE || "http://localhost:3000",
    headless: true,
    viewport: { width: 1440, height: 900 },
    actionTimeout: 15_000,
    screenshot: "only-on-failure",
    trace: "retain-on-failure",
  },
});
