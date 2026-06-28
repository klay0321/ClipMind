import { ProjectDetailView } from "@/components/projects/ProjectDetailView";

export default function ProjectDetailPage({ params }: { params: { projectId: string } }) {
  const projectId = Number(params.projectId);
  return <ProjectDetailView projectId={projectId} />;
}
