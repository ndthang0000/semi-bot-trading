const state = {
  payload: null,
  visibleCount: 300,
  selected: null,
  hitTargets: [],
  timer: null,
};

const elements = {
  canvas: document.querySelector("#chart"),
  tooltip: document.querySelector("#tooltip"),
  timeframe: document.querySelector("#timeframe"),
  limit: document.querySelector("#limit"),
  activeZonesOnly: document.querySelector("#activeZonesOnly"),
  reload: document.querySelector("#reload"),
  biasValue: document.querySelector("#biasValue"),
  regimeValue: document.querySelector("#regimeValue"),
  rangeValue: document.querySelector("#rangeValue"),
  selectedDetails: document.querySelector("#selectedDetails"),
  zoneList: document.querySelector("#zoneList"),
  playPause: document.querySelector("#playPause"),
  stepBack: document.querySelector("#stepBack"),
  stepForward: document.querySelector("#stepForward"),
  replaySlider: document.querySelector("#replaySlider"),
  replayValue: document.querySelector("#replayValue"),
};

function clamp(value, min, max) {
  return Math.max(min, Math.min(max, value));
}

function priceFormat(value) {
  return Number(value).toFixed(2);
}

function shortTime(value) {
  if (!value) return "--";
  return value.replace("T", " ").replace("+00:00", "");
}

function typeClass(value) {
  if (["bullish", "support", "up", "HH", "HL"].includes(value)) return "bullish";
  if (["bearish", "resistance", "down", "LH", "LL"].includes(value)) return "bearish";
  return "";
}

async function loadChart() {
  stopReplay();
  const params = new URLSearchParams({
    symbol: "XAUUSD",
    timeframe: elements.timeframe.value,
    limit: elements.limit.value,
  });
  if (elements.activeZonesOnly.checked) params.set("active_zones_only", "true");

  const response = await fetch(`/api/chart?${params.toString()}`);
  const payload = await response.json();
  if (!response.ok || payload.error) {
    throw new Error(payload.error || "Cannot load chart payload");
  }
  state.payload = payload;
  state.visibleCount = payload.layers.candles.length;
  state.selected = null;
  syncReplayControls();
  render();
}

function syncReplayControls() {
  const total = state.payload?.layers.candles.length || 1;
  elements.replaySlider.max = String(total);
  elements.replaySlider.value = String(state.visibleCount);
  elements.replayValue.textContent = `${state.visibleCount} / ${total}`;
}

function visiblePayload() {
  const payload = state.payload;
  if (!payload) return null;
  const candles = payload.layers.candles.slice(0, state.visibleCount);
  const endTime = candles[candles.length - 1]?.time;
  const startTime = candles[0]?.time;
  return {
    candles,
    zones: payload.layers.zones.filter((zone) => {
      const zoneEnd = zone.visual_end || endTime;
      return zone.visual_start <= endTime && zoneEnd >= startTime;
    }),
    structure: payload.layers.structure.filter((point) => point.time >= startTime && point.time <= endTime),
    trades: payload.layers.trades.filter((trade) => {
      const opened = trade.opened_at || "";
      const closed = trade.closed_at || opened;
      return opened <= endTime && closed >= startTime;
    }),
    contexts: payload.layers.contexts,
    range: { start: startTime, end: endTime },
  };
}

function resizeCanvas() {
  const rect = elements.canvas.parentElement.getBoundingClientRect();
  const dpr = window.devicePixelRatio || 1;
  elements.canvas.width = Math.floor(rect.width * dpr);
  elements.canvas.height = Math.floor(rect.height * dpr);
  elements.canvas.style.width = `${rect.width}px`;
  elements.canvas.style.height = `${rect.height}px`;
  return { width: rect.width, height: rect.height, dpr };
}

function render() {
  const view = visiblePayload();
  const { width, height, dpr } = resizeCanvas();
  const ctx = elements.canvas.getContext("2d");
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  ctx.clearRect(0, 0, width, height);
  state.hitTargets = [];

  if (!view || view.candles.length === 0) {
    drawEmpty(ctx, width, height);
    return;
  }

  const padding = { left: 64, right: 82, top: 26, bottom: 34 };
  const values = view.candles.flatMap((candle) => [candle.high, candle.low]);
  for (const zone of view.zones) values.push(zone.price_low, zone.price_high);
  const min = Math.min(...values);
  const max = Math.max(...values);
  const span = Math.max(max - min, 1);
  const priceMin = min - span * 0.08;
  const priceMax = max + span * 0.08;
  const plot = {
    x: padding.left,
    y: padding.top,
    w: width - padding.left - padding.right,
    h: height - padding.top - padding.bottom,
  };
  const candleWidth = Math.max(2, plot.w / view.candles.length);
  const timeIndex = new Map(view.candles.map((candle, index) => [candle.time, index]));
  const xAt = (index) => plot.x + index * candleWidth + candleWidth / 2;
  const yAt = (price) => plot.y + ((priceMax - price) / (priceMax - priceMin)) * plot.h;

  drawGrid(ctx, plot, priceMin, priceMax, yAt);
  drawZones(ctx, view, plot, timeIndex, candleWidth, xAt, yAt);
  drawCandles(ctx, view.candles, candleWidth, xAt, yAt);
  drawStructure(ctx, view.structure, xAt, yAt, timeIndex);
  drawTrades(ctx, view.trades, xAt, yAt, timeIndex, plot);
  drawAxes(ctx, view, plot, priceMin, priceMax, yAt);
  updateContext(view);
  updateZoneList(view.zones);
  updateSelectedDetails();
}

function drawEmpty(ctx, width, height) {
  ctx.fillStyle = "#8d9aab";
  ctx.textAlign = "center";
  ctx.fillText("No chart data", width / 2, height / 2);
}

function drawGrid(ctx, plot, priceMin, priceMax, yAt) {
  ctx.strokeStyle = "#151b24";
  ctx.lineWidth = 1;
  ctx.font = "12px system-ui";
  ctx.fillStyle = "#768397";
  for (let i = 0; i <= 6; i += 1) {
    const price = priceMin + ((priceMax - priceMin) / 6) * i;
    const y = yAt(price);
    ctx.beginPath();
    ctx.moveTo(plot.x, y);
    ctx.lineTo(plot.x + plot.w, y);
    ctx.stroke();
    ctx.textAlign = "left";
    ctx.fillText(priceFormat(price), plot.x + plot.w + 10, y + 4);
  }
}

function drawZones(ctx, view, plot, timeIndex, candleWidth, xAt, yAt) {
  for (const zone of view.zones) {
    const startIndex = firstIndexAtOrAfter(view.candles, zone.visual_start);
    const endIndex = zone.visual_end ? lastIndexAtOrBefore(view.candles, zone.visual_end) : view.candles.length - 1;
    if (startIndex < 0 || endIndex < 0 || endIndex < startIndex) continue;

    const x = Math.max(plot.x, xAt(startIndex) - candleWidth / 2);
    const right = Math.min(plot.x + plot.w, xAt(endIndex) + candleWidth / 2);
    const y1 = yAt(zone.price_high);
    const y2 = yAt(zone.price_low);
    const active = zone.status === "active";
    const bullish = zone.direction === "bullish";
    const fill = bullish ? "rgba(51, 194, 127, 0.14)" : "rgba(239, 95, 103, 0.14)";
    const stroke = bullish ? "rgba(51, 194, 127, 0.72)" : "rgba(239, 95, 103, 0.72)";

    ctx.fillStyle = active ? fill : "rgba(141, 154, 171, 0.10)";
    ctx.strokeStyle = active ? stroke : "rgba(141, 154, 171, 0.35)";
    ctx.lineWidth = state.selected?.id === zone.id ? 2 : 1;
    ctx.setLineDash(active ? [] : [5, 5]);
    ctx.fillRect(x, y1, right - x, y2 - y1);
    ctx.strokeRect(x, y1, right - x, y2 - y1);
    ctx.setLineDash([]);
    if (state.selected?.id === zone.id || (right - x > 220 && y2 - y1 > 18 && zone.weight >= 0.55)) {
      ctx.fillStyle = active ? stroke : "#8d9aab";
      ctx.font = "11px system-ui";
      ctx.textAlign = "left";
      ctx.fillText(`${zone.type} ${zone.status} w:${zone.weight.toFixed(2)}`, x + 6, y1 + 14);
    }

    state.hitTargets.push({ kind: "zone", entity: zone, x, y: y1, w: right - x, h: y2 - y1 });
  }
}

function drawCandles(ctx, candles, candleWidth, xAt, yAt) {
  const bodyWidth = Math.max(2, Math.min(9, candleWidth * 0.62));
  candles.forEach((candle, index) => {
    const x = xAt(index);
    const up = candle.close >= candle.open;
    const color = up ? "#33c27f" : "#ef5f67";
    const openY = yAt(candle.open);
    const closeY = yAt(candle.close);
    ctx.strokeStyle = color;
    ctx.fillStyle = color;
    ctx.lineWidth = 1;
    ctx.beginPath();
    ctx.moveTo(x, yAt(candle.high));
    ctx.lineTo(x, yAt(candle.low));
    ctx.stroke();
    const bodyTop = Math.min(openY, closeY);
    const bodyHeight = Math.max(1, Math.abs(openY - closeY));
    ctx.fillRect(x - bodyWidth / 2, bodyTop, bodyWidth, bodyHeight);
  });
}

function drawStructure(ctx, points, xAt, yAt, timeIndex) {
  ctx.font = "10px system-ui";
  for (const point of points) {
    const index = timeIndex.get(point.time);
    if (index === undefined) continue;
    const x = xAt(index);
    const y = yAt(point.price);
    const bearish = ["LH", "LL"].includes(point.type) || point.direction === "down";
    ctx.fillStyle = bearish ? "#ef5f67" : "#33c27f";
    ctx.beginPath();
    ctx.arc(x, y, 4, 0, Math.PI * 2);
    ctx.fill();
    if (state.selected?.id === point.id || points.length <= 30) {
      ctx.fillStyle = "#dce6f2";
      ctx.textAlign = "center";
      ctx.fillText(point.type, x, y + (bearish ? 16 : -8));
    }
    state.hitTargets.push({ kind: "structure", entity: point, x: x - 8, y: y - 8, w: 16, h: 16 });
  }
}

function drawTrades(ctx, trades, xAt, yAt, timeIndex, plot) {
  for (const trade of trades) {
    const index = timeIndex.get(trade.opened_at);
    if (index === undefined || trade.entry_price === null) continue;
    const x = xAt(index);
    const y = yAt(trade.entry_price);
    ctx.fillStyle = trade.side === "buy" ? "#62b9ff" : "#d8a347";
    ctx.beginPath();
    ctx.moveTo(x, y - 7);
    ctx.lineTo(x + 7, y + 7);
    ctx.lineTo(x - 7, y + 7);
    ctx.closePath();
    ctx.fill();
    if (trade.stop_loss) {
      drawTradeLine(ctx, plot, yAt(trade.stop_loss), "#ef5f67", "SL");
    }
    for (const target of trade.take_profit || []) {
      const price = typeof target === "number" ? target : target.price;
      if (price) drawTradeLine(ctx, plot, yAt(price), "#33c27f", "TP");
    }
  }
}

function drawTradeLine(ctx, plot, y, color, label) {
  ctx.strokeStyle = color;
  ctx.fillStyle = color;
  ctx.setLineDash([4, 4]);
  ctx.beginPath();
  ctx.moveTo(plot.x, y);
  ctx.lineTo(plot.x + plot.w, y);
  ctx.stroke();
  ctx.setLineDash([]);
  ctx.fillText(label, plot.x + 4, y - 4);
}

function drawAxes(ctx, view, plot) {
  ctx.strokeStyle = "#242c38";
  ctx.strokeRect(plot.x, plot.y, plot.w, plot.h);
  ctx.fillStyle = "#768397";
  ctx.font = "12px system-ui";
  ctx.textAlign = "left";
  ctx.fillText(shortTime(view.range.start), plot.x, plot.y + plot.h + 22);
  ctx.textAlign = "right";
  ctx.fillText(shortTime(view.range.end), plot.x + plot.w, plot.y + plot.h + 22);
}

function firstIndexAtOrAfter(candles, time) {
  return candles.findIndex((candle) => candle.time >= time);
}

function lastIndexAtOrBefore(candles, time) {
  for (let index = candles.length - 1; index >= 0; index -= 1) {
    if (candles[index].time <= time) return index;
  }
  return -1;
}

function updateContext(view) {
  const h1 = view.contexts.H1 || {};
  const bias = h1.bias?.effective_value || "--";
  const regime = h1.regime?.effective_value || "--";
  const overlays = h1.regime?.metadata?.overlays || [];
  elements.biasValue.textContent = bias;
  elements.biasValue.className = typeClass(bias);
  elements.regimeValue.textContent = overlays.length ? `${regime} + ${overlays.join(" + ")}` : regime;
  elements.rangeValue.textContent = `${shortTime(view.range.start)} -> ${shortTime(view.range.end)}`;
}

function updateZoneList(zones) {
  elements.zoneList.innerHTML = "";
  for (const zone of zones.slice().sort((a, b) => b.weight - a.weight)) {
    const button = document.createElement("button");
    button.type = "button";
    button.className = `zone-item ${state.selected?.id === zone.id ? "active" : ""}`;
    button.innerHTML = `
      <div class="zone-title">
        <span class="${typeClass(zone.type)}">${zone.type}</span>
        <span>${zone.status}</span>
      </div>
      <div class="zone-meta">${priceFormat(zone.price_low)} - ${priceFormat(zone.price_high)} · w ${zone.weight.toFixed(2)}</div>
    `;
    button.addEventListener("click", () => selectEntity("zone", zone));
    elements.zoneList.appendChild(button);
  }
}

function updateSelectedDetails() {
  const selected = state.selected;
  if (!selected) {
    elements.selectedDetails.className = "empty";
    elements.selectedDetails.textContent = "Click a zone or marker";
    return;
  }
  const entity = selected.entity;
  elements.selectedDetails.className = "detail-grid";
  if (selected.kind === "zone") {
    elements.selectedDetails.innerHTML = detailRows([
      ["Type", entity.type],
      ["Status", entity.status],
      ["Price", `${priceFormat(entity.price_low)} - ${priceFormat(entity.price_high)}`],
      ["Weight", entity.weight.toFixed(4)],
      ["Source", entity.source],
      ["Start", shortTime(entity.visual_start)],
      ["End", shortTime(entity.visual_end)],
      ["Touches", entity.metadata.touch_count_total ?? entity.metadata.touch_count ?? "--"],
    ]);
  } else {
    elements.selectedDetails.innerHTML = detailRows([
      ["Type", entity.type],
      ["Price", priceFormat(entity.price)],
      ["Time", shortTime(entity.time)],
      ["Detector", entity.detector],
      ["Direction", entity.direction || "--"],
    ]);
  }
}

function detailRows(rows) {
  return rows.map(([key, value]) => `<div class="detail-row"><span>${key}</span><strong>${value}</strong></div>`).join("");
}

function selectEntity(kind, entity) {
  state.selected = { kind, entity, id: entity.id };
  render();
}

function stopReplay() {
  if (state.timer) {
    clearInterval(state.timer);
    state.timer = null;
  }
  elements.playPause.textContent = "Play";
}

function toggleReplay() {
  if (!state.payload) return;
  if (state.timer) {
    stopReplay();
    return;
  }
  elements.playPause.textContent = "Pause";
  state.timer = setInterval(() => {
    const total = state.payload.layers.candles.length;
    if (state.visibleCount >= total) {
      stopReplay();
      return;
    }
    state.visibleCount += 1;
    syncReplayControls();
    render();
  }, 180);
}

function step(delta) {
  if (!state.payload) return;
  stopReplay();
  state.visibleCount = clamp(state.visibleCount + delta, 1, state.payload.layers.candles.length);
  syncReplayControls();
  render();
}

function pointerTarget(event) {
  const rect = elements.canvas.getBoundingClientRect();
  const x = event.clientX - rect.left;
  const y = event.clientY - rect.top;
  for (let index = state.hitTargets.length - 1; index >= 0; index -= 1) {
    const target = state.hitTargets[index];
    if (x >= target.x && x <= target.x + target.w && y >= target.y && y <= target.y + target.h) {
      return target;
    }
  }
  return null;
}

elements.reload.addEventListener("click", () => loadChart().catch(showError));
elements.timeframe.addEventListener("change", () => loadChart().catch(showError));
elements.activeZonesOnly.addEventListener("change", () => loadChart().catch(showError));
elements.playPause.addEventListener("click", toggleReplay);
elements.stepBack.addEventListener("click", () => step(-1));
elements.stepForward.addEventListener("click", () => step(1));
elements.replaySlider.addEventListener("input", () => {
  if (!state.payload) return;
  stopReplay();
  state.visibleCount = Number(elements.replaySlider.value);
  syncReplayControls();
  render();
});
elements.canvas.addEventListener("mousemove", (event) => {
  const target = pointerTarget(event);
  if (!target) {
    elements.tooltip.classList.add("hidden");
    return;
  }
  elements.tooltip.classList.remove("hidden");
  elements.tooltip.style.left = `${event.offsetX + 12}px`;
  elements.tooltip.style.top = `${event.offsetY + 12}px`;
  if (target.kind === "zone") {
    elements.tooltip.textContent = `${target.entity.type} ${target.entity.status} ${priceFormat(target.entity.price_low)}-${priceFormat(target.entity.price_high)}`;
  } else {
    elements.tooltip.textContent = `${target.entity.type} ${priceFormat(target.entity.price)} ${shortTime(target.entity.time)}`;
  }
});
elements.canvas.addEventListener("mouseleave", () => elements.tooltip.classList.add("hidden"));
elements.canvas.addEventListener("click", (event) => {
  const target = pointerTarget(event);
  if (target) selectEntity(target.kind, target.entity);
});
window.addEventListener("resize", render);

function showError(error) {
  elements.selectedDetails.className = "empty";
  elements.selectedDetails.textContent = error.message;
}

loadChart().catch(showError);
