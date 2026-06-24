import "./globals.css";

import type { Metadata } from "next";

import { Providers } from "./providers";

export const metadata: Metadata = {
  title: "ClipMind",
  description: "AI 视频素材管理与智能匹配系统",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="zh-CN">
      <body className="min-h-screen bg-gray-50 text-gray-900 antialiased">
        <Providers>{children}</Providers>
      </body>
    </html>
  );
}
