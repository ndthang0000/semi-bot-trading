import type { ChartPayload } from "../types";
type ContextStripProps = {
    payload: ChartPayload | undefined;
    onContextUpdated: () => void;
};
export declare function ContextStrip({ payload, onContextUpdated }: ContextStripProps): import("react/jsx-runtime").JSX.Element;
export {};
