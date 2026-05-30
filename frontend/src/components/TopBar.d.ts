type TopBarProps = {
    isFetching: boolean;
    mode: "dashboard" | "replay";
    onRefresh: () => void;
};
export declare function TopBar({ isFetching, mode, onRefresh }: TopBarProps): import("react/jsx-runtime").JSX.Element;
export {};
