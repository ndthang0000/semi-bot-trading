import { create } from "zustand";

interface AuthState {
  accessToken: string | null;
  username: string | null;
  isAuthenticated: boolean;
  isInitializing: boolean;
  setTokens: (accessToken: string, username: string) => void;
  clearAuth: () => void;
  setInitializing: (value: boolean) => void;
}

export const useAuthStore = create<AuthState>((set) => ({
  accessToken: null,
  username: null,
  isAuthenticated: false,
  isInitializing: true, // true until we've tried to restore session from refresh token
  setTokens: (accessToken, username) =>
    set({ accessToken, username, isAuthenticated: true, isInitializing: false }),
  clearAuth: () =>
    set({ accessToken: null, username: null, isAuthenticated: false, isInitializing: false }),
  setInitializing: (value) => set({ isInitializing: value }),
}));
