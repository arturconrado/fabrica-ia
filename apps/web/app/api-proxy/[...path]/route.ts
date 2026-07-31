import { NextRequest, NextResponse } from "next/server";

import {
  REFRESH_COOKIE,
  TENANT_COOKIE,
  apiInternalBase,
  clearSessionCookies,
  refreshAccessToken,
  resolveAccessToken,
  setTokenCookies
} from "@/lib/auth-server";


type Context = { params: Promise<{ path: string[] }> };
const readMethods = new Set(["GET", "HEAD"]);

function timeoutResponse(correlationId: string) {
  return NextResponse.json(
    { detail: { code: "UPSTREAM_TIMEOUT", message: "A API não respondeu dentro do prazo.", correlation_id: correlationId } },
    { status: 504, headers: { "X-Correlation-ID": correlationId } },
  );
}

async function proxy(request: NextRequest, context: Context) {
  const correlationId = request.headers.get("x-correlation-id") || crypto.randomUUID();
  try {
    const { path } = await context.params;
    let { accessToken, refreshed } = await resolveAccessToken(request);
    const refreshToken = request.cookies.get(REFRESH_COOKIE)?.value || "";
    if (!accessToken) {
      const response = NextResponse.json({ detail: { code: "AUTH_REQUIRED", message: "Authentication required", correlation_id: correlationId } }, { status: 401 });
      response.headers.set("X-Correlation-ID", correlationId);
      clearSessionCookies(response);
      return response;
    }

    const target = new URL(`${apiInternalBase()}/${path.join("/")}`);
    request.nextUrl.searchParams.forEach((value, key) => target.searchParams.append(key, value));
    const headers = new Headers(request.headers);
    for (const name of ["host", "cookie", "authorization", "content-length", "connection"]) headers.delete(name);
    headers.set("X-Correlation-ID", correlationId);
    const tenantId = request.cookies.get(TENANT_COOKIE)?.value;
    if (tenantId) headers.set("X-Tenant-ID", tenantId);
    const body = readMethods.has(request.method) ? undefined : await request.arrayBuffer();
    const timeoutMs = readMethods.has(request.method) ? 20_000 : 125_000;
    const send = (token: string) => {
      headers.set("Authorization", `Bearer ${token}`);
      return fetch(target, {
        method: request.method,
        headers,
        body,
        cache: "no-store",
        redirect: "manual",
        signal: AbortSignal.timeout(timeoutMs),
      });
    };
    let upstream = await send(accessToken);
    if (upstream.status === 401 && refreshToken && !refreshed) {
      try {
        refreshed = await refreshAccessToken(refreshToken);
        accessToken = refreshed.access_token;
        upstream = await send(accessToken);
      } catch {
        // The centralized 401 response below clears every session cookie.
      }
    }
    const responseHeaders = new Headers({ "X-Correlation-ID": correlationId });
    for (const name of ["content-type", "content-disposition", "cache-control", "etag", "last-modified"]) {
      const value = upstream.headers.get(name);
      if (value) responseHeaders.set(name, value);
    }
    const response = new NextResponse(upstream.body, { status: upstream.status, headers: responseHeaders });
    if (refreshed) setTokenCookies(response, refreshed);
    if (upstream.status === 401) clearSessionCookies(response);
    return response;
  } catch (error) {
    if (error instanceof DOMException && ["AbortError", "TimeoutError"].includes(error.name)) {
      return timeoutResponse(correlationId);
    }
    return NextResponse.json(
      { detail: { code: "UPSTREAM_UNAVAILABLE", message: "Não foi possível alcançar a API.", correlation_id: correlationId } },
      { status: 502, headers: { "X-Correlation-ID": correlationId } },
    );
  }
}

export const GET = proxy;
export const POST = proxy;
export const PUT = proxy;
export const PATCH = proxy;
export const DELETE = proxy;
