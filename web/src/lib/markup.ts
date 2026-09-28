// Разметка сущностей в тексте мастера: [[id|текст]]. Здесь — только разбор на куски; как показать сущность
// и что открыть по клику, решает экран (этап 7, PR 2 — карточки знаний).

export type Piece = { text: string } | { id: string; text: string };

const ENTITY = /\[\[([^|\]]+)\|([^\]]+)\]\]/g;

export function parseMarkup(s: string): Piece[] {
  const out: Piece[] = [];
  let at = 0;
  for (const m of s.matchAll(ENTITY)) {
    if (m.index! > at) out.push({ text: s.slice(at, m.index) });
    out.push({ id: m[1], text: m[2] });
    at = m.index! + m[0].length;
  }
  if (at < s.length) out.push({ text: s.slice(at) });
  return out;
}

export function plain(s: string): string {
  return parseMarkup(s)
    .map((p) => p.text)
    .join("");
}
