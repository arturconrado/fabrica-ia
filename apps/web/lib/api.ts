export const API_BASE = process.env.NEXT_PUBLIC_API_BASE_URL || "/api-proxy";
const READ_TIMEOUT_MS = 15_000;
const COMMAND_TIMEOUT_MS = 120_000;

export class ApiRequestError extends Error {
  constructor(
    message: string,
    public readonly status: number,
    public readonly code = "REQUEST_FAILED",
    public readonly correlationId = "",
    public readonly outcomeUnconfirmed = false,
  ) {
    super(message);
    this.name = "ApiRequestError";
  }
}

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

async function responseError(response: Response): Promise<ApiRequestError> {
  let code = "REQUEST_FAILED";
  let message = `${response.status} ${response.statusText}`;
  let correlationId = response.headers.get("x-correlation-id") || "";
  try {
    const body = await response.json();
    const detail = body.detail || body;
    if (typeof detail === "string") message = `${response.status} ${detail}`;
    if (detail.code || detail.message) {
      code = detail.code || code;
      correlationId = detail.correlation_id || correlationId;
      message = `${response.status} ${code}: ${detail.message || response.statusText}`;
    }
  } catch {
    // Keep the status-based fallback.
  }
  return new ApiRequestError(message, response.status, code, correlationId);
}

async function request(path: string, init: RequestInit, timeoutMs: number, command = false): Promise<Response> {
  try {
    const response = await fetch(`${API_BASE}${path}`, {
      cache: "no-store",
      credentials: "same-origin",
      ...init,
      signal: AbortSignal.timeout(timeoutMs),
    });
    handleAuthentication(response);
    if (!response.ok) {
      const error = await responseError(response);
      if (command && response.status === 504) {
        throw new ApiRequestError(
          "O comando excedeu o prazo e o resultado não está confirmado. Atualize o estado antes de tentar novamente.",
          504,
          error.code,
          error.correlationId,
          true,
        );
      }
      throw error;
    }
    return response;
  } catch (error) {
    if (error instanceof ApiRequestError) throw error;
    if (error instanceof DOMException && ["AbortError", "TimeoutError"].includes(error.name)) {
      const message = command
        ? "O comando excedeu o prazo e o resultado não está confirmado. Atualize o estado antes de tentar novamente."
        : "A resposta excedeu 15 segundos. Tente novamente.";
      throw new ApiRequestError(message, 504, "UPSTREAM_TIMEOUT", "", command);
    }
    throw error;
  }
}

export async function apiGet<T>(path: string): Promise<T> {
  const response = await request(path, {}, READ_TIMEOUT_MS);
  return response.json();
}

export async function apiGetText(path: string): Promise<string> {
  const response = await request(path, {}, READ_TIMEOUT_MS);
  return response.text();
}

export async function apiPost<T>(path: string, body?: unknown, options?: { idempotencyKey?: string }): Promise<T> {
  const response = await request(path, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      ...(options?.idempotencyKey ? { "Idempotency-Key": options.idempotencyKey } : {})
    },
    body: body === undefined ? undefined : JSON.stringify(body),
  }, COMMAND_TIMEOUT_MS, true);
  return response.json();
}

export async function apiPatch<T>(path: string, body: unknown): Promise<T> {
  const response = await request(path, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  }, COMMAND_TIMEOUT_MS, true);
  return response.json();
}

export async function apiDelete<T>(path: string): Promise<T> {
  const response = await request(path, {
    method: "DELETE",
  }, COMMAND_TIMEOUT_MS, true);
  return response.json();
}
