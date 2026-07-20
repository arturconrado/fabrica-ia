"use client";

import { useParams } from "next/navigation";
import { OpportunityView } from "@/components/service-delivery/ServiceDeliveryViews";

export default function OpportunityPage() {
  const params = useParams<{ opportunityId: string }>();
  return <OpportunityView opportunityId={params.opportunityId} />;
}
