// Уведомления о результате действий (правило Arty: каждое нажатие даёт видимый ответ, ошибка — с причиной).
import { create } from "zustand";

export type Tone = "ok" | "error" | "info";

export interface Toast {
  id: number;
  tone: Tone;
  text: string;
}

interface ToastState {
  items: Toast[];
  push(tone: Tone, text: string): void;
  dismiss(id: number): void;
}

let next = 1;
export const TOAST_MS: Record<Tone, number> = { ok: 3500, info: 4500, error: 8000 };

export const useToasts = create<ToastState>((set, get) => ({
  items: [],
  push(tone, text) {
    const id = next++;
    // одно и то же сообщение подряд не множим
    if (get().items.some((t) => t.text === text && t.tone === tone)) return;
    set((s) => ({ items: [...s.items.slice(-3), { id, tone, text }] }));
    setTimeout(() => get().dismiss(id), TOAST_MS[tone]);
  },
  dismiss(id) {
    set((s) => ({ items: s.items.filter((t) => t.id !== id) }));
  },
}));

export const toast = {
  ok: (text: string) => useToasts.getState().push("ok", text),
  error: (text: string) => useToasts.getState().push("error", text),
  info: (text: string) => useToasts.getState().push("info", text),
};
