import { ServiceDeliverableWorkspace } from "@/components/service-operations/ServiceOperations";

export default async function DeliverablePage({ params }: { params: Promise<{ deliverableId: string }> }) {
  const { deliverableId } = await params;
  return <ServiceDeliverableWorkspace deliverableId={deliverableId} />;
}
