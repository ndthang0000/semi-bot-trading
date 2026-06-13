import { jsx as _jsx, jsxs as _jsxs } from "react/jsx-runtime";
import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { AlertTriangle } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { fetchChartPayload, fetchReplayTimeline } from "./api/chart";
import { ContextStrip } from "./components/ContextStrip";
import { Inspector } from "./components/Inspector";
import { ReplayControls } from "./components/ReplayControls";
import { TopBar } from "./components/TopBar";
import { TradingChart } from "./components/TradingChart";
import { useChartStore } from "./store/chartStore";
export function App() {
    const mode = window.location.pathname === "/replay-chart" ? "replay" : "dashboard";
    const isReplayRoute = mode === "replay";
    const symbol = useChartStore((state) => state.symbol);
    const timeframe = useChartStore((state) => state.timeframe);
    const limit = useChartStore((state) => state.limit);
    const startIndex = useChartStore((state) => state.startIndex);
    const activeZonesOnly = useChartStore((state) => state.activeZonesOnly);
    const selectedPlaybooks = useChartStore((state) => state.selectedPlaybooks);
    const autoRefreshEnabled = useChartStore((state) => state.autoRefreshEnabled);
    const [replayPlaying, setReplayPlaying] = useState(false);
    const [replaySpeedSeconds, setReplaySpeedSeconds] = useState(1);
    const [replayIndex, setReplayIndex] = useState(0);
    const autoRefreshActive = !isReplayRoute && autoRefreshEnabled && startIndex === null;
    const timelineQuery = useQuery({
        queryKey: ["replay-timeline", symbol, timeframe, limit, startIndex],
        queryFn: () => fetchReplayTimeline({ symbol, timeframe, limit, startIndex }),
        staleTime: 60_000,
        enabled: isReplayRoute,
    });
    const replayTimes = timelineQuery.data?.times ?? [];
    const replayAt = isReplayRoute ? replayTimes[replayIndex] ?? null : null;
    const replayStart = isReplayRoute ? timelineQuery.data?.start ?? null : null;
    const chartQuery = useQuery({
        queryKey: ["chart", mode, symbol, timeframe, limit, startIndex, activeZonesOnly, selectedPlaybooks, replayStart, replayAt],
        queryFn: () => fetchChartPayload({ symbol, timeframe, limit, startIndex, activeZonesOnly, selectedPlaybooks, replayStart, replayAt }),
        placeholderData: isReplayRoute ? keepPreviousData : undefined,
        refetchInterval: autoRefreshActive ? 60_000 : false,
        refetchIntervalInBackground: false,
        refetchOnReconnect: autoRefreshActive,
        refetchOnWindowFocus: autoRefreshActive,
        staleTime: 10_000,
        enabled: !isReplayRoute || (replayStart !== null && replayAt !== null),
    });
    useEffect(() => {
        setReplayIndex(0);
        setReplayPlaying(false);
    }, [symbol, timeframe, limit, startIndex]);
    useEffect(() => {
        if (!isReplayRoute || !replayPlaying || replayTimes.length === 0)
            return;
        const intervalId = window.setInterval(() => {
            setReplayIndex((current) => {
                if (current >= replayTimes.length - 1) {
                    setReplayPlaying(false);
                    return current;
                }
                return current + 1;
            });
        }, replaySpeedSeconds * 1000);
        return () => window.clearInterval(intervalId);
    }, [isReplayRoute, replayPlaying, replaySpeedSeconds, replayTimes.length]);
    const stepReplay = (delta) => {
        setReplayPlaying(false);
        setReplayIndex((current) => clamp(current + delta, 0, Math.max(replayTimes.length - 1, 0)));
    };
    const replayControls = useMemo(() => ({
        isPlaying: replayPlaying,
        speedSeconds: replaySpeedSeconds,
        timeline: timelineQuery.data,
        currentIndex: replayIndex,
    }), [replayIndex, replayPlaying, replaySpeedSeconds, timelineQuery.data]);
    return (_jsxs("div", { className: "grid h-dvh min-h-0 grid-rows-[auto_minmax(0,1fr)] overflow-hidden bg-ink-950 text-slate-100", children: [_jsx(TopBar, { mode: mode, isFetching: chartQuery.isFetching || timelineQuery.isFetching, onRefresh: () => chartQuery.refetch() }), _jsxs("main", { className: "grid min-h-0 grid-cols-[minmax(0,1fr)_340px]", children: [_jsxs("section", { className: `grid min-h-0 ${isReplayRoute ? "grid-rows-[auto_auto_minmax(0,1fr)]" : "grid-rows-[auto_minmax(0,1fr)]"}`, children: [_jsx(ContextStrip, { payload: chartQuery.data, onContextUpdated: () => chartQuery.refetch() }), isReplayRoute ? (_jsx(ReplayControls, { ...replayControls, onPlayingChange: setReplayPlaying, onSpeedChange: setReplaySpeedSeconds, onStep: stepReplay })) : null, chartQuery.isError ? (_jsx("div", { className: "grid place-items-center bg-ink-950", children: _jsxs("div", { className: "flex max-w-md items-start gap-3 rounded-md border border-rose-500/40 bg-rose-500/10 p-4 text-sm text-rose-100", children: [_jsx(AlertTriangle, { className: "mt-0.5 shrink-0", size: 18 }), _jsx("span", { children: chartQuery.error.message })] }) })) : chartQuery.data ? (_jsx(TradingChart, { payload: chartQuery.data, onEntityCreated: () => chartQuery.refetch() })) : (_jsx("div", { className: "grid place-items-center bg-ink-950 text-sm text-slate-500", children: "Loading chart..." }))] }), _jsx(Inspector, { payload: chartQuery.data, onZoneUpdated: () => chartQuery.refetch() })] })] }));
}
function clamp(value, min, max) {
    return Math.min(Math.max(value, min), max);
}
