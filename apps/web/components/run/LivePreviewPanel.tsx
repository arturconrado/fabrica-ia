import { CheckCircle2, FileCode2, Monitor, PackageCheck, PlayCircle } from "lucide-react";
import type { Dict } from "@/lib/types";
import { StatusBadge } from "@/lib/status";

export function LivePreviewPanel({
  files,
  tests,
  artifacts,
  run
}: {
  files: Dict[];
  tests: Dict[];
  artifacts: Dict[];
  run: Dict;
}) {
  const appFiles = files.filter((file) => String(file.file_path || "").includes("generated_app")).slice(0, 6);
  const finalTest = tests.find((test) => test.status === "passed") || tests[tests.length - 1];
  const hasPackage = artifacts.some((artifact) => String(artifact.name || "").includes("HOMOLOGATION"));

  return (
    <section className="rounded-lg border border-line bg-white">
      <div className="flex items-center justify-between border-b border-line px-4 py-3">
        <h2 className="flex items-center gap-2 text-sm font-semibold">
          <Monitor className="h-4 w-4" />
          Live Preview
        </h2>
        <StatusBadge status={run.status} />
      </div>
      <div className="grid gap-4 p-4 xl:grid-cols-[minmax(0,1fr)_260px]">
        <div className="overflow-hidden rounded-md border border-slate-800 bg-slate-950 text-white">
          <div className="flex items-center gap-2 border-b border-white/10 px-3 py-2">
            <span className="h-2.5 w-2.5 rounded-full bg-red-300" />
            <span className="h-2.5 w-2.5 rounded-full bg-amber-300" />
            <span className="h-2.5 w-2.5 rounded-full bg-emerald-300" />
            <span className="ml-2 truncate text-xs text-slate-400">generated_app / enterprise workspace</span>
          </div>
          <div className="grid min-h-[310px] gap-0 md:grid-cols-[190px_minmax(0,1fr)]">
            <div className="border-b border-white/10 bg-white/[0.03] p-3 md:border-b-0 md:border-r">
              <div className="text-xs uppercase text-slate-500">Modules</div>
              <div className="mt-3 space-y-2 text-sm">
                {["Customers", "Contracts", "Invoices", "Approvals"].map((item) => (
                  <div key={item} className="rounded border border-white/10 px-2 py-2 text-slate-200">{item}</div>
                ))}
              </div>
            </div>
            <div className="p-4">
              <div className="flex flex-wrap items-start justify-between gap-3">
                <div>
                  <div className="text-xl font-semibold">{run.project?.name || "Enterprise Build"}</div>
                  <div className="mt-1 text-sm text-slate-400">{run.current_phase || "factory pipeline"}</div>
                </div>
                <div className="rounded border border-emerald-400/30 bg-emerald-400/10 px-3 py-2 text-sm text-emerald-100">
                  HRS {run.homologation_readiness_score || 0}
                </div>
              </div>
              <div className="mt-5 grid gap-3 sm:grid-cols-3">
                {["Open invoices", "Active contracts", "Audit events"].map((metric, index) => (
                  <div key={metric} className="rounded border border-white/10 bg-white/[0.04] p-3">
                    <div className="text-2xl font-semibold">{[18, 42, 128][index]}</div>
                    <div className="mt-1 text-xs text-slate-400">{metric}</div>
                  </div>
                ))}
              </div>
              <div className="mt-5 rounded border border-white/10 bg-white/[0.04] p-3">
                <div className="mb-3 flex items-center gap-2 text-sm">
                  <PlayCircle className="h-4 w-4 text-cyan-200" />
                  Build evidence
                </div>
                <div className="space-y-2 text-sm text-slate-300">
                  <EvidenceLine label="Initial failing pytest" done={tests.some((test) => test.status === "failed")} />
                  <EvidenceLine label="Final passing pytest" done={Boolean(finalTest?.status === "passed")} />
                  <EvidenceLine label="Homologation package" done={hasPackage} />
                </div>
              </div>
            </div>
          </div>
        </div>

        <aside className="space-y-3">
          <div className="rounded-md border border-line bg-slate-50 p-3">
            <div className="flex items-center gap-2 text-sm font-medium">
              <FileCode2 className="h-4 w-4" />
              Source
            </div>
            <div className="mt-3 space-y-2">
              {appFiles.map((file) => (
                <div key={`${file.id}-${file.file_path}`} className="truncate rounded border border-line bg-white px-2 py-2 text-xs">
                  {file.file_path}
                </div>
              ))}
              {!appFiles.length && <div className="text-sm text-slate-500">Waiting for generated files.</div>}
            </div>
          </div>
          <div className="rounded-md border border-line bg-slate-50 p-3">
            <div className="flex items-center gap-2 text-sm font-medium">
              <PackageCheck className="h-4 w-4" />
              Release
            </div>
            <div className="mt-3 space-y-2 text-sm">
              <ReleaseLine label="Tests" value={finalTest ? `${finalTest.passed_count || 0} passed` : "pending"} />
              <ReleaseLine label="Artifacts" value={String(artifacts.length)} />
              <ReleaseLine label="Approval" value={run.status === "waiting_for_human" ? "waiting" : run.status} />
            </div>
          </div>
        </aside>
      </div>
    </section>
  );
}

function EvidenceLine({ label, done }: { label: string; done: boolean }) {
  return (
    <div className="flex items-center gap-2">
      <CheckCircle2 className={`h-4 w-4 ${done ? "text-emerald-300" : "text-slate-600"}`} />
      <span>{label}</span>
    </div>
  );
}

function ReleaseLine({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex items-center justify-between rounded border border-line bg-white px-2 py-2">
      <span className="text-slate-500">{label}</span>
      <span className="font-medium">{value}</span>
    </div>
  );
}
