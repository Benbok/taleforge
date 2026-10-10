import type { SVGProps } from "react";

/** Векторные символы Taleforge: единый набор SVG-путей, без шрифтов, эмодзи и внешних ассетов. */
export const MAP_GLYPHS = {
  "hero": [
    "M12 2 19 5v6c0 5-3.5 8.5-7 11-3.5-2.5-7-6-7-11V5l7-3Z",
    "M9 12l2 2 4-4"
  ],
  "enemy": [
    "M4 4l16 16",
    "M20 4 4 20",
    "M5 2l3 3-3 3-3-3 3-3Z",
    "M19 16l3 3-3 3-3-3 3-3Z"
  ],
  "person": [
    "M12 12a4 4 0 1 0 0-8 4 4 0 0 0 0 8Z",
    "M4 21v-2a8 8 0 0 1 16 0v2"
  ],
  "gem": [
    "M6 3h12l5 7-11 12L1 10 6 3Z",
    "M1 10h22",
    "M6 3l6 19 6-19"
  ],
  "pin": [
    "M20 10c0 5-8 12-8 12S4 15 4 10a8 8 0 1 1 16 0Z",
    "M12 10a2.5 2.5 0 1 0 0-5 2.5 2.5 0 0 0 0 5Z"
  ],
  "landmark": [
    "M3 21h18",
    "M5 21V9l7-6 7 6v12",
    "M9 21v-7h6v7"
  ],
  "scroll": [
    "M7 4h11a3 3 0 0 1 3 3v12a3 3 0 0 1-3 3H6a3 3 0 0 1-3-3 3 3 0 0 1 3-3h12",
    "M7 4a3 3 0 0 0 0 6h8",
    "M8 13h7"
  ],
  "chest": [
    "M3 10h18v11H3z",
    "M3 10V7a9 9 0 0 1 18 0v3",
    "M12 10v11",
    "M10 13h4v4h-4z"
  ],
  "flask": [
    "M9 2h6",
    "M10 2v7l-6 10a2 2 0 0 0 2 3h12a2 2 0 0 0 2-3l-6-10V2",
    "M7 16h10"
  ],
  "sword": [
    "M3 21l6-6",
    "M5 19l-2-2",
    "M9 15l10-12 2-1-1 3-11 12",
    "M7 17l-2-2"
  ],
  "key": [
    "M8 14a6 6 0 1 0-6-6 6 6 0 0 0 6 6Z",
    "M12 12l10 10",
    "M17 17l3-3",
    "M19 19l3-3"
  ],
  "book": [
    "M3 5h7a4 4 0 0 1 4 4v12a4 4 0 0 0-4-4H3z",
    "M21 5h-7a4 4 0 0 0-4 4v12a4 4 0 0 1 4-4h7z"
  ],
  "torch": [
    "M9 14h6l-2 8h-2l-2-8Z",
    "M12 14C5 10 8 5 11 2c-1 4 5 4 4 9 0 2-1 3-3 3Z"
  ],
  "tree": [
    "M12 3l-7 9h4l-5 6h16l-5-6h4l-7-9Z",
    "M12 18v4"
  ],
  "table": [
    "M3 9h18v4H3z",
    "M6 13v8",
    "M18 13v8"
  ],
  "shield": [
    "M12 2 21 6v6c0 6-4 9-9 11-5-2-9-5-9-11V6l9-4Z"
  ],
  "alert": [
    "M12 3 22 21H2L12 3Z",
    "M12 9v5",
    "M12 18v1"
  ],
  "door": [
    "M5 22V3h14v19",
    "M9 22V7h7v15",
    "M13 15h1"
  ],
  "window": [
    "M3 3h18v18H3z",
    "M12 3v18",
    "M3 12h18"
  ],
  "arch": [
    "M3 22V12a9 9 0 0 1 18 0v10",
    "M8 22V12a4 4 0 0 1 8 0v10"
  ],
  "bars": [
    "M3 3v18",
    "M9 3v18",
    "M15 3v18",
    "M21 3v18",
    "M1 8h22",
    "M1 18h22"
  ],
  "stairs": [
    "M2 21h6v-5h5v-5h5V6h4"
  ],
  "hatch": [
    "M3 3h18v18H3z",
    "M7 7h10v10H7z",
    "M12 10v4"
  ],
  "gap": [
    "M2 5h7l-3 5 5 4-3 6",
    "M22 5h-7l3 5-5 4 3 6"
  ],
  "passage": [
    "M3 12h17",
    "M14 6l6 6-6 6"
  ],
  "coin": [
    "M12 3a9 9 0 1 0 0 18 9 9 0 0 0 0-18Z",
    "M15 8h-4a2 2 0 0 0 0 4h2a2 2 0 0 1 0 4H9",
    "M12 6v12"
  ],
  "box": [
    "M3 7l9-4 9 4v10l-9 4-9-4V7Z",
    "M3 7l9 4 9-4",
    "M12 11v10"
  ],
  "nature": [
    "M12 2v20",
    "M12 12c-7-1-9-6-9-9 5 0 9 3 9 9Z",
    "M12 17c7-1 9-6 9-9-5 0-9 3-9 9Z"
  ]
} as const;

export type MapGlyphName = keyof typeof MAP_GLYPHS;

export function MapGlyph({
  name,
  ...props
}: SVGProps<SVGSVGElement> & { name: MapGlyphName }) {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={1.8}
      strokeLinecap="round" strokeLinejoin="round" aria-hidden="true" focusable="false" {...props}>
      {MAP_GLYPHS[name].map((d, i) => <path key={i} d={d} />)}
    </svg>
  );
}
