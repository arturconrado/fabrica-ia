import type { ReactNode } from "react";
import { AlertCircle, Inbox, LoaderCircle, RotateCcw } from "lucide-react";


export function PageHeader({ eyebrow, title, description, actions }: { eyebrow?: string; title: string; description?: string; actions?: ReactNode }) {
  return (
    <header className="flex flex-col gap-4 lg:flex-row lg:items-end lg:justify-between">
      <div className="min-w-0">
        {eyebrow ? <p className="mb-2 text-xs font-semibold uppercase tracking-[0.18em] text-blue-400">{eyebrow}</p> : null}
        <h1 className="text-2xl font-semibold tracking-tight text-ink sm:text-3xl">{title}</h1>
        {description ? <p className="mt-2 max-w-3xl text-sm leading-6 text-[rgb(var(--muted))]">{description}</p> : null}
      </div>
      {actions ? <div className="flex shrink-0 flex-wrap gap-2">{actions}</div> : null}
    </header>
  );
}

export function Surface({ children, className = "" }: { children: ReactNode; className?: string }) {
  return <section className={`panel ${className}`}>{children}</section>;
}

export function LoadingState({ label = "Carregando dados reais…" }: { label?: string }) {
  return (
    <div className="panel min-h-52 overflow-hidden p-6" role="status" aria-live="polite">
      <div className="flex items-center gap-3">
        <span className="flex h-10 w-10 items-center justify-center rounded-xl bg-blue-500/10">
          <LoaderCircle className="h-5 w-5 animate-spin text-blue-400" aria-hidden="true" />
        </span>
        <div>
          <p className="text-sm font-semibold text-ink">{label}</p>
          <p className="mt-1 text-xs text-[rgb(var(--muted))]">Estamos consultando somente os dados autorizados deste cliente.</p>
        </div>
      </div>
      <div className="mt-6 grid gap-3 sm:grid-cols-3" aria-hidden="true">
        <div className="skeleton h-20 rounded-xl" />
        <div className="skeleton h-20 rounded-xl" />
        <div className="skeleton h-20 rounded-xl" />
      </div>
    </div>
  );
}

export function ErrorState({ message, onRetry, retryLabel = "Tentar novamente" }: { message: string; onRetry?: () => void; retryLabel?: string }) {
  return (
    <div className="panel flex min-h-36 items-start gap-4 border-red-500/40 p-5 text-sm" role="alert">
      <span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-red-500/10 text-red-300">
        <AlertCircle className="h-5 w-5" aria-hidden="true" />
      </span>
      <div className="min-w-0">
        <div className="font-semibold text-ink">Esta informação não carregou</div>
        <p className="mt-1 max-w-3xl break-words leading-6 text-red-200/80">{message}</p>
        <p className="mt-2 text-xs text-[rgb(var(--muted))]">Você pode tentar novamente sem recarregar ou perder o que já estava na tela.</p>
        {onRetry ? <button type="button" className="mt-4 inline-flex min-h-11 cursor-pointer items-center gap-2 rounded-lg border border-red-400/30 px-4 font-semibold text-red-100 transition-colors duration-200 hover:bg-red-500/10" onClick={onRetry}><RotateCcw className="h-4 w-4" />{retryLabel}</button> : null}
      </div>
    </div>
  );
}

export function EmptyState({ title, description, action }: { title: string; description?: string; action?: ReactNode }) {
  return (
    <div className="flex min-h-44 flex-col items-center justify-center rounded-xl border border-dashed border-line p-6 text-center">
      <Inbox className="h-7 w-7 text-[rgb(var(--muted))]" aria-hidden="true" />
      <h2 className="mt-3 text-sm font-semibold text-ink">{title}</h2>
      {description ? <p className="mt-1 max-w-lg text-sm text-[rgb(var(--muted))]">{description}</p> : null}
      {action ? <div className="mt-4">{action}</div> : null}
    </div>
  );
}

export function MetricCard({ label, value, detail, icon }: { label: string; value: ReactNode; detail?: string; icon?: ReactNode }) {
  return (
    <div className="panel min-h-32 p-4">
      <div className="flex items-center justify-between gap-3 text-sm text-[rgb(var(--muted))]">
        <span>{label}</span><span className="text-blue-400">{icon}</span>
      </div>
      <div className="mt-3 text-2xl font-semibold tracking-tight text-ink">{value}</div>
      {detail ? <p className="mt-2 text-xs leading-5 text-[rgb(var(--muted))]">{detail}</p> : null}
    </div>
  );
}

export function Provenance({ value }: { value: string }) {
  const labels: Record<string, string> = { real: "real", calculated: "calculado", estimated_from_real_usage: "estimado por uso real" };
  return <span className="inline-flex rounded-full border border-line bg-[rgb(var(--panel-soft))] px-2 py-1 text-[10px] font-semibold uppercase tracking-wide text-[rgb(var(--muted))]">{labels[value] || value}</span>;
}
