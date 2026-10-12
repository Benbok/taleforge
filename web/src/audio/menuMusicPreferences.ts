import { create } from "zustand";
import { api } from "../lib/api";
import type { MenuMusicPreferences, User } from "../lib/types";

export type MenuMusicSaveState = "saved" | "saving" | "error";
export const DEFAULT_MENU_MUSIC: MenuMusicPreferences = { enabled: true, volume: 0.2 };

interface MenuMusicState {
  userId: string | null;
  prefs: MenuMusicPreferences;
  saveState: MenuMusicSaveState;
  bindUser(user: User | null): void;
  update(patch: Partial<MenuMusicPreferences>): void;
  retry(): void;
}

let generation = 0;
let timer: ReturnType<typeof setTimeout> | null = null;
let pending: Partial<MenuMusicPreferences> | null = null;
let inFlight = false;
let saved: MenuMusicPreferences = { ...DEFAULT_MENU_MUSIC };

function clearTimer() {
  if (timer !== null) clearTimeout(timer);
  timer = null;
}

function patchFrom(prefs: MenuMusicPreferences): Partial<MenuMusicPreferences> {
  const patch: Partial<MenuMusicPreferences> = {};
  if (prefs.enabled !== saved.enabled) patch.enabled = prefs.enabled;
  if (prefs.volume !== saved.volume) patch.volume = prefs.volume;
  return patch;
}

async function flush(get: () => MenuMusicState, set: (value: Partial<MenuMusicState>) => void) {
  if (inFlight || !pending) return;
  const mine = generation;
  const body = pending;
  pending = null;
  inFlight = true;
  let continuePending = true;
  set({ saveState: "saving" });
  try {
    const response = await api<MenuMusicPreferences>("/api/me/menu-music", { method: "PATCH", body });
    if (mine === generation) {
      const acknowledged = Object.entries(body).every(([key, value]) => response?.[key as keyof MenuMusicPreferences] === value);
      if (!acknowledged) {
        pending = { ...body, ...(pending ?? {}) };
        continuePending = false;
        set({ saveState: "error" });
        return;
      }
      saved = { ...saved, ...response };
      const remaining = patchFrom(get().prefs);
      if (Object.keys(remaining).length > 0) pending = { ...(pending ?? {}), ...remaining };
      set({ saveState: pending ? "saving" : "saved" });
    }
  } catch {
    if (mine === generation) {
      pending = { ...body, ...(pending ?? {}) };
      continuePending = false;
      set({ saveState: "error" });
    }
  } finally {
    inFlight = false;
    if (continuePending && pending) void flush(get, set);
  }
}

function schedule(get: () => MenuMusicState, set: (value: Partial<MenuMusicState>) => void) {
  clearTimer();
  timer = setTimeout(() => {
    timer = null;
    void flush(get, set);
  }, 250);
}

export const useMenuMusicPreferences = create<MenuMusicState>((set, get) => ({
  userId: null,
  prefs: { ...DEFAULT_MENU_MUSIC },
  saveState: "saved",

  bindUser(user) {
    generation++;
    clearTimer();
    pending = null;
    saved = user?.menu_music ? { ...user.menu_music } : { ...DEFAULT_MENU_MUSIC };
    set({ userId: user?.id ?? null, prefs: { ...saved }, saveState: "saved" });
  },

  update(patch) {
    const prefs = { ...get().prefs, ...patch };
    if (!get().userId) {
      set({ prefs, saveState: "saved" });
      return;
    }
    pending = { ...pending, ...patch };
    set({ prefs, saveState: "saving" });
    schedule(get, set);
  },

  retry() {
    if (!get().userId || get().saveState !== "error") return;
    pending = patchFrom(get().prefs);
    if (!pending || Object.keys(pending).length === 0) {
      set({ saveState: "saved" });
      return;
    }
    set({ saveState: "saving" });
    schedule(get, set);
  },
}));
