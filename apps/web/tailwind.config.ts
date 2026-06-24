import type { Config } from "tailwindcss";

const config: Config = {
  content: ["./app/**/*.{ts,tsx}", "./components/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        // 主操作色（绿色），呼应 ClipMind 视觉
        brand: {
          DEFAULT: "#0f7b6c",
          dark: "#0b5e53",
          light: "#e6f4f1",
        },
      },
    },
  },
  plugins: [],
};

export default config;
