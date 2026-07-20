import { NextRequest, NextResponse } from "next/server";

import {
  PKCE_COOKIE,
  RETURN_COOKIE,
  STATE_COOKIE,
  appBaseUrl,
  oidcClientId,
  oidcPublicIssuer,
  pkceChallenge,
  randomUrlSafe,
  safeReturnPath,
  sessionCookieOptions
} from "@/lib/auth-server";


export async function GET(request: NextRequest) {
  const verifier = randomUrlSafe();
  const state = randomUrlSafe(32);
  const returnTo = safeReturnPath(request.nextUrl.searchParams.get("returnTo"));
  const redirectUri = `${appBaseUrl()}/auth/callback`;
  const authorization = new URL(`${oidcPublicIssuer()}/protocol/openid-connect/auth`);
  authorization.searchParams.set("client_id", oidcClientId());
  authorization.searchParams.set("response_type", "code");
  authorization.searchParams.set("scope", "openid profile email");
  authorization.searchParams.set("redirect_uri", redirectUri);
  authorization.searchParams.set("state", state);
  authorization.searchParams.set("code_challenge", pkceChallenge(verifier));
  authorization.searchParams.set("code_challenge_method", "S256");

  const response = NextResponse.redirect(authorization);
  const cookieOptions = sessionCookieOptions(600);
  response.cookies.set(PKCE_COOKIE, verifier, cookieOptions);
  response.cookies.set(STATE_COOKIE, state, cookieOptions);
  response.cookies.set(RETURN_COOKIE, returnTo, cookieOptions);
  return response;
}
