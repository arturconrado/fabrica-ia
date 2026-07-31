export type SessionTenant = { id: string; name: string; status?: string };
export type OperatorProfile = "generalist" | "business_analyst" | "software_engineer" | "qa_quality" | "governance_risk";
export type SessionPrincipal = { name: string; email: string; role: string; tenant_id: string; operator_profile: OperatorProfile };
export type BrowserSession = {
  authenticated: boolean;
  active_tenant_id: string;
  me: SessionPrincipal;
  tenants: SessionTenant[];
};

export class SessionRequestError extends Error {
  constructor(public readonly status: number, message?: string) {
    super(message || (status === 401 ? "Authentication required" : "Session unavailable"));
    this.name = "SessionRequestError";
  }
}

let sessionRequest: Promise<BrowserSession> | null = null;
export const BROWSER_SESSION_RETRY_EVENT = "asf:browser-session-retry";

export function getBrowserSession(): Promise<BrowserSession> {
  if (!sessionRequest) {
    sessionRequest = fetch("/auth/session", {
      cache: "no-store",
      signal: AbortSignal.timeout(15_000),
    })
      .then(async (response) => {
        if (!response.ok) throw new SessionRequestError(response.status);
        return response.json() as Promise<BrowserSession>;
      })
      .catch((error: unknown) => {
        sessionRequest = null;
        if (error instanceof DOMException && ["AbortError", "TimeoutError"].includes(error.name)) {
          throw new SessionRequestError(504, "A sessão excedeu 15 segundos.");
        }
        throw error;
      });
  }
  return sessionRequest;
}

export function reloadBrowserSession(): Promise<BrowserSession> {
  sessionRequest = null;
  return getBrowserSession();
}

export function requestBrowserSessionRetry(): void {
  sessionRequest = null;
  window.dispatchEvent(new Event(BROWSER_SESSION_RETRY_EVENT));
}
