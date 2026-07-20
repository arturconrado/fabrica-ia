import { NextResponse } from "next/server";

import { appBaseUrl, clearSessionCookies, oidcClientId, oidcPublicIssuer } from "@/lib/auth-server";


export async function GET() {
  const logout = new URL(`${oidcPublicIssuer()}/protocol/openid-connect/logout`);
  logout.searchParams.set("client_id", oidcClientId());
  logout.searchParams.set("post_logout_redirect_uri", `${appBaseUrl()}/`);
  const response = NextResponse.redirect(logout);
  clearSessionCookies(response);
  return response;
}
