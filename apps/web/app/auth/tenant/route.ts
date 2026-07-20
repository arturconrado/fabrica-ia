import { NextRequest, NextResponse } from "next/server";

import { TENANT_COOKIE, apiInternalBase, resolveAccessToken, sessionCookieOptions, setTokenCookies } from "@/lib/auth-server";


export async function POST(request: NextRequest) {
  const { accessToken, refreshed } = await resolveAccessToken(request);
  if (!accessToken) return NextResponse.json({ detail: "Authentication required" }, { status: 401 });
  const body = await request.json() as { tenant_id?: string };
  const tenantId = String(body.tenant_id || "").trim();
  if (!tenantId) return NextResponse.json({ detail: "tenant_id is required" }, { status: 422 });
  const response = await fetch(`${apiInternalBase()}/auth/me`, {
    headers: { Authorization: `Bearer ${accessToken}`, "X-Tenant-ID": tenantId },
    cache: "no-store"
  });
  if (!response.ok) return NextResponse.json({ detail: "Tenant membership is required" }, { status: 403 });
  const result = NextResponse.json({ active_tenant_id: tenantId });
  if (refreshed) setTokenCookies(result, refreshed);
  result.cookies.set(TENANT_COOKIE, tenantId, sessionCookieOptions(60 * 60 * 24 * 30));
  return result;
}
