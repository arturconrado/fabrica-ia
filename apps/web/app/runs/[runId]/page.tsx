"use client";

import { useState } from "react";
import dynamic from "next/dynamic";
import { useParams } from "next/navigation";
import { Panel } from "@/components/common/Panel";
import { ApprovalsPanel } from "@/components/run/ApprovalsPanel";
import { AINativeProvenancePanel } from "@/components/run/AINativeProvenancePanel";
import { ArtifactsPanel } from "@/components/run/ArtifactsPanel";
import { BuildWorkspace } from "@/components/run/BuildWorkspace";
import { DiffsPanel } from "@/components/run/DiffsPanel";
import { FeedbackPanel } from "@/components/run/FeedbackPanel";
import { FactoryFloor } from "@/components/run/FactoryFloor";
import { FilesPanel } from "@/components/run/FilesPanel";
import { HomologationReadinessPanel } from "@/components/run/HomologationReadinessPanel";
import { LivePreviewPanel } from "@/components/run/LivePreviewPanel";
import { NodeInspector } from "@/components/run/NodeInspector";
import { QualityGatesPanel } from "@/components/run/QualityGatesPanel";
import { RawLogsPanel } from "@/components/run/RawLogsPanel";
import { RequirementsPanel } from "@/components/run/RequirementsPanel";
import { RunHeader } from "@/components/run/RunHeader";
import { TestsPanel } from "@/components/run/TestsPanel";
import { Timeline } from "@/components/run/Timeline";
import { TraceabilityMatrix } from "@/components/run/TraceabilityMatrix";
import { ErrorState, LoadingState } from "@/components/common/OperationalUI";
import { useRunData } from "@/hooks/useRunData";
import { useRunStream } from "@/hooks/useRunStream";
import type { Dict } from "@/lib/types";
import type { WorkflowTopology } from "@/lib/contracts";

const WorkflowGraph = dynamic(() => import("@/components/run/WorkflowGraph").then((module) => module.WorkflowGraph), { ssr: false, loading: () => <LoadingState label="Carregando topologia…" /> });
const tabs = [
  { id: "build", label: "Linha de produção" },
  { id: "preview", label: "Topologia" },
  { id: "files", label: "Artifacts e arquivos" },
  { id: "tests", label: "Testes" },
  { id: "quality", label: "Qualidade" },
  { id: "ai", label: "IA e proveniência" },
  { id: "approval", label: "Aprovação" },
  { id: "logs", label: "Ledger técnico" }
];

export default function RunPage() {
  const params = useParams<{ runId: string }>();
  const runId = params.runId;
  const { data, loading, error, reload } = useRunData(runId);
  const [selectedNode, setSelectedNode] = useState<Dict | null>(null);
  const [tab, setTab] = useState("build");
  useRunStream(runId, reload);

  if (loading) return <LoadingState label="Sincronizando cockpit com o workflow…" />;
  if (error) return <ErrorState message={error} />;
  if (!data.run) return <ErrorState message="Execução não encontrada neste tenant." />;

  return (
    <div className="space-y-4">
      <RunHeader run={data.run} onReload={() => void reload()} />
      <div className="flex gap-2 overflow-x-auto pb-1" role="tablist" aria-label="Áreas da missão">
        {tabs.map((item) => (
          <button role="tab" aria-selected={tab === item.id} key={item.id} className={`min-h-11 shrink-0 rounded-lg border px-3 text-sm ${tab === item.id ? "border-blue-500/40 bg-blue-500/15 font-semibold text-blue-200" : "border-line bg-[rgb(var(--panel))] text-[rgb(var(--muted))]"}`} onClick={() => setTab(item.id)}>
            {item.label}
          </button>
        ))}
      </div>
      {tab === "build" && (
        <BuildWorkspace
          run={data.run}
          agentStates={data.agentStates}
          agentMessages={data.agentMessages}
          workItems={data.workItems}
          artifacts={data.artifacts}
          files={data.files}
          tests={data.tests}
          gates={data.gates}
          events={data.events}
          homologation={data.homologation}
        />
      )}
      {tab === "preview" && (
        <div className="grid gap-4 xl:grid-cols-[1.5fr_1fr]">
          <div className="xl:col-span-2"><LivePreviewPanel files={data.files} tests={data.tests} artifacts={data.artifacts} run={data.run} /></div>
          <Panel title="Topologia real do workflow"><WorkflowGraph topology={data.topology as WorkflowTopology | null} nodes={data.nodes} currentNode={String(data.run.current_node || "")} onSelect={setSelectedNode} /></Panel>
          <Panel title="Inspetor do node"><NodeInspector node={selectedNode} events={data.events} artifacts={data.artifacts} /></Panel>
          <Panel title="Timeline"><Timeline events={data.events} /></Panel>
        </div>
      )}
      {tab === "quality" && (
        <div className="grid gap-4 xl:grid-cols-2">
          <Panel title="Prontidão para homologação"><HomologationReadinessPanel run={data.run} homologation={data.homologation} /></Panel>
          <Panel title="Quality Gates"><QualityGatesPanel gates={data.gates} /></Panel>
          <Panel title="Requisitos e critérios"><RequirementsPanel requirements={data.requirements} criteria={data.criteria} /></Panel>
          <Panel title="Matriz de rastreabilidade"><TraceabilityMatrix rows={data.traceability} /></Panel>
          <Panel title="Linha de agentes"><FactoryFloor run={data.run} agentStates={data.agentStates} agentMessages={data.agentMessages} workItems={data.workItems} artifacts={data.artifacts} events={data.events} /></Panel>
          <Panel title="Feedback"><FeedbackPanel run={data.run} feedback={data.feedback} onReload={() => void reload()} /></Panel>
        </div>
      )}
      {tab === "files" && (
        <div className="grid gap-4">
          <Panel title="Arquivos"><FilesPanel runId={runId} files={data.files} /></Panel>
          <Panel title="Diffs"><DiffsPanel diffs={data.diffs} /></Panel>
          <Panel title="Artifacts"><ArtifactsPanel artifacts={data.artifacts} /></Panel>
        </div>
      )}
      {tab === "tests" && <Panel title="Relatórios de teste"><TestsPanel tests={data.tests} /></Panel>}
      {tab === "ai" && <AINativeProvenancePanel runId={runId} ai={data.ai} steps={data.stepExecutions} units={data.executionUnits} fragments={data.artifactFragments} validation={data.validation} />}
      {tab === "approval" && <Panel title="Aprovações"><ApprovalsPanel run={data.run} approvals={data.homologation.approvals || []} onReload={() => void reload()} /></Panel>}
      {tab === "logs" && <Panel title="Eventos técnicos do ledger"><RawLogsPanel events={data.events} /></Panel>}
    </div>
  );
}
