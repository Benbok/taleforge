// Тема: токены пакета ставятся CSS-переменными на :root. Режим (тёмный или светлый) — выбор игрока,
// хранится в браузере. Раскладку тема не трогает.
import type { Theme } from "./types";

export type Mode = "dark" | "light";
const MODE_KEY = "tf_theme_mode";

export function savedMode(): Mode {
  try {
    const m = localStorage.getItem(MODE_KEY);
    if (m === "dark" || m === "light") return m;
  } catch {
    /* нет доступа к хранилищу */
  }
  return "dark"; // тёмная тема по умолчанию (документ дизайна)
}

export function saveMode(mode: Mode): void {
  try {
    localStorage.setItem(MODE_KEY, mode);
  } catch {
    /* не страшно: выбор просто не запомнится */
  }
}

export function cssVars(theme: Theme, mode: Mode): Record<string, string> {
  const vars: Record<string, string> = {};
  for (const [k, v] of Object.entries(theme[mode])) vars[`--tf-${k.replace(/_/g, "-")}`] = v;
  vars["--tf-font-narration"] = theme.fonts.narration;
  vars["--tf-font-ui"] = theme.fonts.ui;
  vars["--tf-font-heading"] = theme.fonts.heading;
  return vars;
}

export function applyTheme(theme: Theme, mode: Mode, root: HTMLElement = document.documentElement): void {
  for (const [k, v] of Object.entries(cssVars(theme, mode))) root.style.setProperty(k, v);
  root.dataset.theme = mode;
  if (theme.font_css && theme.font_css.startsWith("https://fonts.googleapis.com/")) {
    let link = document.getElementById("tf-fonts") as HTMLLinkElement | null;
    if (!link) {
      link = document.createElement("link");
      link.id = "tf-fonts";
      link.rel = "stylesheet";
      document.head.appendChild(link);
    }
    if (link.href !== theme.font_css) link.href = theme.font_css;
  }
}

export function label(theme: Theme | null, key: string, fallback: string): string {
  return theme?.labels[key] ?? fallback;
}
