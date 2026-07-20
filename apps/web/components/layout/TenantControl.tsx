"use client";

import { useState } from "react";
import { Building2, ChevronDown, LoaderCircle } from "lucide-react";


type Tenant = { id: string; name: string; status?: string };

export function TenantControl({ tenants, activeTenantId }: { tenants: Tenant[]; activeTenantId: string }) {
  const [pending, setPending] = useState(false);
  const [error, setError] = useState("");

  async function select(tenantId: string) {
    if (tenantId === activeTenantId) return;
    setPending(true);
    setError("");
    const response = await fetch("/auth/tenant", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ tenant_id: tenantId })
    });
    if (!response.ok) {
      setPending(false);
      setError("Acesso negado");
      return;
    }
    window.location.reload();
  }

  const active = tenants.find((tenant) => tenant.id === activeTenantId);
  return (
    <div className="relative min-w-0">
      <label className="flex min-h-11 w-36 min-w-0 items-center gap-2 rounded-lg border border-line bg-[rgb(var(--panel))] px-3 text-xs text-ink sm:w-56">
        {pending ? <LoaderCircle className="h-4 w-4 shrink-0 animate-spin text-blue-400" /> : <Building2 className="h-4 w-4 shrink-0 text-blue-400" />}
        <span className="sr-only">Cliente ativo</span>
        <select className="min-w-0 flex-1 appearance-none truncate border-0 bg-transparent py-2 pr-5 text-xs font-medium" value={activeTenantId} onChange={(event) => void select(event.target.value)} disabled={pending} aria-describedby={error ? "tenant-error" : undefined}>
          {tenants.length ? tenants.map((tenant) => <option key={tenant.id} value={tenant.id}>{tenant.name}</option>) : <option value={activeTenantId}>{active?.name || activeTenantId}</option>}
        </select>
        <ChevronDown className="pointer-events-none -ml-5 h-3.5 w-3.5 shrink-0 text-[rgb(var(--muted))]" />
      </label>
      {error ? <span id="tenant-error" className="absolute right-0 top-full mt-1 text-[10px] text-red-300" role="alert">{error}</span> : null}
    </div>
  );
}
