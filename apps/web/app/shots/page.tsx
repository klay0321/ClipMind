import { ShotsView } from "@/components/ShotsView";

export default function ShotsPage({
  searchParams,
}: {
  searchParams: { asset_id?: string; product_id?: string };
}) {
  const raw = searchParams.asset_id ? Number(searchParams.asset_id) : null;
  const assetId = raw != null && Number.isFinite(raw) ? raw : null;
  const praw = searchParams.product_id ? Number(searchParams.product_id) : null;
  const productId = praw != null && Number.isFinite(praw) ? praw : null;
  return <ShotsView assetId={assetId} initialProductId={productId} />;
}
