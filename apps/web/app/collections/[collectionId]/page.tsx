import { CollectionDetailView } from "@/components/projects/CollectionDetailView";

export default function CollectionDetailPage({ params }: { params: { collectionId: string } }) {
  const collectionId = Number(params.collectionId);
  return <CollectionDetailView collectionId={collectionId} />;
}
