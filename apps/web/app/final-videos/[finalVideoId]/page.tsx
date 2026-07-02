import { FinalVideoDetail } from "@/components/final-videos/FinalVideoDetail";

export default function FinalVideoDetailPage({
  params,
}: {
  params: { finalVideoId: string };
}) {
  const id = Number(params.finalVideoId);
  return <FinalVideoDetail finalVideoId={id} />;
}
