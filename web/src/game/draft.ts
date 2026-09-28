// Черновик поля ввода: переживает обрыв связи и перезагрузку вкладки (документ дизайна: набранное не теряется).
import { create } from "zustand";

const key = (cid: string) => `tf_draft_${cid}`;

interface DraftState {
  campaignId: string | null;
  text: string;
  whisper: boolean;
  load(cid: string): void;
  setText(text: string): void;
  setWhisper(w: boolean): void;
  insert(text: string): void;
}

export const useDraft = create<DraftState>((set, get) => ({
  campaignId: null,
  text: "",
  whisper: false,
  load(cid) {
    let text = "";
    try {
      text = localStorage.getItem(key(cid)) ?? "";
    } catch {
      /* без хранилища черновик живёт до перезагрузки */
    }
    set({ campaignId: cid, text, whisper: false });
  },
  setText(text) {
    set({ text });
    const cid = get().campaignId;
    try {
      if (cid) {
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
  insert(text) {
    const cur = get().text.trim();
    get().setText(cur ? `${cur} ${text}` : text);
    document.getElementById("tf-composer")?.focus();
  },
}));
