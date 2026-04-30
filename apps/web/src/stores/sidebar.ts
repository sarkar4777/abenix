import { create } from 'zustand';

interface SidebarState {
  collapsed: boolean;
  mobileOpen: boolean;
  toggle: () => void;
  setMobileOpen: (open: boolean) => void;
  closeMobile: () => void;
}

export const useSidebar = create<SidebarState>((set) => ({
  collapsed: false,
  mobileOpen: false,
  toggle: () => set((s) => ({ collapsed: !s.collapsed })),
  setMobileOpen: (open: boolean) => set({ mobileOpen: open }),
  closeMobile: () => set({ mobileOpen: false }),
}));
