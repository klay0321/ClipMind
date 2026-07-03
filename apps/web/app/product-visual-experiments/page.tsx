import { TopNav } from "@/components/TopNav";
import { VisualExperimentsView } from "@/components/visual/VisualExperimentsView";

export const metadata = { title: "视觉识别实验 - ClipMind" };

export default function ProductVisualExperimentsPage() {
  return (
    <div className="min-h-screen bg-gray-50">
      <TopNav active="visual-experiments" />
      <main className="mx-auto max-w-7xl px-4 py-6">
        <VisualExperimentsView />
      </main>
    </div>
  );
}
