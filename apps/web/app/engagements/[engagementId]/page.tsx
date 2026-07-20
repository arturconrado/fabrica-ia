import { EngagementWorkspace } from "@/components/service-operations/ServiceOperations";

export default async function EngagementPage({ params }: { params: Promise<{ engagementId: string }> }) {
  const { engagementId } = await params;
  return <EngagementWorkspace engagementId={engagementId} />;
}
