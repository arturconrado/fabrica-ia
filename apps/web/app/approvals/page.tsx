import { Suspense } from "react";
import { ReviewCenter } from "@/components/review/ReviewCenter";
import { LoadingState, PageHeader } from "@/components/common/OperationalUI";

export default function ApprovalsPage() {
  return (
    <div className="space-y-6">
      <PageHeader eyebrow="Human-in-the-loop" title="Aprovações" description="Decida somente depois de conferir gates, rastreabilidade e artifacts autorizados." />
      <Suspense fallback={<LoadingState label="Carregando aprovações…" />}><ReviewCenter /></Suspense>
    </div>
  );
}
