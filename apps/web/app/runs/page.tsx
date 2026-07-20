import { OperationalIndex } from "@/components/missions/OperationalIndex";

export default function RunsPage() {
  return <OperationalIndex endpoint="/runs" title="Runs" description="Execuções da fábrica, com demanda, projeto e estado derivados do ledger." emptyDescription="Nenhuma missão foi iniciada neste tenant." hrefPrefix="/runs" kind="run" />;
}
