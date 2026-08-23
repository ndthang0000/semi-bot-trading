import type { H1ImpulseMarker, M15TriggerOverlay, PriceZone, StructurePoint } from "../../types";

export type ZoneBox = {
  zone: PriceZone;
  x: number;
  y: number;
  width: number;
  height: number;
};

export type StructureDot = {
  point: StructurePoint;
  x: number;
  y: number;
};

export type SwingDot = StructureDot & {
  swingType: "high" | "low";
  label: string;
};

export type M15TriggerMarker = {
  trigger: M15TriggerOverlay;
  x: number;
  y: number;
};

export type H1ImpulseChartMarker = {
  marker: H1ImpulseMarker;
  x: number;
  y: number;
};

export type ZoneDragMode = "move" | "resize-top" | "resize-bottom" | "resize-left" | "resize-right";

export type ZoneDragState = {
  mode: ZoneDragMode;
  zone: PriceZone;
  startPointerPrice: number;
  startPointerTime: number;
  startLow: number;
  startHigh: number;
  startVisualStart: string;
  startVisualEnd: string | null;
};
