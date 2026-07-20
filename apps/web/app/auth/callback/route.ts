import { NextRequest, NextResponse } from "next/server";

import {
  PKCE_COOKIE,
  RETURN_COOKIE,
  STATE_COOKIE,
  appBaseUrl,
  exchangeToken,
  oidcClientId,
  safeReturnPath,
  setTokenCookies
} from "@/lib/auth-server";


export async function GET(request: NextRequest) {
  const code = request.nextUrl.searchParams.get("code");
  const state = request.nextUrl.searchParams.get("state");
  const expectedState = request.cookies.get(STATE_COOKIE)?.value;
  const verifier = request.cookies.get(PKCE_COOKIE)?.value;
  if (!code || !state || !expectedState || state !== expectedState || !verifier) {
    return NextResponse.json({ detail: "Invalid OIDC callback state" }, { status: 400 });
  }
  try {
    const tokens = await exchangeToken(new URLSearchParams({
      grant_type: "authorization_code",
      client_id: oidcClientId(),
      code,
      code_verifier: verifier,
      redirect_uri: `${appBaseUrl()}/auth/callback`
    }));
    const returnTo = safeReturnPath(request.cookies.get(RETURN_COOKIE)?.value || null);
    const response = NextResponse.redirect(new URL(returnTo, appBaseUrl()));
    setTokenCookies(response, tokens);
    response.cookies.delete(PKCE_COOKIE);
    response.cookies.delete(STATE_COOKIE);
    response.cookies.delete(RETURN_COOKIE);
    return response;
  } catch (error) {
    return NextResponse.json({ detail: error instanceof Error ? error.message : "OIDC callback failed" }, { status: 502 });
  }
}
