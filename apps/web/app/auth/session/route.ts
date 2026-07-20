import { NextRequest, NextResponse } from "next/server";

import { TENANT_COOKIE, apiInternalBase, clearSessionCookies, resolveAccessToken, setTokenCookies } from "@/lib/auth-server";


export async function GET(request: NextRequest) {
  const { accessToken, refreshed } = await resolveAccessToken(request);
  if (!accessToken) {
    const response = NextResponse.json({ authenticated: false }, { status: 401 });
    clearSessionCookies(response);
    return response;
  }
  const tenantId = request.cookies.get(TENANT_COOKIE)?.value || "";
  const headers = { Authorization: `Bearer ${accessToken}`, ...(tenantId ? { "X-Tenant-ID": tenantId } : {}) };
  const sessionResponse = await fetch(`${apiInternalBase()}/auth/session`, { headers, cache: "no-store" });
  if (!sessionResponse.ok) {
    const response = NextResponse.json({ authenticated: false }, { status: 401 });
    clearSessionCookies(response);
    return response;
  }
  const { me, tenants } = await sessionResponse.json();
  const result = NextResponse.json({ authenticated: true, active_tenant_id: me.tenant_id, me, tenants });
  if (refreshed) setTokenCookies(result, refreshed);
  return result;
}
