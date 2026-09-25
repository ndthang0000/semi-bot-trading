import { create } from "zustand";

type QuickOrderState = {
  open: boolean;
  setOpen: (open: boolean) => void;
};

export const useQuickOrderStore = create<QuickOrderState>((set) => ({
  open: false,
  setOpen: (open) => set({ open }),
}));
