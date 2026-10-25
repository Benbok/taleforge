const KEY = "tf_scene_header_collapsed";
const READING_KEY = "tf_reading_mode";
const CHAT_FONT_SIZE_KEY = "tf_chat_font_size";

export type ChatFontSize = "small" | "medium" | "large";

export function loadChatFontSize(): ChatFontSize {
  try {
    const v = localStorage.getItem(CHAT_FONT_SIZE_KEY);
    if (v === "small" || v === "medium" || v === "large") return v;
    return "medium";
  } catch {
    return "medium";
  }
}

export function saveChatFontSize(size: ChatFontSize): void {
  try {
    localStorage.setItem(CHAT_FONT_SIZE_KEY, size);
  } catch {
    // Storage is optional; the preference simply lasts for this render.
  }
}

export function loadReadingMode(): boolean {
  try {
    return localStorage.getItem(READING_KEY) === "true";
  } catch {
    return false;
  }
}

export function saveReadingMode(value: boolean): void {
  try {
    localStorage.setItem(READING_KEY, String(value));
  } catch {
    // The interface still works when browser storage is unavailable.
  }
}

export function loadSceneHeaderCollapsed(): boolean {
  try {
    return localStorage.getItem(KEY) === "true";
  } catch {
    return false;
  }
}

export function saveSceneHeaderCollapsed(value: boolean): void {
  try {
    localStorage.setItem(KEY, String(value));
  } catch {
    // Storage is optional; the preference simply lasts for this render.
  }
}
