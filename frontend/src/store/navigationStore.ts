import { create } from "zustand";

export type AppPage = "chart" | "dashboard" | "journal" | "weekly-journal" | "calm";

interface NavigationState {
  activePage: AppPage;
  setPage: (page: AppPage) => void;
}

export const useNavigationStore = create<NavigationState>((set) => ({
  activePage: "chart",
  setPage: (page) => set({ activePage: page }),
}));
