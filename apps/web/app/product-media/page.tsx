import { Suspense } from "react";

import { TopNav } from "@/components/TopNav";
import { ProductMediaView } from "@/components/product-media/ProductMediaView";

export const metadata = { title: "产品素材库 - ClipMind" };

export default function ProductMediaPage() {
  return (
    <div className="min-h-screen bg-gray-50">
      <TopNav active="product-media" />
      <main className="mx-auto max-w-7xl px-4 py-6">
        <Suspense fallback={<p className="text-sm text-gray-400">加载中…</p>}>
          <ProductMediaView />
        </Suspense>
      </main>
    </div>
  );
}
