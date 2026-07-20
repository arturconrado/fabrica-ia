import { ClientWorkspace } from "@/components/service-operations/ServiceOperations";

export default async function ClientPage({ params }: { params: Promise<{ tenantId: string }> }) {
  const { tenantId } = await params;
  return <ClientWorkspace tenantId={tenantId} />;
}
