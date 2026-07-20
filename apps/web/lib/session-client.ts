export type SessionTenant = { id: string; name: string; status?: string };
export type SessionPrincipal = { name: string; email: string; role: string; tenant_id: string };
export type BrowserSession = {
  authenticated: boolean;
  active_tenant_id: string;
  me: SessionPrincipal;
  tenants: SessionTenant[];
};

export class SessionRequestError extends Error {
  constructor(public readonly status: number) {
    super(status === 401 ? "Authentication required" : "Session unavailable");
  }
}

let sessionRequest: Promise<BrowserSession> | null = null;

export function getBrowserSession(): Promise<BrowserSession> {
  if (!sessionRequest) {
    sessionRequest = fetch("/auth/session", { cache: "no-store" }).then(async (response) => {
      if (!response.ok) throw new SessionRequestError(response.status);
      return response.json() as Promise<BrowserSession>;
    });
  }
  return sessionRequest;
}
