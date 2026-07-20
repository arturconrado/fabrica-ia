"use client";

import { useParams } from "next/navigation";
import { MvpRunView } from "@/components/service-delivery/ServiceDeliveryViews";

export default function MvpRunPage() {
  const params = useParams<{ mvpRunId: string }>();
  return <MvpRunView mvpRunId={params.mvpRunId} />;
}
