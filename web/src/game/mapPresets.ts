export const MAP_PRESETS = {
  hero: { icon: "★", color: "#c98a4b" },
  creature: { icon: "⚔", color: "#c0563a" },
  npc: { icon: "●", color: "#5f9e8f" },
  item: { icon: "◆", color: "#b07a4a" },
  landmark: { icon: "◈", color: "#a8a296" },
  location: { icon: "⌖", color: "#5f9e8f" },
  lore: { icon: "◇", color: "#a8a296" },
} as const;

/** Абстрактные пресеты проходов и деталей эскиза. */
export const EXIT_PRESETS = {
  door: "▯",
  bars: "#",
  window: "◫",
  arch: "∩",
  stairs: "≡",
  hatch: "⊡",
  gap: "⌇",
  passage: "→",
} as const;
