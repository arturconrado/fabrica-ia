import { ServiceOfferingWorkspace } from "@/components/service-operations/ServiceOperations";


export default async function ServiceOfferingPage({ params }: { params: Promise<{ offeringId: string }> }) {
  const { offeringId } = await params;
  return <ServiceOfferingWorkspace offeringId={offeringId} />;
}
