import path from "node:path";

import react from "@vitejs/plugin-react";
import { defineConfig } from "vitest/config";

export default defineConfig({
  plugins: [react()],
  test: {
    environment: "jsdom",
    globals: true,
    setupFiles: ["./vitest.setup.ts"],
    // forks 池更稳定，避免 Windows 上 tinypool 线程 worker 偶发崩溃
    pool: "forks",
  },
  resolve: {
    alias: { "@": path.resolve(__dirname, ".") },
  },
});
