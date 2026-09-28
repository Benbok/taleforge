const MODE_KEY = "tf_theme_mode";
export function savedMode() {
    try {
        const m = localStorage.getItem(MODE_KEY);
        if (m === "dark" || m === "light")
            return m;
    }
    catch {
        /* нет доступа к хранилищу */
    }
    return "dark"; // тёмная тема по умолчанию (документ дизайна)
}
export function saveMode(mode) {
    try {
        localStorage.setItem(MODE_KEY, mode);
    }
    catch {
        /* не страшно: выбор просто не запомнится */
    }
}
export function cssVars(theme, mode) {
    const vars = {};
    for (const [k, v] of Object.entries(theme[mode]))
        vars[`--tf-${k.replace(/_/g, "-")}`] = v;
    vars["--tf-font-narration"] = theme.fonts.narration;
    vars["--tf-font-ui"] = theme.fonts.ui;
    vars["--tf-font-heading"] = theme.fonts.heading;
    return vars;
}
export function applyTheme(theme, mode, root = document.documentElement) {
    for (const [k, v] of Object.entries(cssVars(theme, mode)))
        root.style.setProperty(k, v);
    root.dataset.theme = mode;
    if (theme.font_css && theme.font_css.startsWith("https://fonts.googleapis.com/")) {
        let link = document.getElementById("tf-fonts");
        if (!link) {
            link = document.createElement("link");
            link.id = "tf-fonts";
            link.rel = "stylesheet";
            document.head.appendChild(link);
        }
        if (link.href !== theme.font_css)
            link.href = theme.font_css;
    }
}
export function label(theme, key, fallback) {
    return theme?.labels[key] ?? fallback;
}
