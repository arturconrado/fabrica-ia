"use client";

import { useParams } from "next/navigation";
import { ComponentView } from "@/components/service-delivery/ServiceDeliveryViews";

export default function ComponentPage() {
  const params = useParams<{ componentId: string }>();
  return <ComponentView componentId={params.componentId} />;
}
