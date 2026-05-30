import type { ChartPayload } from "../types";
type InspectorProps = {
    payload: ChartPayload | undefined;
    onZoneUpdated: () => void;
};
export declare function Inspector({ payload, onZoneUpdated }: InspectorProps): import("react/jsx-runtime").JSX.Element;
export {};
