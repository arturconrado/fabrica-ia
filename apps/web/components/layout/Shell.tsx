"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useCallback, useEffect, useMemo, useState } from "react";
import {
  Activity,
  Award,
  ClipboardCheck,
  Factory,
  Gauge,
  Handshake,
  ListTodo,
  LibraryBig,
  LogOut,
  Menu,
  Moon,
  PanelLeftClose,
  PanelLeftOpen,
  ShieldCheck,
  Sun,
  Users,
  X
} from "lucide-react";

import { TenantControl } from "@/components/layout/TenantControl";
import { apiPatch } from "@/lib/api";
import { BROWSER_SESSION_RETRY_EVENT, getBrowserSession, reloadBrowserSession, requestBrowserSessionRetry, SessionRequestError, type BrowserSession, type OperatorProfile } from "@/lib/session-client";


type NavItem = { label: string; href: string; icon: React.ComponentType<{ className?: string }> };
type NavGroup = { label: string; items: NavItem[] };

const reviewerRoles = new Set(["client_sponsor", "process_owner", "reviewer", "auditor"]);
const ownerNavigation: NavGroup[] = [
  {
    label: "Trabalho",
    items: [
      { label: "Hoje", href: "/dashboard", icon: Gauge },
      { label: "Clientes", href: "/clients", icon: Users },
      { label: "Portfólio", href: "/service-catalog", icon: LibraryBig },
      { label: "Engajamentos", href: "/engagements", icon: Handshake },
      { label: "Operação", href: "/work-queue", icon: ListTodo },
      { label: "Entregas", href: "/deliverables", icon: Award },
    ]
  },
  {
    label: "Apoio",
    items: [
      { label: "Diagnóstico", href: "/diagnostics", icon: Activity },
    ]
  }
];
const engagementManagerNavigation: NavGroup[] = [
  {
    label: "Decisões",
    items: [
      { label: "Minha fila", href: "/dashboard", icon: ClipboardCheck },
      { label: "Portfólio", href: "/service-catalog", icon: LibraryBig },
      { label: "Engajamentos", href: "/engagements", icon: Handshake },
      { label: "Entregas", href: "/deliverables", icon: Award },
      { label: "Evidências", href: "/evidence", icon: Activity },
    ]
  }
];
const reviewerNavigation: NavGroup[] = [
  {
    label: "Revisão",
    items: [
      { label: "Minha fila", href: "/dashboard", icon: ClipboardCheck },
      { label: "Entregas", href: "/deliverables", icon: Award },
      { label: "Evidências", href: "/evidence", icon: Activity },
    ]
  }
];

const routeTitles: Record<string, string> = {
  dashboard: "Próxima ação",
  clients: "Clientes",
  "work-queue": "Fila e capacidade",
  "service-catalog": "Produtos e serviços",
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
  diagnostics: "Diagnóstico",
  admin: "Administração"
};

function activeRoute(pathname: string, href: string) {
  return pathname === href || pathname.startsWith(`${href}/`);
}

function roleLabel(role = "") {
  const labels: Record<string, string> = {
    owner: "Operador",
    super_admin: "Administrador",
    engagement_manager: "VP · Gestor de engajamentos",
    client_sponsor: "Sponsor do cliente",
    process_owner: "Responsável pelo processo",
    reviewer: "Revisor",
    auditor: "Auditor",
  };
  return labels[role] || role.replaceAll("_", " ");
}

const operatorProfiles: Array<{ value: OperatorProfile; label: string }> = [
  { value: "generalist", label: "Visão geral" },
  { value: "business_analyst", label: "Analista de negócio" },
  { value: "software_engineer", label: "Engenharia de software" },
  { value: "qa_quality", label: "QA e qualidade" },
  { value: "governance_risk", label: "Governança e risco" },
];

export function Shell({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const [session, setSession] = useState<BrowserSession | null>(null);
  const [sessionError, setSessionError] = useState("");
  const [sessionLoading, setSessionLoading] = useState(true);
  const [mobileOpen, setMobileOpen] = useState(false);
  const [collapsed, setCollapsed] = useState(false);
  const [theme, setTheme] = useState<"dark" | "light">("dark");
  const [profileBusy, setProfileBusy] = useState(false);

  const loadSession = useCallback(() => {
    setSessionLoading(true);
    setSessionError("");
    getBrowserSession()
      .then((value) => {
        setSession(value);
        setSessionLoading(false);
      })
      .catch((error: Error) => {
        if (error instanceof SessionRequestError && error.status === 401) {
          window.location.assign(`/auth/login?returnTo=${encodeURIComponent(`${window.location.pathname}${window.location.search}`)}`);
          return;
        }
        setSession(null);
        setSessionError(error.message || "Sessão temporariamente indisponível.");
        setSessionLoading(false);
      });
  }, []);

  useEffect(() => {
    const savedTheme = window.localStorage.getItem("asf_theme") === "light" ? "light" : "dark";
    setTheme(savedTheme);
    document.documentElement.dataset.theme = savedTheme;
    setCollapsed(window.localStorage.getItem("asf_sidebar_collapsed") === "true");
    const retry = () => loadSession();
    window.addEventListener(BROWSER_SESSION_RETRY_EVENT, retry);
    loadSession();
    return () => window.removeEventListener(BROWSER_SESSION_RETRY_EVENT, retry);
  }, [loadSession]);

  useEffect(() => setMobileOpen(false), [pathname]);

  const reviewer = Boolean(session && reviewerRoles.has(session.me.role));
  const engagementManager = session?.me.role === "engagement_manager";
  const visibleNavigation = useMemo(
    () => engagementManager ? engagementManagerNavigation : reviewer ? reviewerNavigation : ownerNavigation,
    [engagementManager, reviewer],
  );
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

  async function changeOperatorProfile(operatorProfile: OperatorProfile) {
    setProfileBusy(true);
    setSessionError("");
    try {
      await apiPatch("/auth/me/operator-profile", { operator_profile: operatorProfile });
      setSession(await reloadBrowserSession());
    } catch (error) {
      setSessionError(error instanceof Error ? error.message : "Não foi possível alterar a visão profissional.");
    } finally {
      setProfileBusy(false);
    }
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
            {!collapsed ? <div className="min-w-0"><div className="truncate text-xs font-semibold text-ink">{session?.me.name || (sessionError ? "Sessão indisponível" : "Conectando…")}</div><div className="truncate text-[11px] text-[rgb(var(--muted))]">{session ? roleLabel(session.me.role) : (sessionError ? "tente novamente" : "sessão segura")}</div></div> : null}
          </div>
          {!collapsed && session && !engagementManager && !reviewer ? <label className="mt-3 grid gap-1 text-[10px] font-semibold uppercase tracking-[0.12em] text-[rgb(var(--muted))]">Visão profissional<select value={session.me.operator_profile} disabled={profileBusy} onChange={(event) => void changeOperatorProfile(event.target.value as OperatorProfile)} className="min-h-11 rounded-lg border px-2 text-xs font-normal normal-case tracking-normal text-ink disabled:opacity-50">{operatorProfiles.map((profile) => <option key={profile.value} value={profile.value}>{profile.label}</option>)}</select></label> : null}
          {!collapsed && session ? <a href="/auth/logout" className="mt-3 flex min-h-11 items-center justify-center gap-2 rounded-lg border border-line text-xs text-[rgb(var(--muted))] hover:bg-[rgb(var(--panel-raised))] hover:text-ink"><LogOut className="h-4 w-4" /> Encerrar sessão</a> : null}
          {!collapsed && sessionError ? <button type="button" className="mt-3 min-h-11 w-full rounded-lg border border-amber-400/30 px-3 text-xs font-semibold text-amber-200" onClick={requestBrowserSessionRetry}>Tentar novamente</button> : null}
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

      <div className={`min-h-screen ${collapsed ? "lg:pl-[76px]" : "lg:pl-[270px]"}`}>
        <header className="sticky top-0 z-30 flex min-h-16 max-w-full items-center justify-between gap-3 overflow-x-clip border-b border-line bg-[rgba(7,11,20,0.82)] px-4 backdrop-blur-xl sm:px-6">
          <div className="flex min-w-0 flex-1 items-center gap-3">
            <button className="flex h-11 w-11 shrink-0 items-center justify-center rounded-lg border border-line text-[rgb(var(--muted))] lg:hidden" onClick={() => setMobileOpen(true)} aria-label="Abrir menu"><Menu className="h-5 w-5" /></button>
            <div className="hidden min-w-0 sm:block"><div className="truncate text-sm font-semibold text-ink">{title}</div><div className="hidden truncate text-[11px] text-[rgb(var(--muted))] sm:block">Operação segura, rastreável e orientada à próxima ação</div></div>
          </div>
          <div className="flex min-w-0 shrink-0 items-center gap-2">
            {session ? <TenantControl tenants={session.tenants} activeTenantId={session.active_tenant_id} /> : sessionLoading ? <div className="skeleton h-11 w-36 rounded-lg" role="status" aria-label="Carregando cliente" /> : <button type="button" className="min-h-11 rounded-lg border border-amber-400/30 px-3 text-xs font-semibold text-amber-200" onClick={requestBrowserSessionRetry}>Reconectar</button>}
            <button className="flex h-11 w-11 shrink-0 items-center justify-center rounded-lg border border-line text-[rgb(var(--muted))] hover:bg-[rgb(var(--panel-raised))] hover:text-ink" onClick={toggleTheme} aria-label={theme === "dark" ? "Ativar tema claro" : "Ativar tema escuro"}>{theme === "dark" ? <Sun className="h-4 w-4" /> : <Moon className="h-4 w-4" />}</button>
          </div>
        </header>
        <main id="conteudo-principal" className="mx-auto w-full max-w-[1600px] px-4 py-5 sm:px-6 sm:py-7" tabIndex={-1}>{children}</main>
      </div>
    </div>
  );
}
