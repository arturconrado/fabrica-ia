"use client";

import { useParams } from "next/navigation";
import { ProgramView } from "@/components/service-delivery/ServiceDeliveryViews";

export default function ProgramPage() {
  const params = useParams<{ programId: string }>();
  return <ProgramView programId={params.programId} />;
}
