export async function fetchChartPayload(query) {
    const params = new URLSearchParams({
        symbol: query.symbol,
        timeframe: query.timeframe,
        limit: String(query.limit),
    });
    if (query.startIndex !== null) {
        params.set("start_index", String(query.startIndex));
    }
    if (query.activeZonesOnly) {
        params.set("active_zones_only", "true");
    }
    params.set("playbooks", query.selectedPlaybooks.length > 0 ? query.selectedPlaybooks.join(",") : "__none__");
    if (query.replayAt) {
        params.set("replay_at", query.replayAt);
    }
    if (query.replayStart) {
        params.set("replay_start", query.replayStart);
    }
    const response = await fetch(`/api/chart?${params.toString()}`);
    if (!response.ok) {
        const body = await response.json().catch(() => null);
        throw new Error(body?.detail ?? `Chart API failed with ${response.status}`);
    }
    return response.json();
}
export async function fetchReplayTimeline(query) {
    const params = new URLSearchParams({
        symbol: query.symbol,
        timeframe: query.timeframe,
        limit: String(query.limit),
    });
    if (query.startIndex !== null) {
        params.set("start_index", String(query.startIndex));
    }
    const response = await fetch(`/api/replay/timeline?${params.toString()}`);
    if (!response.ok) {
        const body = await response.json().catch(() => null);
        throw new Error(body?.detail ?? `Replay timeline failed with ${response.status}`);
    }
    return response.json();
}
export async function createManualZone(input) {
    const response = await fetch("/api/zones", {
        method: "POST",
        headers: {
            "Content-Type": "application/json",
        },
        body: JSON.stringify(input),
    });
    if (!response.ok) {
        const body = await response.json().catch(() => null);
        throw new Error(body?.detail ?? `Zone create failed with ${response.status}`);
    }
    return response.json();
}
export async function updateZoneOverride(zoneId, input) {
    const response = await fetch(`/api/zones/${encodeURIComponent(zoneId)}`, {
        method: "PATCH",
        headers: {
            "Content-Type": "application/json",
        },
        body: JSON.stringify(input),
    });
    if (!response.ok) {
        const body = await response.json().catch(() => null);
        throw new Error(body?.detail ?? `Zone update failed with ${response.status}`);
    }
    return response.json();
}
export async function deleteManualZone(zoneId, reason) {
    const params = new URLSearchParams();
    if (reason) {
        params.set("reason", reason);
    }
    const suffix = params.toString() ? `?${params.toString()}` : "";
    const response = await fetch(`/api/zones/${encodeURIComponent(zoneId)}${suffix}`, {
        method: "DELETE",
    });
    if (!response.ok) {
        const body = await response.json().catch(() => null);
        throw new Error(body?.detail ?? `Zone delete failed with ${response.status}`);
    }
    return response.json();
}
export async function updateMarketContextOverride(timeframe, contextType, input) {
    const response = await fetch(`/api/contexts/${encodeURIComponent(timeframe)}/${encodeURIComponent(contextType)}`, {
        method: "PATCH",
        headers: {
            "Content-Type": "application/json",
        },
        body: JSON.stringify(input),
    });
    if (!response.ok) {
        const body = await response.json().catch(() => null);
        throw new Error(body?.detail ?? `Context update failed with ${response.status}`);
    }
    return response.json();
}
