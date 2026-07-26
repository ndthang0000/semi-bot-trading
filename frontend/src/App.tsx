import { useQuery } from "@tanstack/react-query";
import { useEffect } from "react";
import { authFetch, clearStoredRefreshToken, getStoredRefreshToken, refreshAccessToken } from "./api/auth";
import { BlackoutBanner, useNewsData } from "./components/NewsWidget";
import { CalmResetMonitor } from "./components/CalmResetMonitor";
import { LoginPage } from "./components/LoginPage";
import { Sidebar } from "./components/Sidebar";
import { buildWeeklyReviewGate } from "./lib/weeklyReview";
import { AccountDashboardPage } from "./pages/AccountDashboardPage";
import { CalmPage } from "./pages/CalmPage";
import { ChartPage } from "./pages/ChartPage";
import { JournalPage } from "./pages/JournalPage";
import { useAuthStore } from "./store/authStore";
import { useNavigationStore } from "./store/navigationStore";
import type { TradeHistoryResponse } from "./types";

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
  const setPage = useNavigationStore((s) => s.setPage);
  const newsData = useNewsData();
  const { data: weeklyReviewTrades } = useQuery({
    queryKey: ["weekly-review-gate"],
    queryFn: fetchWeeklyReviewTrades,
    refetchInterval: 60_000,
    staleTime: 15_000,
  });
  const weeklyReviewGate = buildWeeklyReviewGate(weeklyReviewTrades ?? []);

  useEffect(() => {
    if (weeklyReviewGate.active && activePage !== "journal" && activePage !== "calm") {
      setPage("journal");
    }
  }, [activePage, setPage, weeklyReviewGate.active]);

  const renderedPage = weeklyReviewGate.active && activePage !== "calm" ? "journal" : activePage;

  return (
    <div className="flex h-dvh flex-col overflow-hidden">
      <CalmResetMonitor />
      {newsData?.active_blackout && <BlackoutBanner event={newsData.active_blackout} />}
      <div className="flex flex-1 min-h-0 overflow-hidden">
        <Sidebar reviewLocked={weeklyReviewGate.active} />
        <div className="flex-1 min-w-0">
          {renderedPage === "chart" && <ChartPage newsData={newsData} />}
          {renderedPage === "dashboard" && <AccountDashboardPage />}
          {renderedPage === "journal" && <JournalPage weeklyReviewGate={weeklyReviewGate} />}
          {renderedPage === "calm" && <CalmPage />}
        </div>
      </div>
    </div>
  );
}

async function fetchWeeklyReviewTrades() {
  const response = await authFetch("/api/trades?limit=500&backtest=false&sort=opened_at_desc");
  if (!response.ok) {
    const body = await response.json().catch(() => null);
    throw new Error(body?.detail ?? `Weekly review gate failed with ${response.status}`);
  }
  const payload: TradeHistoryResponse = await response.json();
  return payload.trades ?? [];
}
