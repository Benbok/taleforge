const KEY = "tf_scene_header_collapsed";
const READING_KEY = "tf_reading_mode";

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
