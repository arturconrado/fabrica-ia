import Link from "next/link";

import { PageHeader, Surface } from "@/components/common/OperationalUI";


const groups = [
  {
    title: "Execução técnica",
    description: "Runs, runtime, agentes e componentes da fábrica.",
    links: [
      ["Runs", "/runs"],
      ["Runtime", "/runtime"],
      ["Agentes", "/agents"],
      ["Componentes", "/components"],
      ["Batches", "/batches"],
    ],
  },
  {
    title: "IA e conhecimento",
    description: "Proveniência, bases, conectores e aprendizado supervisionado.",
    links: [
      ["Atividade de IA", "/ai-activity"],
      ["Conhecimento", "/knowledge"],
      ["Conectores", "/connectors"],
      ["Aprendizado", "/learning"],
    ],
  },
  {
    title: "Portfólio técnico",
    description: "Deep links preservados para investigação e administração.",
    links: [
      ["Nova missão", "/mvp-factory"],
      ["MVP runs", "/mvp-runs"],
      ["Projetos", "/projects"],
      ["Programas", "/programs"],
      ["Oportunidades", "/opportunities"],
      ["Catálogo", "/service-catalog"],
      ["Contratos", "/admin/contracts"],
      ["Tenants e membros", "/admin/tenants"],
    ],
  },
] as const;

export default function DiagnosticsPage() {
  return (
    <div className="space-y-6">
      <PageHeader
        eyebrow="Apoio operacional"
        title="Diagnóstico"
        description="Detalhes técnicos ficam aqui para não competir com a próxima ação segura. As URLs anteriores continuam válidas."
      />
      <div className="grid gap-4 lg:grid-cols-3">
        {groups.map((group) => (
          <Surface key={group.title} className="p-5">
            <h2 className="text-base font-semibold text-ink">{group.title}</h2>
            <p className="mt-2 text-sm leading-6 text-[rgb(var(--muted))]">{group.description}</p>
            <div className="mt-4 grid gap-2">
              {group.links.map(([label, href]) => (
                <Link key={href} href={href} className="flex min-h-11 items-center rounded-lg border border-line px-3 text-sm text-ink hover:border-blue-500/40 hover:bg-blue-500/10">
                  {label}
                </Link>
              ))}
            </div>
          </Surface>
        ))}
      </div>
    </div>
  );
}
