export const API_BASE = process.env.NEXT_PUBLIC_API_BASE_URL || "/api-proxy";

export function commandKey(prefix: string): string {
  const suffix = typeof crypto !== "undefined" && "randomUUID" in crypto
    ? crypto.randomUUID()
    : `${Date.now()}-${Math.random().toString(16).slice(2)}`;
  return `${prefix}:${suffix}`;
}


function handleAuthentication(response: Response): void {
  if (response.status !== 401 || typeof window === "undefined") return;
  const returnTo = `${window.location.pathname}${window.location.search}`;
  window.location.assign(`/auth/login?returnTo=${encodeURIComponent(returnTo)}`);
}

async function errorMessage(response: Response): Promise<string> {
  try {
    const body = await response.json();
    const detail = body.detail || body;
    if (typeof detail === "string") return `${response.status} ${detail}`;
    if (detail.code || detail.message) return `${response.status} ${detail.code || response.statusText}: ${detail.message || response.statusText}`;
  } catch {
    // Fall back to status text below.
  }
  return `${response.status} ${response.statusText}`;
}

export async function apiGet<T>(path: string): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, { cache: "no-store", credentials: "same-origin" });
  handleAuthentication(response);
  if (!response.ok) throw new Error(await errorMessage(response));
  return response.json();
}

export async function apiGetText(path: string): Promise<string> {
  const response = await fetch(`${API_BASE}${path}`, { cache: "no-store", credentials: "same-origin" });
  handleAuthentication(response);
  if (!response.ok) throw new Error(await errorMessage(response));
  return response.text();
}

export async function apiPost<T>(path: string, body?: unknown, options?: { idempotencyKey?: string }): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      ...(options?.idempotencyKey ? { "Idempotency-Key": options.idempotencyKey } : {})
    },
    credentials: "same-origin",
    body: body ? JSON.stringify(body) : undefined
  });
  handleAuthentication(response);
  if (!response.ok) throw new Error(await errorMessage(response));
  return response.json();
}

export async function apiDelete<T>(path: string): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, {
    method: "DELETE",
    credentials: "same-origin"
  });
  handleAuthentication(response);
  if (!response.ok) throw new Error(await errorMessage(response));
  return response.json();
}
