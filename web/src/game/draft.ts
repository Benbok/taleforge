// Черновик поля ввода: переживает обрыв связи и перезагрузку вкладки (документ дизайна: набранное не теряется).
import { create } from "zustand";
import type { QuickAction } from "./quick";

const key = (cid: string) => `tf_draft_${cid}`;
const actionKey = (cid: string) => `tf_draft_action_${cid}`;

interface DraftState {
  campaignId: string | null;
  text: string;
  whisper: boolean;
  quick: QuickAction[] | null;
  load(cid: string): void;
  setText(text: string): void;
  setWhisper(w: boolean): void;
  insert(text: string, action?: QuickAction): void;
}

export const useDraft = create<DraftState>((set, get) => ({
  campaignId: null,
  text: "",
  whisper: false,
  quick: null,
  load(cid) {
    let text = "";
    let quick: QuickAction[] | null = null;
    try {
      text = localStorage.getItem(key(cid)) ?? "";
      const saved = JSON.parse(localStorage.getItem(actionKey(cid)) ?? "null");
      if (saved?.text === text && Array.isArray(saved.actions)) quick = saved.actions;
    } catch {
      /* без хранилища черновик живёт до перезагрузки */
    }
    set({ campaignId: cid, text, whisper: false, quick });
  },
  setText(text) {
    const quick = get().text === text ? get().quick : null;
    set({ text, quick });
    const cid = get().campaignId;
    try {
      if (cid) {
        if (!quick) localStorage.removeItem(actionKey(cid));
        if (text) localStorage.setItem(key(cid), text);
        else localStorage.removeItem(key(cid));
      }
    } catch {
      /* не страшно */
    }
  },
  setWhisper(whisper) {
    set({ whisper });
  },
  insert(text, action) {
    const cur = get().text.trim();
    get().setText(cur ? `${cur} ${text}` : text);
    if (!cur && action) {
      const quick = [action];
      set({ quick });
      try {
        const cid = get().campaignId;
        if (cid) localStorage.setItem(actionKey(cid), JSON.stringify({ text, actions: quick }));
      } catch {
        /* без хранилища намерение живёт вместе с черновиком в памяти */
      }
    }
    document.getElementById("tf-composer")?.focus();
  },
}));
