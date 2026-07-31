import { NextRequest, NextResponse } from "next/server";

import { TENANT_COOKIE, apiInternalBase, clearSessionCookies, resolveAccessToken, setTokenCookies } from "@/lib/auth-server";


export async function GET(request: NextRequest) {
  const correlationId = request.headers.get("x-correlation-id") || crypto.randomUUID();
  try {
    const { accessToken, refreshed } = await resolveAccessToken(request);
    if (!accessToken) {
      const response = NextResponse.json({ authenticated: false }, { status: 401 });
      clearSessionCookies(response);
      return response;
    }
    const tenantId = request.cookies.get(TENANT_COOKIE)?.value || "";
    const headers = { Authorization: `Bearer ${accessToken}`, "X-Correlation-ID": correlationId, ...(tenantId ? { "X-Tenant-ID": tenantId } : {}) };
    const sessionResponse = await fetch(`${apiInternalBase()}/auth/session`, {
      headers,
      cache: "no-store",
      signal: AbortSignal.timeout(20_000),
    });
    if (!sessionResponse.ok) {
      if (sessionResponse.status === 401) {
        const response = NextResponse.json({ authenticated: false }, { status: 401 });
        clearSessionCookies(response);
        return response;
      }
      return NextResponse.json(
        { detail: { code: "SESSION_UPSTREAM_ERROR", message: "A sessão está temporariamente indisponível.", correlation_id: correlationId } },
        { status: sessionResponse.status, headers: { "X-Correlation-ID": correlationId } },
      );
    }
    const { me, tenants } = await sessionResponse.json();
    const result = NextResponse.json({ authenticated: true, active_tenant_id: me.tenant_id, me, tenants });
    result.headers.set("X-Correlation-ID", correlationId);
    if (refreshed) setTokenCookies(result, refreshed);
    return result;
  } catch (error) {
    const timeout = error instanceof DOMException && ["AbortError", "TimeoutError"].includes(error.name);
    return NextResponse.json(
      { detail: { code: timeout ? "UPSTREAM_TIMEOUT" : "SESSION_UPSTREAM_ERROR", message: timeout ? "A sessão excedeu o prazo de resposta." : "A sessão está temporariamente indisponível.", correlation_id: correlationId } },
      { status: timeout ? 504 : 503, headers: { "X-Correlation-ID": correlationId } },
    );
  }
}
