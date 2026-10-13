// Кто вошёл и какая тема сейчас на экране.
import { create } from "zustand";
import { api, getToken, setToken } from "../lib/api";
import { applyTheme, initThemeMode, saveMode, type Mode } from "../lib/theme";
import type { Theme, User } from "../lib/types";
import { useMenuMusicPreferences } from "../audio/menuMusicPreferences";

interface SessionState {
  user: User | null;
  ready: boolean;
  theme: Theme | null;
  mode: Mode;
  boot(): Promise<void>;
  signIn(token: string, user: User): void;
  signOut(): void;
  setUser(user: User): void;
  setTheme(theme: Theme): void;
  toggleMode(): void;
}

export const useSession = create<SessionState>((set, get) => ({
  user: null,
  ready: false,
  theme: null,
  mode: initThemeMode(),

  async boot() {
    let user: User | null = null;
    if (getToken()) {
      try {
        user = await api<User>("/api/auth/me");
      } catch {
        setToken(null);
      }
    }
    set({ user, ready: true });
    useMenuMusicPreferences.getState().bindUser(user);
  },

  signIn(token, user) {
    setToken(token);
    set({ user, ready: true });
    useMenuMusicPreferences.getState().bindUser(user);
  },

  setUser(user) {
    set({ user });
    useMenuMusicPreferences.getState().bindUser(user);
  },

  signOut() {
    setToken(null);
    set({ user: null });
    useMenuMusicPreferences.getState().bindUser(null);
  },

  setTheme(theme) {
    applyTheme(theme, get().mode);
    set({ theme });
  },

  toggleMode() {
    const mode: Mode = get().mode === "dark" ? "light" : "dark";
    saveMode(mode);
    if (typeof document !== "undefined") {
      document.documentElement.dataset.theme = mode;
    }
    const theme = get().theme;
    if (theme) applyTheme(theme, mode);
    set({ mode });
  },
}));
