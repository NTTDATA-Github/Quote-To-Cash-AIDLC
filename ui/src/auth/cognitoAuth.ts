/**
 * Raw Cognito calls, no AWS SDK — `InitiateAuth`/`RefreshToken` are public client
 * actions Cognito is designed to accept directly from a browser (no credentials, no
 * SigV4 signing), confirmed against floci during development. Same endpoint-switching
 * pattern the backend uses everywhere else: an explicit `endpointUrl` targets floci
 * locally; omitted, it targets real AWS.
 */

export interface CognitoConfig {
  endpointUrl?: string;
  region: string;
  clientId: string;
}

export interface AuthTokens {
  idToken: string;
  accessToken: string;
  refreshToken: string;
  /** epoch ms */
  expiresAt: number;
}

export class CognitoError extends Error {
  constructor(
    public readonly type: string,
    message: string,
  ) {
    super(message);
    this.name = "CognitoError";
  }
}

interface AuthenticationResult {
  IdToken: string;
  AccessToken: string;
  RefreshToken?: string;
  ExpiresIn: number;
}

async function callCognito(
  config: CognitoConfig,
  target: string,
  body: Record<string, unknown>,
): Promise<{ AuthenticationResult: AuthenticationResult }> {
  const url = config.endpointUrl ? `${config.endpointUrl.replace(/\/$/, "")}/` : `https://cognito-idp.${config.region}.amazonaws.com/`;
  let res: Response;
  try {
    res = await fetch(url, {
      method: "POST",
      headers: {
        "Content-Type": "application/x-amz-json-1.1",
        "X-Amz-Target": `AWSCognitoIdentityProviderService.${target}`,
      },
      body: JSON.stringify(body),
    });
  } catch {
    // fetch() throws a generic TypeError ("Failed to fetch") for both "server is down"
    // and "CORS preflight rejected" — neither carries a status code to distinguish them.
    throw new CognitoError("NetworkError", `Could not reach the identity service at ${url}. Check that it is running and reachable.`);
  }
  const data = (await res.json()) as Record<string, unknown>;
  if (!res.ok) {
    throw new CognitoError(
      typeof data.__type === "string" ? data.__type : "UnknownError",
      typeof data.message === "string" ? data.message : "Sign-in failed",
    );
  }
  return data as { AuthenticationResult: AuthenticationResult };
}

function toTokens(result: AuthenticationResult, fallbackRefreshToken?: string): AuthTokens {
  const refreshToken = result.RefreshToken ?? fallbackRefreshToken;
  if (!refreshToken) {
    throw new CognitoError("MissingRefreshToken", "Cognito did not return a refresh token");
  }
  return {
    idToken: result.IdToken,
    accessToken: result.AccessToken,
    refreshToken,
    expiresAt: Date.now() + result.ExpiresIn * 1000,
  };
}

export async function signIn(config: CognitoConfig, username: string, password: string): Promise<AuthTokens> {
  const { AuthenticationResult } = await callCognito(config, "InitiateAuth", {
    AuthFlow: "USER_PASSWORD_AUTH",
    ClientId: config.clientId,
    AuthParameters: { USERNAME: username, PASSWORD: password },
  });
  return toTokens(AuthenticationResult);
}

export async function refreshSession(config: CognitoConfig, refreshToken: string): Promise<AuthTokens> {
  const { AuthenticationResult } = await callCognito(config, "InitiateAuth", {
    AuthFlow: "REFRESH_TOKEN_AUTH",
    ClientId: config.clientId,
    AuthParameters: { REFRESH_TOKEN: refreshToken },
  });
  // A refresh response never repeats the refresh token — keep the one we already have.
  return toTokens(AuthenticationResult, refreshToken);
}

/** Decode-only (no signature check — the backend re-verifies every request against
 * Cognito's JWKS; this is purely for UI display: whose tenant, which roles, and the
 * identity shown in the user menu). */
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
    tenantId: typeof claims["custom:tenant_id"] === "string" ? (claims["custom:tenant_id"] as string) : null,
    roles: Array.isArray(claims["cognito:groups"]) ? (claims["cognito:groups"] as string[]) : [],
    email: typeof claims["email"] === "string" ? (claims["email"] as string) : null,
    username: typeof claims["cognito:username"] === "string" ? (claims["cognito:username"] as string) : null,
  };
}
