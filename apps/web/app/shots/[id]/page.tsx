import { ShotDetailPage } from "@/components/ShotDetailPage";

export default function Page({ params }: { params: { id: string } }) {
  const raw = Number(params.id);
  const shotId = Number.isFinite(raw) ? raw : null;
  return <ShotDetailPage shotId={shotId} />;
}
