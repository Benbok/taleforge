const KEY = "tf_scene_header_collapsed";

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
