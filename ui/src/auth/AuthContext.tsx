import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState, type ReactNode } from "react";

import * as keycloak from "./keycloakAuth";

import type { AuthTokens } from "./keycloakAuth";

const STORAGE_KEY = "erp-portal.auth";
// Refresh a bit before actual expiry so a request never races a just-expired token.
const REFRESH_MARGIN_MS = 60_000;

function loadStoredTokens(): AuthTokens | null {
  try {
    const raw = sessionStorage.getItem(STORAGE_KEY);
    return raw ? (JSON.parse(raw) as AuthTokens) : null;
  } catch {
    return null;
  }
}

function storeTokens(tokens: AuthTokens | null): void {
  try {
    if (tokens) sessionStorage.setItem(STORAGE_KEY, JSON.stringify(tokens));
    else sessionStorage.removeItem(STORAGE_KEY);
  } catch {
    // sessionStorage unavailable (private mode, etc.) — session just won't survive a refresh.
  }
}

interface AuthState {
  idToken: string | null;
  tenantId: string | null;
  roles: string[];
  email: string | null;
  username: string | null;
  isAuthenticated: boolean;
  isLoading: boolean;
  error: string | null;
  signIn: (username: string, password: string) => Promise<void>;
  signOut: () => void;
}

const AuthContext = createContext<AuthState | null>(null);

const keycloakConfig: keycloak.KeycloakConfig = {
  issuerUrl: import.meta.env.VITE_KEYCLOAK_ISSUER_URL,
  clientId: import.meta.env.VITE_KEYCLOAK_CLIENT_ID,
};

const auth = {
  signIn: (username: string, password: string) =>
    keycloak.signIn(keycloakConfig, username, password),
  refreshSession: (refreshToken: string) => keycloak.refreshSession(keycloakConfig, refreshToken),
  decodeIdTokenClaims: keycloak.decodeIdTokenClaims,
};

export function AuthProvider({ children }: { children: ReactNode }) {
  const [tokens, setTokens] = useState<AuthTokens | null>(() => loadStoredTokens());
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const refreshTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  const applyTokens = useCallback((next: AuthTokens | null) => {
    setTokens(next);
    storeTokens(next);
  }, []);

  const signOut = useCallback(() => {
    if (refreshTimer.current) clearTimeout(refreshTimer.current);
    applyTokens(null);
  }, [applyTokens]);

  const doSignIn = useCallback(
    async (username: string, password: string) => {
      setIsLoading(true);
      setError(null);
      try {
        const next = await auth.signIn(username, password);
        applyTokens(next);
      } catch (err) {
        setError(err instanceof Error ? err.message : "Sign-in failed");
        throw err;
      } finally {
        setIsLoading(false);
      }
    },
    [applyTokens],
  );

  // Schedule a silent refresh before the current token expires; sign out if refresh
  // itself fails (expired refresh token, revoked, etc.) rather than keep retrying.
  useEffect(() => {
    if (refreshTimer.current) clearTimeout(refreshTimer.current);
    if (!tokens) return;

    const delay = Math.max(0, tokens.expiresAt - Date.now() - REFRESH_MARGIN_MS);
    refreshTimer.current = setTimeout(() => {
      auth
        .refreshSession(tokens.refreshToken)
        .then(applyTokens)
        .catch(() => signOut());
    }, delay);

    return () => {
      if (refreshTimer.current) clearTimeout(refreshTimer.current);
    };
  }, [tokens, applyTokens, signOut]);

  const claims = useMemo(
    () => (tokens ? auth.decodeIdTokenClaims(tokens.idToken) : { tenantId: null, roles: [], email: null, username: null }),
    [tokens],
  );

  const value: AuthState = {
    idToken: tokens?.idToken ?? null,
    tenantId: claims.tenantId,
    roles: claims.roles,
    email: claims.email,
    username: claims.username,
    isAuthenticated: tokens !== null,
    isLoading,
    error,
    signIn: doSignIn,
    signOut,
  };

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthState {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be used inside <AuthProvider>");
  return ctx;
}
