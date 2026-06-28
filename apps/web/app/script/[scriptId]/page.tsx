import { ScriptWorkbench } from "@/components/script/ScriptWorkbench";

export default function ScriptWorkbenchPage({ params }: { params: { scriptId: string } }) {
  const raw = Number(params.scriptId);
  const scriptId = Number.isFinite(raw) ? raw : null;
  return <ScriptWorkbench scriptId={scriptId} />;
}
