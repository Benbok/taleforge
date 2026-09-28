// Кто вошёл и какая тема сейчас на экране.
import { create } from "zustand";
import { api, getToken, setToken } from "../lib/api";
import { applyTheme, saveMode, savedMode } from "../lib/theme";
export const useSession = create((set, get) => ({
    user: null,
    ready: false,
    theme: null,
    mode: savedMode(),
    async boot() {
        let user = null;
        if (getToken()) {
            try {
                user = await api("/api/auth/me");
            }
            catch {
                setToken(null);
            }
        }
        set({ user, ready: true });
    },
    signIn(token, user) {
        setToken(token);
        set({ user, ready: true });
    },
    signOut() {
        setToken(null);
        set({ user: null });
    },
    setTheme(theme) {
        applyTheme(theme, get().mode);
        set({ theme });
    },
    toggleMode() {
        const mode = get().mode === "dark" ? "light" : "dark";
        saveMode(mode);
        const theme = get().theme;
        if (theme)
            applyTheme(theme, mode);
        set({ mode });
    },
}));
