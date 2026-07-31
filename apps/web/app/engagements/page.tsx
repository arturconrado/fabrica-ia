import { EngagementsView } from "@/components/service-operations/ServiceOperations";

export default async function EngagementsPage({ searchParams }: { searchParams: Promise<{ offering?: string }> }) {
  const { offering = "" } = await searchParams;
  return <EngagementsView initialOfferingId={offering} />;
}
