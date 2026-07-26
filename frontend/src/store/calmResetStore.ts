import { create } from "zustand";
import type { CalmOutcome, CalmTradeEvent } from "../lib/calmReset";
import type { AppPage } from "./navigationStore";

interface CalmResetState {
  event: CalmTradeEvent | null;
  message: string | null;
  returnPage: AppPage;
  previewOutcome: CalmOutcome | null;
  begin: (event: CalmTradeEvent, message: string, returnPage: AppPage) => void;
  setMessage: (message: string) => void;
  requestPreview: (outcome: CalmOutcome) => void;
  consumePreview: () => void;
  complete: () => void;
}

export const useCalmResetStore = create<CalmResetState>((set) => ({
  event: null,
  message: null,
  returnPage: "chart",
  previewOutcome: null,
  begin: (event, message, returnPage) => set({ event, message, returnPage }),
  setMessage: (message) => set({ message }),
  requestPreview: (previewOutcome) => set({ previewOutcome }),
  consumePreview: () => set({ previewOutcome: null }),
  complete: () => set({ event: null, message: null }),
}));
