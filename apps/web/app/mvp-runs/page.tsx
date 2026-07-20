import { OperationalIndex } from "@/components/missions/OperationalIndex";

export default function MvpRunsPage() {
  return <OperationalIndex endpoint="/api/v1/mvp-runs" title="MVP runs" description="Escopos materializados, quality gates e packages antes da execução ASF." emptyDescription="Gere o primeiro MVP a partir de uma oportunidade real." hrefPrefix="/mvp-runs" kind="mvp_run" />;
}
