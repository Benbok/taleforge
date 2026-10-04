// Готовые приключения в админке: типы ответа сервера (app/api/modules.py) и чистые помощники экрана.
import { getToken } from "./api";

export type ModuleStatus =
  | "reading"
  | "translating"
  | "mapping"
  | "review"
  | "published"
  | "failed";

export interface MapMark {
  number: string;
  x: number;
  y: number;
}

export interface ModuleMap {
  id: string;
  name: string;
  location_id: string | null;
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
    rooms: { id: string; number?: string; name: string }[];
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
  return [
    ...marks.filter((m) => m.number !== number),
    { number, x: clamp(x), y: clamp(y) },
  ];
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
