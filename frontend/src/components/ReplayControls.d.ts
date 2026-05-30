import type { ReplayTimeline } from "../types";
type ReplayControlsProps = {
    isPlaying: boolean;
    speedSeconds: number;
    timeline: ReplayTimeline | undefined;
    currentIndex: number;
    onPlayingChange: (playing: boolean) => void;
    onSpeedChange: (seconds: number) => void;
    onStep: (delta: number) => void;
};
export declare function ReplayControls({ isPlaying, speedSeconds, timeline, currentIndex, onPlayingChange, onSpeedChange, onStep, }: ReplayControlsProps): import("react/jsx-runtime").JSX.Element;
export {};
