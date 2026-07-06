export const API_BASE = process.env.NEXT_PUBLIC_API_BASE_URL || "http://localhost:8000";

function authHeaders(): HeadersInit {
  const headers: Record<string, string> = {
    "X-Tenant-ID": process.env.NEXT_PUBLIC_DEFAULT_TENANT_ID || "local-dev"
  };
  const browserToken =
    typeof window !== "undefined" ? window.localStorage.getItem("asf_bearer_token") || "" : "";
  if (browserToken) headers.Authorization = `Bearer ${browserToken}`;
  return headers;
}

export async function apiGet<T>(path: string): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, { cache: "no-store", headers: authHeaders() });
  if (!response.ok) throw new Error(`${response.status} ${response.statusText}`);
  return response.json();
}

export async function apiPost<T>(path: string, body?: unknown): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, {
    method: "POST",
    headers: { "Content-Type": "application/json", ...authHeaders() },
    body: body ? JSON.stringify(body) : undefined
  });
  if (!response.ok) throw new Error(`${response.status} ${response.statusText}`);
  return response.json();
}
