import Link from "next/link";
import { Boxes, BrainCircuit, ClipboardCheck, Factory, ServerCog, ShieldCheck, Zap } from "lucide-react";
import { AuthTokenControl } from "@/components/layout/AuthTokenControl";

export function Shell({ children }: { children: React.ReactNode }) {
  return (
    <div className="min-h-screen bg-[#f4f7f8]">
      <header className="sticky top-0 z-20 border-b border-slate-200 bg-white/95 backdrop-blur">
        <div className="mx-auto flex max-w-[1440px] items-center justify-between gap-4 px-5 py-3">
          <Link href="/" className="flex items-center gap-2 font-semibold">
            <span className="flex h-8 w-8 items-center justify-center rounded-md bg-slate-950 text-cyan-200">
              <Factory className="h-4 w-4" />
            </span>
            <span className="hidden sm:inline">ASF Builder</span>
          </Link>
          <nav className="flex min-w-0 items-center gap-1 text-sm text-slate-600">
            <span className="hidden items-center gap-1 rounded-md border border-line px-2 py-1 text-xs text-slate-500 lg:inline-flex">
              <ShieldCheck className="h-3.5 w-3.5" /> Enterprise
            </span>
            <span className="hidden rounded-md border border-line px-2 py-1 text-xs text-slate-500 md:inline-flex">
              Workspace {process.env.NEXT_PUBLIC_DEFAULT_TENANT_ID || "local-dev"}
            </span>
            <span className="hidden items-center gap-1 rounded-md border border-cyan-200 bg-cyan-50 px-2 py-1 text-xs text-cyan-900 xl:inline-flex">
              <Zap className="h-3.5 w-3.5" /> 4.2k credits
            </span>
            <AuthTokenControl />
            <Link className="flex items-center gap-1 rounded-md px-3 py-2 hover:bg-slate-100" href="/projects">
              <ClipboardCheck className="h-4 w-4" /> Projects
            </Link>
            <Link className="flex items-center gap-1 rounded-md px-3 py-2 hover:bg-slate-100" href="/batches">
              <Boxes className="h-4 w-4" /> Batches
            </Link>
            <Link className="flex items-center gap-1 rounded-md px-3 py-2 hover:bg-slate-100" href="/learning">
              <BrainCircuit className="h-4 w-4" /> Learning
            </Link>
            <Link className="flex items-center gap-1 rounded-md px-3 py-2 hover:bg-slate-100" href="/runtime">
              <ServerCog className="h-4 w-4" /> Runtime
            </Link>
          </nav>
        </div>
      </header>
      <main className="mx-auto max-w-7xl px-5 py-5">{children}</main>
    </div>
  );
}
