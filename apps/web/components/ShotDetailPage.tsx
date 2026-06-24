"use client";

import Link from "next/link";

import { ShotDetail } from "@/components/ShotDetail";
import { TopNav } from "@/components/TopNav";

export function ShotDetailPage({ shotId }: { shotId: number | null }) {
  return (
    <div>
      <TopNav active="shots" />
      <main className="mx-auto max-w-2xl space-y-3 p-4">
        <Link href="/shots" className="text-sm text-gray-500 hover:text-gray-800">
          ← 返回镜头库
        </Link>
        <div className="rounded-lg border border-gray-100 bg-white shadow-sm">
          <ShotDetail shotId={shotId} />
        </div>
      </main>
    </div>
  );
}
