// Уведомления о результате действий (правило Arty: каждое нажатие даёт видимый ответ, ошибка — с причиной).
import { create } from "zustand";
let next = 1;
export const TOAST_MS = { ok: 3500, info: 4500, error: 8000 };
export const useToasts = create((set, get) => ({
    items: [],
    push(tone, text) {
        const id = next++;
        // одно и то же сообщение подряд не множим
        if (get().items.some((t) => t.text === text && t.tone === tone))
            return;
        set((s) => ({ items: [...s.items.slice(-3), { id, tone, text }] }));
        setTimeout(() => get().dismiss(id), TOAST_MS[tone]);
    },
    dismiss(id) {
        set((s) => ({ items: s.items.filter((t) => t.id !== id) }));
    },
}));
export const toast = {
    ok: (text) => useToasts.getState().push("ok", text),
    error: (text) => useToasts.getState().push("error", text),
    info: (text) => useToasts.getState().push("info", text),
};
