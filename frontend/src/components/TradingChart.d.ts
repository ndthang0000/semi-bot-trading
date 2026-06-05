import type { ChartPayload } from "../types";
type TradingChartProps = {
    payload: ChartPayload;
    onEntityCreated: () => void;
};
export declare function TradingChart({ payload, onEntityCreated }: TradingChartProps): import("react/jsx-runtime").JSX.Element;
export {};
