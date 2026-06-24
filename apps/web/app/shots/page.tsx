import { ShotsView } from "@/components/ShotsView";

export default function ShotsPage({
  searchParams,
}: {
  searchParams: { asset_id?: string };
}) {
  const raw = searchParams.asset_id ? Number(searchParams.asset_id) : null;
  const assetId = raw != null && Number.isFinite(raw) ? raw : null;
  return <ShotsView assetId={assetId} />;
}
