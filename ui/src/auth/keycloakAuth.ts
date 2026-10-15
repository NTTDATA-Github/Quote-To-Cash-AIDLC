/**
 * Raw Keycloak token-endpoint calls, no adapter library — same reasoning as
 * `cognitoAuth.ts`: Keycloak's direct-grant (Resource Owner Password Credentials) flow is
 * a plain form-encoded POST a public client is designed to call straight from a browser,
 * no client secret involved (`o2c-portal` is `publicClient: true`,
 * `directAccessGrantsEnabled: true` — see `keycloak-realm-export.json`).
 */

export interface KeycloakConfig {
  /** Realm issuer URL, e.g. "https://<keycloak-fqdn>/realms/o2c" — no trailing slash. */
  issuerUrl: string;
  clientId: string;
}

export interface AuthTokens {
  idToken: string;
  accessToken: string;
  refreshToken: string;
  /** epoch ms */
  expiresAt: number;
}

export class KeycloakError extends Error {
  constructor(
    public readonly type: string,
    message: string,
  ) {
    super(message);
    this.name = "KeycloakError";
  }
}

interface TokenResponse {
  id_token?: string;
  access_token: string;
  refresh_token: string;
  expires_in: number;
}

async function callToken(config: KeycloakConfig, params: Record<string, string>): Promise<TokenResponse> {
  const url = `${config.issuerUrl.replace(/\/$/, "")}/protocol/openid-connect/token`;
  let res: Response;
  try {
    res = await fetch(url, {
      method: "POST",
      headers: { "Content-Type": "application/x-www-form-urlencoded" },
      body: new URLSearchParams({ client_id: config.clientId, ...params }),
    });
  } catch {
    // fetch() throws a generic TypeError for both "server is down" and "CORS preflight
    // rejected" — neither carries a status code to distinguish them.
    throw new KeycloakError("NetworkError", `Could not reach the identity service at ${url}. Check that it is running and reachable.`);
  }
  const data = (await res.json()) as Record<string, unknown>;
  if (!res.ok) {
    throw new KeycloakError(
      typeof data.error === "string" ? data.error : "UnknownError",
      typeof data.error_description === "string" ? data.error_description : "Sign-in failed",
    );
  }
  return data as unknown as TokenResponse;
}

function toTokens(result: TokenResponse, fallbackRefreshToken?: string): AuthTokens {
  const refreshToken = result.refresh_token ?? fallbackRefreshToken;
  if (!refreshToken) {
    throw new KeycloakError("MissingRefreshToken", "Keycloak did not return a refresh token");
  }
  const idToken = result.id_token ?? result.access_token;
  return {
    idToken,
    accessToken: result.access_token,
    refreshToken,
    expiresAt: Date.now() + result.expires_in * 1000,
  };
}

export async function signIn(config: KeycloakConfig, username: string, password: string): Promise<AuthTokens> {
  const result = await callToken(config, { grant_type: "password", username, password });
  return toTokens(result);
}

export async function refreshSession(config: KeycloakConfig, refreshToken: string): Promise<AuthTokens> {
  const result = await callToken(config, { grant_type: "refresh_token", refresh_token: refreshToken });
  return toTokens(result, refreshToken);
}

/** Decode-only (no signature check — the backend re-verifies every request against
 * Keycloak's JWKS; this is purely for UI display: whose tenant, which roles, and the
 * identity shown in the user menu). `tenant_id`/`roles` are flat claims (realm protocol
 * mappers), unlike Cognito's `custom:`/`cognito:` namespacing. */
export function decodeIdTokenClaims(idToken: string): {
  tenantId: string | null;
  roles: string[];
  email: string | null;
  username: string | null;
} {
  const payload = idToken.split(".")[1];
  const json = atob(payload.replace(/-/g, "+").replace(/_/g, "/"));
  const claims = JSON.parse(json) as Record<string, unknown>;
  return {
    tenantId: typeof claims["tenant_id"] === "string" ? (claims["tenant_id"] as string) : null,
    roles: Array.isArray(claims["roles"]) ? (claims["roles"] as string[]) : [],
    email: typeof claims["email"] === "string" ? (claims["email"] as string) : null,
    username: typeof claims["preferred_username"] === "string" ? (claims["preferred_username"] as string) : null,
  };
}
