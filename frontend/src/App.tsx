import { useEffect } from "react";
import { clearStoredRefreshToken, getStoredRefreshToken, refreshAccessToken } from "./api/auth";
import { LoginPage } from "./components/LoginPage";
import { Sidebar } from "./components/Sidebar";
import { AccountDashboardPage } from "./pages/AccountDashboardPage";
import { ChartPage } from "./pages/ChartPage";
import { JournalPage } from "./pages/JournalPage";
import { useAuthStore } from "./store/authStore";
import { useNavigationStore } from "./store/navigationStore";

export function App() {
  const isAuthenticated = useAuthStore((s) => s.isAuthenticated);
  const isInitializing = useAuthStore((s) => s.isInitializing);
  const setTokens = useAuthStore((s) => s.setTokens);
  const clearAuth = useAuthStore((s) => s.clearAuth);

  // Restore session from stored refresh token on page load
  useEffect(() => {
    const stored = getStoredRefreshToken();
    if (!stored) {
      clearAuth();
      return;
    }
    refreshAccessToken(stored)
      .then((data) => setTokens(data.access_token, data.username))
      .catch(() => {
        clearStoredRefreshToken();
        clearAuth();
      });
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  if (isInitializing) {
    return (
      <div className="grid h-dvh place-items-center bg-ink-950 text-sm text-slate-500">
        Loading…
      </div>
    );
  }

  if (!isAuthenticated) {
    return <LoginPage />;
  }

  return <AppShell />;
}

function AppShell() {
  const activePage = useNavigationStore((s) => s.activePage);

  return (
    <div className="flex h-dvh overflow-hidden">
      <Sidebar />
      <div className="flex-1 min-w-0">
        {activePage === "chart" && <ChartPage />}
        {activePage === "dashboard" && <AccountDashboardPage />}
        {activePage === "journal" && <JournalPage />}
      </div>
    </div>
  );
}
