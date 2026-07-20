import { Suspense } from "react";
import { ReviewCenter } from "@/components/review/ReviewCenter";
import { LoadingState } from "@/components/common/OperationalUI";

export default function ApprovalsPage() {
  return <Suspense fallback={<LoadingState label="Carregando aprovações…" />}><ReviewCenter /></Suspense>;
}
