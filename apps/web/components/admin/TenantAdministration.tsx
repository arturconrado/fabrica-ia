"use client";

import { useEffect, useState } from "react";
import { Building2, ShieldCheck, Users } from "lucide-react";

import { EmptyState, ErrorState, LoadingState, MetricCard, PageHeader, Surface } from "@/components/common/OperationalUI";
import { apiGet } from "@/lib/api";
import { fmtDate } from "@/lib/format";
import { getBrowserSession, type BrowserSession } from "@/lib/session-client";
import { StatusBadge } from "@/lib/status";


type Tenant = { id: string; name: string; slug: string; status: string; created_at: string };
type Member = { membership: { id: string; role: string; status: string; created_at: string }; user: { id: string; name: string; email: string } };
export function TenantAdministration() {
  const [tenants, setTenants] = useState<Tenant[]>([]);
  const [members, setMembers] = useState<Member[]>([]);
  const [session, setSession] = useState<BrowserSession | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  useEffect(() => {
    Promise.all([
      getBrowserSession(),
      apiGet<Tenant[]>("/tenants")
    ])
      .then(async ([sessionData, tenantRows]) => {
        setSession(sessionData);
        setTenants(tenantRows);
        setMembers(await apiGet<Member[]>(`/tenants/${sessionData.active_tenant_id}/members`));
      })
      .catch((reason: Error) => setError(reason.message))
      .finally(() => setLoading(false));
  }, []);

  if (loading) return <LoadingState label="Carregando memberships autorizadas…" />;
  if (error) return <ErrorState message={error} />;
  return (
    <div className="space-y-6">
      <PageHeader eyebrow="Administração" title="Clientes e acessos" description="Onboarding produtivo continua assistido; esta tela apenas apresenta tenants e memberships reais." />
      <div className="grid gap-3 sm:grid-cols-3">
        <MetricCard label="Tenants acessíveis" value={tenants.length} detail="Limitados às memberships do operador" icon={<Building2 className="h-5 w-5" />} />
        <MetricCard label="Membros no tenant ativo" value={members.length} detail="Identidades provisionadas no OIDC" icon={<Users className="h-5 w-5" />} />
        <MetricCard label="Seu papel" value={session?.me.role || "—"} detail="Autorização aplicada no servidor" icon={<ShieldCheck className="h-5 w-5" />} />
      </div>
      <div className="grid gap-5 xl:grid-cols-2">
        <Surface><div className="border-b border-line px-5 py-4 text-sm font-semibold text-ink">Tenants</div>{tenants.length ? <div className="divide-y divide-line">{tenants.map((tenant) => <div key={tenant.id} className={`flex min-h-20 items-center justify-between gap-4 px-5 py-4 ${tenant.id === session?.active_tenant_id ? "bg-blue-500/[0.06]" : ""}`}><div><div className="text-sm font-semibold text-ink">{tenant.name}</div><div className="mt-1 text-xs text-[rgb(var(--muted))]">{tenant.slug} · {fmtDate(tenant.created_at)}</div></div><StatusBadge status={tenant.status} /></div>)}</div> : <div className="p-5"><EmptyState title="Nenhum tenant" description="Execute o onboarding assistido para provisionar o primeiro cliente." /></div>}</Surface>
        <Surface><div className="border-b border-line px-5 py-4 text-sm font-semibold text-ink">Membros do tenant ativo</div>{members.length ? <div className="divide-y divide-line">{members.map((row) => <div key={row.membership.id} className="flex min-h-20 items-center justify-between gap-4 px-5 py-4"><div><div className="text-sm font-semibold text-ink">{row.user.name || row.user.email}</div><div className="mt-1 text-xs text-[rgb(var(--muted))]">{row.user.email || "E-mail não informado"} · {row.membership.role}</div></div><StatusBadge status={row.membership.status} /></div>)}</div> : <div className="p-5"><EmptyState title="Nenhum membro" description="As memberships provisionadas aparecerão aqui." /></div>}</Surface>
      </div>
    </div>
  );
}
