import { createHash, randomBytes } from "node:crypto";

import type { NextResponse } from "next/server";


export const ACCESS_COOKIE = "asf_access_token";
export const REFRESH_COOKIE = "asf_refresh_token";
export const EXPIRES_COOKIE = "asf_token_expires_at";
export const TENANT_COOKIE = "asf_active_tenant";
export const PKCE_COOKIE = "asf_pkce_verifier";
export const STATE_COOKIE = "asf_oidc_state";
export const RETURN_COOKIE = "asf_login_return";

export const oidcInternalIssuer = () => process.env.OIDC_ISSUER_URL || "http://keycloak:8080/realms/software-factory";
export const oidcPublicIssuer = () => process.env.OIDC_PUBLIC_ISSUER_URL || "http://localhost:8081/realms/software-factory";
export const oidcClientId = () => process.env.OIDC_CLIENT_ID || "software-factory-web";
export const appBaseUrl = () => process.env.APP_BASE_URL || "http://localhost:3000";
export const apiInternalBase = () => process.env.API_INTERNAL_BASE_URL || "http://api:8000";

const secureCookies = () => process.env.SESSION_COOKIE_SECURE == null
  ? process.env.NODE_ENV === "production" && !appBaseUrl().startsWith("http://localhost")
  : process.env.SESSION_COOKIE_SECURE === "true";

export function sessionCookieOptions(maxAge: number) {
  return { httpOnly: true, secure: secureCookies(), sameSite: "lax" as const, path: "/", maxAge };
}

export function randomUrlSafe(bytes = 48): string {
  return randomBytes(bytes).toString("base64url");
}

export function pkceChallenge(verifier: string): string {
  return createHash("sha256").update(verifier).digest("base64url");
}

export type TokenSet = {
  access_token: string;
  refresh_token?: string;
  expires_in?: number;
  refresh_expires_in?: number;
};

export async function exchangeToken(parameters: URLSearchParams): Promise<TokenSet> {
  const response = await fetch(`${oidcInternalIssuer()}/protocol/openid-connect/token`, {
    method: "POST",
    headers: { "Content-Type": "application/x-www-form-urlencoded" },
    body: parameters,
    cache: "no-store"
  });
  if (!response.ok) {
    throw new Error(`OIDC token exchange failed (${response.status})`);
  }
  const tokens = await response.json() as TokenSet;
  if (!tokens.access_token) throw new Error("OIDC response did not include an access token");
  return tokens;
}

export async function refreshAccessToken(refreshToken: string): Promise<TokenSet> {
  return exchangeToken(new URLSearchParams({
    grant_type: "refresh_token",
    client_id: oidcClientId(),
    refresh_token: refreshToken
  }));
}

type CookieRequest = { cookies: { get(name: string): { value: string } | undefined } };

export async function resolveAccessToken(request: CookieRequest): Promise<{ accessToken: string; refreshed: TokenSet | null }> {
  let accessToken = request.cookies.get(ACCESS_COOKIE)?.value || "";
  const refreshToken = request.cookies.get(REFRESH_COOKIE)?.value || "";
  const expiresAt = Number(request.cookies.get(EXPIRES_COOKIE)?.value || 0);
  let refreshed: TokenSet | null = null;
  if ((!accessToken || !expiresAt || expiresAt < Date.now() + 30_000) && refreshToken) {
    try {
      refreshed = await refreshAccessToken(refreshToken);
      accessToken = refreshed.access_token;
    } catch {
      accessToken = "";
    }
  }
  return { accessToken, refreshed };
}

export function setTokenCookies(response: NextResponse, tokens: TokenSet): void {
  const secure = secureCookies();
  const expiresIn = Math.max(30, Number(tokens.expires_in || 300));
  response.cookies.set(ACCESS_COOKIE, tokens.access_token, {
    ...sessionCookieOptions(expiresIn),
    secure
  });
  response.cookies.set(EXPIRES_COOKIE, String(Date.now() + expiresIn * 1000), {
    ...sessionCookieOptions(expiresIn),
    secure
  });
  if (tokens.refresh_token) {
    response.cookies.set(REFRESH_COOKIE, tokens.refresh_token, {
      ...sessionCookieOptions(Math.max(expiresIn, Number(tokens.refresh_expires_in || 1800))),
      secure
    });
  }
}

export function clearSessionCookies(response: NextResponse): void {
  for (const name of [ACCESS_COOKIE, REFRESH_COOKIE, EXPIRES_COOKIE, TENANT_COOKIE, PKCE_COOKIE, STATE_COOKIE, RETURN_COOKIE]) {
    response.cookies.set(name, "", sessionCookieOptions(0));
  }
}

export function safeReturnPath(value: string | null): string {
  if (!value || !value.startsWith("/") || value.startsWith("//")) return "/dashboard";
  return value;
}
