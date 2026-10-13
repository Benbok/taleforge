import type { LocationPresentation } from "../lib/types";
import type { Mode } from "../lib/theme";

export interface SceneArt {
  src: string;
  focus: string;
}

export const SCENE_ART: Record<string, SceneArt> = {
  neutral: { src: "/assets/scenes/neutral.svg", focus: "50% 50%" },
  tavern: { src: "/assets/scenes/tavern.svg", focus: "50% 55%" },
  coast: { src: "/assets/scenes/coast.svg", focus: "50% 50%" },
  forest: { src: "/assets/scenes/forest.svg", focus: "50% 50%" },
  ruins: { src: "/assets/scenes/ruins.svg", focus: "50% 55%" },
  crypt: { src: "/assets/scenes/crypt.svg", focus: "50% 50%" },
  sanctuary: { src: "/assets/scenes/sanctuary.svg", focus: "50% 45%" },
};

const PERIODS: Record<string, string> = { dawn: "Рассвет", day: "День", dusk: "Сумерки", night: "Ночь" };
const WEATHER: Record<string, string> = { clear: "Ясно", cloudy: "Пасмурно", rain: "Дождь", fog: "Туман", snow: "Снег" };

export function resolveSceneArt(presentation: LocationPresentation | null | undefined): SceneArt {
  const preset = presentation?.preset && SCENE_ART[presentation.preset] ? presentation.preset : "neutral";
  const base = SCENE_ART[preset];
  const key = presentation?.illustration_key;
  return key && /^[a-z0-9_-]{1,64}$/.test(key) && SCENE_ART[key] ? SCENE_ART[key] : base;
}

export function presentationSubtitle(presentation: LocationPresentation | null | undefined): string {
  return [presentation?.period ? PERIODS[presentation.period] : null, presentation?.weather ? WEATHER[presentation.weather] : null]
    .filter(Boolean)
    .join(" · ");
}

const GLOW: Record<string, string> = {
  neutral: "#b87333",
  tavern: "#d59a5c",
  coast: "#5fae9f",
  forest: "#76956b",
  ruins: "#9b917d",
  crypt: "#8c789a",
  sanctuary: "#d2bd8c",
};

export function sceneLighting(
  presentation: LocationPresentation | null | undefined,
  mode: Mode,
  combat: boolean,
): Record<string, string> {
  const glow = GLOW[presentation?.preset ?? "neutral"] ?? GLOW.neutral;
  const base = mode === "dark" ? 0.14 : 0.06;
  const opacity = presentation?.period === "night" ? base * 0.75 : base;
  return {
    "--tf-scene-glow": glow,
    "--tf-scene-glow-opacity": opacity.toFixed(3),
    "--tf-scene-edge": combat ? "#c4553f" : "transparent",
    "--tf-scene-edge-opacity": combat ? (mode === "dark" ? "0.08" : "0.04") : "0",
  };
}
