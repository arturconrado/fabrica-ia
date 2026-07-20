"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useMemo, useState } from "react";
import {
  Activity,
  Award,
  Boxes,
  BookOpen,
  Bot,
  BriefcaseBusiness,
  ClipboardCheck,
  Database,
  FileCheck2,
  Factory,
  FolderKanban,
  Gauge,
  Handshake,
  Library,
  ListTodo,
  LogOut,
  Menu,
  Moon,
  Network,
  PanelLeftClose,
  PanelLeftOpen,
  ServerCog,
  ShieldCheck,
  Sparkles,
  Sun,
  Users,
  X
} from "lucide-react";

import { TenantControl } from "@/components/layout/TenantControl";
import { getBrowserSession, SessionRequestError, type BrowserSession } from "@/lib/session-client";


type NavItem = { label: string; href: string; icon: React.ComponentType<{ className?: string }>; operatorOnly?: boolean; adminOnly?: boolean };
type NavGroup = { label: string; items: NavItem[] };

const reviewerRoles = new Set(["client_sponsor", "process_owner", "reviewer", "auditor"]);
const administrativeRoles = new Set(["owner", "super_admin", "tenant_admin", "admin"]);
const navigation: NavGroup[] = [
  {
    label: "Carteira",
    items: [
      { label: "Visão geral", href: "/dashboard", icon: Gauge },
      { label: "Clientes", href: "/clients", icon: Users, operatorOnly: true },
      { label: "Fila e capacidade", href: "/work-queue", icon: ListTodo, operatorOnly: true }
    ]
  },
  {
    label: "Serviços",
    items: [
      { label: "Catálogo", href: "/service-catalog", icon: Library, operatorOnly: true },
      { label: "Engajamentos", href: "/engagements", icon: Handshake, operatorOnly: true },
      { label: "Entregáveis", href: "/deliverables", icon: Award }
    ]
  },
  {
    label: "Execução",
    items: [
      { label: "Nova missão", href: "/mvp-factory", icon: Sparkles, operatorOnly: true },
      { label: "Runs", href: "/runs", icon: Activity, operatorOnly: true },
      { label: "Aprovações", href: "/approvals", icon: ClipboardCheck },
      { label: "Conhecimento", href: "/knowledge", icon: BookOpen, operatorOnly: true },
      { label: "Evidências", href: "/evidence", icon: FileCheck2 }
    ]
  },
  {
    label: "Equipe AI",
    items: [
      { label: "Agent Studio", href: "/agents", icon: Bot, operatorOnly: true },
      { label: "Atividade de IA", href: "/ai-activity", icon: Activity, operatorOnly: true },
      { label: "Aprendizado", href: "/learning", icon: Database, operatorOnly: true }
    ]
  },
  {
    label: "Operações técnicas",
    items: [
      { label: "Projetos", href: "/projects", icon: FolderKanban, operatorOnly: true },
      { label: "Programas", href: "/programs", icon: BriefcaseBusiness, operatorOnly: true },
      { label: "Oportunidades", href: "/opportunities", icon: Sparkles, operatorOnly: true },
      { label: "Componentes", href: "/components", icon: Boxes, operatorOnly: true },
      { label: "MVP runs", href: "/mvp-runs", icon: Factory, operatorOnly: true },
      { label: "Runtime", href: "/runtime", icon: ServerCog, operatorOnly: true },
      { label: "Conectores", href: "/connectors", icon: Network, operatorOnly: true },
      { label: "Batches", href: "/batches", icon: Boxes, operatorOnly: true }
    ]
  },
  {
    label: "Administração",
    items: [
      { label: "Contratos e entitlements", href: "/admin/contracts", icon: BriefcaseBusiness, operatorOnly: true, adminOnly: true },
      { label: "Tenants e membros", href: "/admin/tenants", icon: Users, operatorOnly: true, adminOnly: true }
    ]
  }
];

const routeTitles: Record<string, string> = {
  dashboard: "Command Center",
  clients: "Clientes",
  "work-queue": "Fila e capacidade",
  "service-catalog": "Catálogo de serviços",
  engagements: "Engajamentos",
  "mvp-factory": "Nova missão",
  projects: "Projetos",
  programs: "Programas",
  opportunities: "Oportunidades",
  components: "Componentes",
  "mvp-runs": "MVP runs",
  runs: "Cockpit da missão",
  approvals: "Aprovações",
  knowledge: "Knowledge & RAG",
  evidence: "Evidências",
  deliverables: "Entregas",
  agents: "Agent Studio",
  "ai-activity": "Atividade de IA",
  runtime: "Runtime",
  connectors: "Conectores",
  batches: "Execuções em lote",
  learning: "Aprendizado",
  admin: "Administração"
};

function activeRoute(pathname: string, href: string) {
  return pathname === href || pathname.startsWith(`${href}/`);
}

export function Shell({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const [session, setSession] = useState<BrowserSession | null>(null);
  const [mobileOpen, setMobileOpen] = useState(false);
  const [collapsed, setCollapsed] = useState(false);
  const [theme, setTheme] = useState<"dark" | "light">("dark");

  useEffect(() => {
    const savedTheme = window.localStorage.getItem("asf_theme") === "light" ? "light" : "dark";
    setTheme(savedTheme);
    document.documentElement.dataset.theme = savedTheme;
    setCollapsed(window.localStorage.getItem("asf_sidebar_collapsed") === "true");
    getBrowserSession()
      .then(setSession)
      .catch((error: Error) => {
        if (error instanceof SessionRequestError && error.status === 401) {
          window.location.assign(`/auth/login?returnTo=${encodeURIComponent(`${window.location.pathname}${window.location.search}`)}`);
          return;
        }
        setSession(null);
      });
  }, []);

  useEffect(() => setMobileOpen(false), [pathname]);

  const reviewer = Boolean(session && reviewerRoles.has(session.me.role));
  const administrator = Boolean(session && administrativeRoles.has(session.me.role));
  const visibleNavigation = useMemo(() => navigation
    .map((group) => ({ ...group, items: group.items.filter((item) => (!item.operatorOnly || !reviewer) && (!item.adminOnly || administrator)) }))
    .filter((group) => group.items.length), [administrator, reviewer]);
  const title = routeTitles[pathname.split("/").filter(Boolean)[0] || "dashboard"] || "Factory OS";

  function toggleTheme() {
    const next = theme === "dark" ? "light" : "dark";
    setTheme(next);
    document.documentElement.dataset.theme = next;
    window.localStorage.setItem("asf_theme", next);
  }

  function toggleCollapsed() {
    const next = !collapsed;
    setCollapsed(next);
    window.localStorage.setItem("asf_sidebar_collapsed", String(next));
  }

  const sidebar = (
    <div className="flex h-full flex-col">
      <div className={`flex h-16 items-center border-b border-line px-4 ${collapsed ? "justify-center" : "justify-between"}`}>
        <Link href="/dashboard" className="flex min-h-11 items-center gap-3 rounded-lg text-ink" aria-label="Factory OS — Visão geral">
          <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-xl bg-blue-500 text-white shadow-lg shadow-blue-500/20"><Factory className="h-5 w-5" /></span>
          {!collapsed ? <span><span className="block text-sm font-semibold">Factory OS</span><span className="block text-[10px] uppercase tracking-[0.16em] text-[rgb(var(--muted))]">Agentic operations</span></span> : null}
        </Link>
        {!collapsed ? <button className="hidden h-11 w-11 items-center justify-center rounded-lg text-[rgb(var(--muted))] hover:bg-[rgb(var(--panel-raised))] lg:flex" onClick={toggleCollapsed} aria-label="Recolher menu"><PanelLeftClose className="h-4 w-4" /></button> : null}
      </div>

      <nav className="flex-1 overflow-y-auto px-3 py-4" aria-label="Navegação principal">
        {collapsed ? <button className="mb-3 hidden h-11 w-full items-center justify-center rounded-lg text-[rgb(var(--muted))] hover:bg-[rgb(var(--panel-raised))] lg:flex" onClick={toggleCollapsed} aria-label="Expandir menu"><PanelLeftOpen className="h-4 w-4" /></button> : null}
        <div className="space-y-5">
          {visibleNavigation.map((group) => (
            <div key={group.label}>
              {!collapsed ? <div className="mb-1.5 px-3 text-[10px] font-semibold uppercase tracking-[0.16em] text-[rgb(var(--muted))]">{group.label}</div> : null}
              <div className="space-y-1">
                {group.items.map((item) => {
                  const Icon = item.icon;
                  const active = activeRoute(pathname, item.href);
                  return (
                    <Link
                      key={item.href}
                      href={item.href}
                      title={collapsed ? item.label : undefined}
                      aria-current={active ? "page" : undefined}
                      className={`flex min-h-11 items-center rounded-lg text-sm transition-colors ${collapsed ? "justify-center px-2" : "gap-3 px-3"} ${active ? "bg-blue-500/15 font-semibold text-blue-300 ring-1 ring-inset ring-blue-500/25" : "text-[rgb(var(--muted))] hover:bg-[rgb(var(--panel-raised))] hover:text-ink"}`}
                    >
                      <Icon className="h-[18px] w-[18px] shrink-0" />{!collapsed ? item.label : null}
                    </Link>
                  );
                })}
              </div>
            </div>
          ))}
        </div>
      </nav>

      <div className="border-t border-line p-3">
        <div className={`rounded-xl bg-[rgb(var(--panel-soft))] p-3 ${collapsed ? "flex justify-center" : ""}`}>
          <div className="flex items-center gap-3">
            <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-full bg-emerald-500/15 text-emerald-300"><ShieldCheck className="h-4 w-4" /></span>
            {!collapsed ? <div className="min-w-0"><div className="truncate text-xs font-semibold text-ink">{session?.me.name || "Conectando…"}</div><div className="truncate text-[11px] text-[rgb(var(--muted))]">{session?.me.role || "sessão OIDC"}</div></div> : null}
          </div>
          {!collapsed && session ? <a href="/auth/logout" className="mt-3 flex min-h-11 items-center justify-center gap-2 rounded-lg border border-line text-xs text-[rgb(var(--muted))] hover:bg-[rgb(var(--panel-raised))] hover:text-ink"><LogOut className="h-4 w-4" /> Encerrar sessão</a> : null}
        </div>
      </div>
    </div>
  );

  return (
    <div className="min-h-screen bg-canvas text-ink">
      <a className="skip-link" href="#conteudo-principal">Pular para o conteúdo</a>
      {mobileOpen ? <button className="fixed inset-0 z-40 bg-black/60 lg:hidden" aria-label="Fechar menu" onClick={() => setMobileOpen(false)} /> : null}
      <aside className={`fixed inset-y-0 left-0 z-50 border-r border-line bg-[rgb(var(--panel))] transition-[width,transform] duration-200 ${collapsed ? "w-[76px]" : "w-[270px]"} ${mobileOpen ? "translate-x-0" : "-translate-x-full lg:translate-x-0"}`}>
        <button className="absolute right-3 top-3 z-10 flex h-11 w-11 items-center justify-center rounded-lg text-[rgb(var(--muted))] lg:hidden" onClick={() => setMobileOpen(false)} aria-label="Fechar menu"><X className="h-5 w-5" /></button>
        {sidebar}
      </aside>

      <div className={`min-h-screen transition-[padding] duration-200 ${collapsed ? "lg:pl-[76px]" : "lg:pl-[270px]"}`}>
        <header className="sticky top-0 z-30 flex min-h-16 max-w-full items-center justify-between gap-3 overflow-x-clip border-b border-line bg-[rgba(7,11,20,0.82)] px-4 backdrop-blur-xl sm:px-6">
          <div className="flex min-w-0 flex-1 items-center gap-3">
            <button className="flex h-11 w-11 shrink-0 items-center justify-center rounded-lg border border-line text-[rgb(var(--muted))] lg:hidden" onClick={() => setMobileOpen(true)} aria-label="Abrir menu"><Menu className="h-5 w-5" /></button>
            <div className="hidden min-w-0 sm:block"><div className="truncate text-sm font-semibold text-ink">{title}</div><div className="hidden truncate text-[11px] text-[rgb(var(--muted))] sm:block">Dados do ledger e das projeções operacionais</div></div>
          </div>
          <div className="flex min-w-0 shrink-0 items-center gap-2">
            {session ? <TenantControl tenants={session.tenants} activeTenantId={session.active_tenant_id} /> : <div className="skeleton h-11 w-36 rounded-lg" role="status" aria-label="Carregando cliente" />}
            <button className="flex h-11 w-11 shrink-0 items-center justify-center rounded-lg border border-line text-[rgb(var(--muted))] hover:bg-[rgb(var(--panel-raised))] hover:text-ink" onClick={toggleTheme} aria-label={theme === "dark" ? "Ativar tema claro" : "Ativar tema escuro"}>{theme === "dark" ? <Sun className="h-4 w-4" /> : <Moon className="h-4 w-4" />}</button>
          </div>
        </header>
        <main id="conteudo-principal" className="mx-auto w-full max-w-[1600px] px-4 py-5 sm:px-6 sm:py-7" tabIndex={-1}>{children}</main>
      </div>
    </div>
  );
}
