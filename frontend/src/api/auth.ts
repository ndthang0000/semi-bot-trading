import { useAuthStore } from "../store/authStore";

const REFRESH_TOKEN_KEY = "rzt_v1"; // localStorage key for refresh token

// ---------------------------------------------------------------------------
// Refresh token persistence
// ---------------------------------------------------------------------------

export function getStoredRefreshToken(): string | null {
  try {
    return localStorage.getItem(REFRESH_TOKEN_KEY);
  } catch {
    return null;
  }
}

export function setStoredRefreshToken(token: string): void {
  try {
    localStorage.setItem(REFRESH_TOKEN_KEY, token);
  } catch {
    // Ignore (private browsing with storage blocked)
  }
}

export function clearStoredRefreshToken(): void {
  try {
    localStorage.removeItem(REFRESH_TOKEN_KEY);
  } catch {
    // Ignore
  }
}

// ---------------------------------------------------------------------------
// API calls
// ---------------------------------------------------------------------------

export async function login(
  username: string,
  password: string,
): Promise<{ access_token: string; refresh_token: string; username: string }> {
  const response = await fetch("/api/auth/login", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ username, password }),
  });
  if (!response.ok) {
    const body = await response.json().catch(() => null);
    throw new Error(body?.detail ?? "Login failed");
  }
  return response.json();
}

export async function refreshAccessToken(
  refreshToken: string,
): Promise<{ access_token: string; username: string }> {
  const response = await fetch("/api/auth/refresh", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ refresh_token: refreshToken }),
  });
  if (!response.ok) throw new Error("Token refresh failed");
  return response.json();
}

export async function logout(accessToken: string, refreshToken: string): Promise<void> {
  try {
    await fetch("/api/auth/logout", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        Authorization: `Bearer ${accessToken}`,
      },
      body: JSON.stringify({ refresh_token: refreshToken }),
    });
  } catch {
    // Best-effort — clear local state regardless
  }
}

// ---------------------------------------------------------------------------
// authFetch — drop-in replacement for fetch() that adds the Bearer token
// and auto-refreshes on 401.
// ---------------------------------------------------------------------------

export async function authFetch(url: string, options: RequestInit = {}): Promise<Response> {
  const { accessToken } = useAuthStore.getState();

  const doRequest = (token: string | null) =>
    fetch(url, {
      ...options,
      headers: {
        ...(options.headers ?? {}),
        ...(token ? { Authorization: `Bearer ${token}` } : {}),
      },
    });

  let response = await doRequest(accessToken);

  if (response.status === 401) {
    // Try to silently refresh
    const storedRefresh = getStoredRefreshToken();
    if (storedRefresh) {
      try {
        const data = await refreshAccessToken(storedRefresh);
        useAuthStore.getState().setTokens(data.access_token, data.username);
        // Retry original request with new token
        response = await doRequest(data.access_token);
      } catch {
        // Refresh failed — log the user out
        clearStoredRefreshToken();
        useAuthStore.getState().clearAuth();
      }
    } else {
      useAuthStore.getState().clearAuth();
    }
  }

  return response;
}
