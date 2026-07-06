"use client";

import { useState } from "react";
import { useParams } from "next/navigation";
import { Panel } from "@/components/common/Panel";
import { ApprovalsPanel } from "@/components/run/ApprovalsPanel";
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
import { WorkflowGraph } from "@/components/run/WorkflowGraph";
import { useRunData } from "@/hooks/useRunData";
import { useRunStream } from "@/hooks/useRunStream";
import type { Dict } from "@/lib/types";

const tabs = ["Build", "Preview", "Files", "Tests", "Quality", "Approval", "Logs"];

export default function RunPage() {
  const params = useParams<{ runId: string }>();
  const runId = params.runId;
  const { data, loading, error, reload } = useRunData(runId);
  const [selectedNode, setSelectedNode] = useState<Dict | null>(null);
  const [tab, setTab] = useState("Build");
  useRunStream(runId, reload);

  if (loading) return <div className="panel px-4 py-8 text-sm text-slate-500">Loading run...</div>;
  if (error) return <div className="panel px-4 py-8 text-sm text-red-700">{error}</div>;
  if (!data.run) return <div className="panel px-4 py-8 text-sm text-slate-500">Run not found.</div>;

  return (
    <div className="space-y-4">
      <RunHeader run={data.run} onReload={reload} />
      <div className="flex flex-wrap gap-2">
        {tabs.map((item) => (
          <button key={item} className={`rounded-md border px-3 py-2 text-sm ${tab === item ? "border-slate-900 bg-slate-900 text-white" : "border-line bg-white"}`} onClick={() => setTab(item)}>
            {item}
          </button>
        ))}
      </div>
      {tab === "Build" && (
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
      {tab === "Preview" && (
        <div className="grid gap-4 xl:grid-cols-[1.5fr_1fr]">
          <div className="xl:col-span-2"><LivePreviewPanel files={data.files} tests={data.tests} artifacts={data.artifacts} run={data.run} /></div>
          <Panel title="Workflow Graph"><WorkflowGraph nodes={data.nodes} onSelect={setSelectedNode} /></Panel>
          <Panel title="Node Inspector"><NodeInspector node={selectedNode} events={data.events} artifacts={data.artifacts} /></Panel>
          <Panel title="Timeline"><Timeline events={data.events} /></Panel>
        </div>
      )}
      {tab === "Quality" && (
        <div className="grid gap-4 xl:grid-cols-2">
          <Panel title="Homologation Readiness"><HomologationReadinessPanel run={data.run} homologation={data.homologation} /></Panel>
          <Panel title="Quality Gates"><QualityGatesPanel gates={data.gates} /></Panel>
          <Panel title="Requirements and Criteria"><RequirementsPanel requirements={data.requirements} criteria={data.criteria} /></Panel>
          <Panel title="Traceability Matrix"><TraceabilityMatrix rows={data.traceability} /></Panel>
          <Panel title="Agent Factory Floor"><FactoryFloor run={data.run} agentStates={data.agentStates} agentMessages={data.agentMessages} workItems={data.workItems} artifacts={data.artifacts} events={data.events} /></Panel>
          <Panel title="Feedback"><FeedbackPanel run={data.run} feedback={data.feedback} onReload={reload} /></Panel>
        </div>
      )}
      {tab === "Files" && (
        <div className="grid gap-4">
          <Panel title="Files"><FilesPanel runId={runId} files={data.files} /></Panel>
          <Panel title="Diffs"><DiffsPanel diffs={data.diffs} /></Panel>
          <Panel title="Artifacts"><ArtifactsPanel artifacts={data.artifacts} /></Panel>
        </div>
      )}
      {tab === "Tests" && <Panel title="Test Reports"><TestsPanel tests={data.tests} /></Panel>}
      {tab === "Approval" && <Panel title="Approvals"><ApprovalsPanel run={data.run} approvals={data.homologation.approvals || []} onReload={reload} /></Panel>}
      {tab === "Logs" && <Panel title="Raw Event JSON"><RawLogsPanel events={data.events} /></Panel>}
    </div>
  );
}
