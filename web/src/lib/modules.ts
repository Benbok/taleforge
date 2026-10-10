// Готовые приключения в админке: типы ответа сервера (app/api/modules.py) и чистые помощники экрана.
import { getToken } from "./api";

export type ModuleStatus =
  | "reading"
  | "translating"
  | "mapping"
  | "review"
  | "published"
  | "failed";

export interface MapPassage {
  to: string;
  side: "n" | "e" | "s" | "w";
  cell: [number, number];
  kind?: "passage" | "door" | "arch" | "stairs" | "hatch" | "gap" | "bars";
}

export interface MapMark {
  number: string;
  x: number;
  y: number;
  cells?: number[][]; // пол комнаты прямоугольниками [столбец1, строка1, столбец2, строка2]
  blocked?: number[][]; // клетки, где стоять нельзя: стены, колонны
  passages?: MapPassage[]; // достоверно размеченные проёмы в соседние комнаты
}

export interface MapGrid {
  cols: number;
  rows: number;
  left: number;
  top: number;
  right: number;
  bottom: number;
}

export interface ModuleMap {
  id: string;
  name: string;
  location_id: string | null;
  grid?: MapGrid | null;
  marks: MapMark[];
  missing?: string[];
  status: "pending" | "reading" | "ok" | "failed";
  error?: string | null;
}

export interface ModuleShort {
  id: string;
  title: string;
  status: ModuleStatus;
  error: string | null;
  source_name: string;
  pages: number;
  maps: number;
  counts: Partial<
    Record<
      "locations" | "rooms" | "creatures" | "items" | "hooks" | "acts",
      number
    >
  >;
  pack_id: string | null;
  pack_version: string | null;
  published_at: string | null;
  created_at: string;
  updated_at: string;
}

export interface ModuleDraft {
  summary: string;
  levels: { start: number; end: number } | null;
  party_size: number | null;
  locations: {
    id: string;
    name: string;
    rooms: { id: string; number?: string; name: string; exits?: string[] }[];
  }[];
  creatures: {
    id: string;
    name: string;
    base_ref: string;
    book_note?: string;
  }[];
  items: { id: string; name: string; category: string; book_note?: string }[];
  hooks: { id: string; title: string }[];
  notes: string[];
}

export interface ModuleFull extends ModuleShort {
  note: string;
  warnings: string[];
  draft: ModuleDraft | null;
  room_numbers: Record<string, string[]>;
  map_list: ModuleMap[];
}

export const STATUS_LABEL: Record<ModuleStatus, string> = {
  reading: "Читаю PDF",
  translating: "ИИ разбирает книгу",
  mapping: "Ищу номера на картах",
  review: "Ждёт проверки",
  published: "Опубликовано",
  failed: "Ошибка",
};

export function isBusy(status: ModuleStatus): boolean {
  return (
    status === "reading" || status === "translating" || status === "mapping"
  );
}

/** Карта ещё в работе у модели: экран спрашивает сервер, пока она не закончит. */
export function anyBusy(m: Pick<ModuleFull, "status" | "map_list">): boolean {
  return isBusy(m.status) || m.map_list.some((x) => x.status === "reading");
}

/** Поставить номер в точку клика: старая отметка этого номера заменяется. Координаты — доли от 0 до 1. */
export function placeMark(
  marks: MapMark[],
  number: string,
  x: number,
  y: number,
): MapMark[] {
  const clamp = (v: number) =>
    Math.round(Math.min(1, Math.max(0, v)) * 10000) / 10000;
  const old = marks.find((m) => m.number === number);
  return [
    ...marks.filter((m) => m.number !== number),
    { ...old, number, x: clamp(x), y: clamp(y) },
  ];
}

/** Клетка сетки под точкой картинки (доли); null — вне сетки. */
export function cellAt(
  grid: MapGrid,
  x: number,
  y: number,
): [number, number] | null {
  const col = Math.floor(
    ((x - grid.left) / (grid.right - grid.left)) * grid.cols,
  );
  const row = Math.floor(
    ((y - grid.top) / (grid.bottom - grid.top)) * grid.rows,
  );
  if (col < 0 || row < 0 || col >= grid.cols || row >= grid.rows) return null;
  return [col, row];
}

/** Клетка в комнате: в одном из её прямоугольников. */
export function inRoom(mark: MapMark, [c, r]: [number, number]): boolean {
  return (mark.cells ?? []).some(
    ([c0, r0, c1, r1]) => c0 <= c && c <= c1 && r0 <= r && r <= r1,
  );
}

/** Добавить к полу комнаты прямоугольник между двумя клетками (порядок углов любой). */
export function addRect(
  mark: MapMark,
  a: [number, number],
  b: [number, number],
): MapMark {
  const rect = [
    Math.min(a[0], b[0]),
    Math.min(a[1], b[1]),
    Math.max(a[0], b[0]),
    Math.max(a[1], b[1]),
  ];
  return {
    ...mark,
    cells: [...(mark.cells ?? []), rect],
    blocked: mark.blocked ?? [],
  };
}

/** Щелчок по клетке комнаты: занята ⇄ свободна. Вне комнаты — без изменений. */
export function toggleBlocked(mark: MapMark, cell: [number, number]): MapMark {
  if (!inRoom(mark, cell)) return mark;
  const blocked = mark.blocked ?? [];
  const has = blocked.some(([c, r]) => c === cell[0] && r === cell[1]);
  return {
    ...mark,
    blocked: has
      ? blocked.filter(([c, r]) => c !== cell[0] || r !== cell[1])
      : [...blocked, cell],
  };
}

/** Номера места, которых на карте ещё нет: их админ ставит щелчком. */
export function unplaced(numbers: string[], marks: MapMark[]): string[] {
  const placed = new Set(marks.map((m) => m.number));
  return numbers.filter((n) => !placed.has(n));
}

/** Файл телом запроса, как архив пакета: книга PDF или картинка карты. */
export async function uploadRaw<T>(path: string, file: File): Promise<T> {
  const res = await fetch(path, {
    method: "POST",
    headers: {
      "Content-Type": file.type || "application/octet-stream",
      Authorization: `Bearer ${getToken() ?? ""}`,
    },
    body: file,
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok)
    throw new Error(
      typeof data.detail === "string"
        ? data.detail
        : `ошибка сервера (${res.status})`,
    );
  return data as T;
}
