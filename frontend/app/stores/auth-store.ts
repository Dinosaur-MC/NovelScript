import { create } from "zustand";
import { me, type User } from "../api/auth";

interface AuthState {
  user: User | null;
  loaded: boolean;
  fetchUser: () => Promise<void>;
  setUser: (user: User) => void;
  clearUser: () => void;
}

export const useAuthStore = create<AuthState>((set) => ({
  user: null,
  loaded: false,

  fetchUser: async () => {
    try {
      const token = typeof window !== "undefined" && localStorage.getItem("auth_token");
      if (!token) {
        set({ loaded: true });
        return;
      }
      const u = await me();
      set({ user: u, loaded: true });
    } catch {
      set({ loaded: true });
    }
  },

  setUser: (user) => set({ user, loaded: true }),

  clearUser: () => {
    if (typeof window !== "undefined") localStorage.removeItem("auth_token");
    set({ user: null, loaded: true });
  },
}));
