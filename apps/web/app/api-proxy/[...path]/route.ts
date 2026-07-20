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

async function proxy(request: NextRequest, context: Context) {
  const { path } = await context.params;
  let { accessToken, refreshed } = await resolveAccessToken(request);
  const refreshToken = request.cookies.get(REFRESH_COOKIE)?.value || "";
  if (!accessToken) {
    const response = NextResponse.json({ detail: { code: "AUTH_REQUIRED", message: "Authentication required" } }, { status: 401 });
    clearSessionCookies(response);
    return response;
  }

  const target = new URL(`${apiInternalBase()}/${path.join("/")}`);
  request.nextUrl.searchParams.forEach((value, key) => target.searchParams.append(key, value));
  const headers = new Headers(request.headers);
  for (const name of ["host", "cookie", "authorization", "content-length", "connection"]) headers.delete(name);
  const tenantId = request.cookies.get(TENANT_COOKIE)?.value;
  if (tenantId) headers.set("X-Tenant-ID", tenantId);
  const body = request.method === "GET" || request.method === "HEAD" ? undefined : await request.arrayBuffer();
  const send = (token: string) => {
    headers.set("Authorization", `Bearer ${token}`);
    return fetch(target, { method: request.method, headers, body, cache: "no-store", redirect: "manual" });
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
  const responseHeaders = new Headers();
  for (const name of ["content-type", "content-disposition", "cache-control", "etag", "last-modified"]) {
    const value = upstream.headers.get(name);
    if (value) responseHeaders.set(name, value);
  }
  const response = new NextResponse(upstream.body, { status: upstream.status, headers: responseHeaders });
  if (refreshed) setTokenCookies(response, refreshed);
  if (upstream.status === 401) clearSessionCookies(response);
  return response;
}

export const GET = proxy;
export const POST = proxy;
export const PUT = proxy;
export const PATCH = proxy;
export const DELETE = proxy;
