// Карта: схема места («Вокруг») и граф открытых мест («Места»). Сервер собирает её из реестра мира
// (app/core/map.py): запрос сокетом map.get, ответ событием map.state. Пока окно открыто, карта обновляется
// после каждого хода мастера (scene.updated).
import { create } from "zustand";
import type { EntityType } from "../lib/types";
import { useGame } from "../stores/game";

export type Zone = "melee" | "near" | "far";
export type Bearing = "n" | "ne" | "e" | "se" | "s" | "sw" | "w" | "nw";

export type Elevation = "low" | "ground" | "high";
export type Cover = "none" | "half" | "three_quarters" | "total";

export interface MapThing {
  id: string;
  name: string;
  type: EntityType;
  zone: Zone;
  zone_name: string;
  bearing: Bearing | null;
  elevation?: Elevation;
  cover?: Cover;
  condition?: string | null;
}

/** Герой в этом месте. zone = null — в строю отряда, в центре схемы. */
export interface MapHero {
  id: string;
  name: string;
  mine: boolean;
  zone: Zone | null;
  bearing: Bearing | null;
  elevation: Elevation;
  cover: Cover;
  down: boolean;
}

/** Область на площадь: облако, огонь, туман. */
export interface MapArea {
  id: string;
  name: string;
  zone: Zone;
  bearing: Bearing | null;
  radius_ft: number;
}

export const ELEVATION_NAME: Record<Elevation, string> = { low: "внизу", ground: "на земле", high: "на возвышении" };
export const COVER_NAME: Record<Cover, string> = {
  none: "без укрытия",
  half: "половинное укрытие",
  three_quarters: "укрытие на три четверти",
  total: "полное укрытие",
};

export interface MapExit {
  id: string;
  name: string;
  via: string | null;
  bearing: Bearing | null;
  visited: boolean;
}

export interface MapPlace {
  id: string;
  name: string;
  parent_id: string | null;
  status: "here" | "visited" | "known";
}

export interface MapState {
  here: { id: string; name: string; description: string | null } | null;
  around: MapThing[];
  party?: MapHero[];
  areas?: MapArea[];
  mode?: "free" | "combat";
  exits: MapExit[];
  places: MapPlace[];
  links: { a: string; b: string; label: string | null }[];
  bearings: Record<Bearing, string>;
}

type Tab = "around" | "places";

interface MapWindowState {
  open: boolean;
  tab: Tab;
  data: MapState | null;
  loading: boolean;
  error: string | null;
  show(tab?: Tab): void;
  hide(): void;
  setTab(tab: Tab): void;
  request(): void;
  receive(data: MapState): void;
}

export const useMapWindow = create<MapWindowState>((set, get) => ({
  open: false,
  tab: "around",
  data: null,
  loading: false,
  error: null,
  show(tab) {
    set((s) => ({ open: true, tab: tab ?? s.tab }));
    get().request();
  },
  hide() {
    set({ open: false });
  },
  setTab(tab) {
    set({ tab });
  },
  request() {
    const sent = useGame.getState().socket?.send("map.get") ?? false;
    set(sent ? { loading: true, error: null } : { loading: false, error: "нет связи с сервером: карта обновится, когда соединение вернётся" });
  },
  receive(data) {
    set({ data, loading: false, error: null });
  },
}));

/** Событие сокета для карты: ответ сервера или повод перезапросить открытую карту. */
export function mapEvent(type: string, payload: unknown): void {
  const w = useMapWindow.getState();
  if (type === "map.state") w.receive(payload as MapState);
  else if (w.open && (type === "scene.updated" || type === "state.snapshot" || type === "knowledge.revealed")) w.request();
}

// --- раскладка «Вокруг» ---

export const RING: Record<Zone, number> = { melee: 55, near: 105, far: 155 };
export const EDGE = 188;
const BEARINGS: Bearing[] = ["n", "ne", "e", "se", "s", "sw", "w", "nw"];

/** Устойчивый угол для того, у кого мастер не указал сторону: по id, чтобы маркер не прыгал между ходами. */
function hashAngle(id: string): number {
  let h = 0;
  for (const ch of id) h = (h * 31 + ch.charCodeAt(0)) >>> 0;
  return (h % 360) * (Math.PI / 180);
}

function baseAngle(id: string, bearing: Bearing | null): number {
  const i = bearing ? BEARINGS.indexOf(bearing) : -1;
  return i >= 0 ? (i * Math.PI) / 4 : hashAngle(id);
}

export interface Placed<T> {
  item: T;
  x: number;
  y: number;
}

/** Точки на кольцах: север вверху, по часовой стрелке. Соседи в одной стороне и зоне расходятся веером. */
export function placeAround<T extends { id: string; bearing: Bearing | null }>(
  items: T[],
  radius: (item: T) => number,
  cx = 200,
  cy = 200,
): Placed<T>[] {
  const taken = new Map<string, number>();
  return items.map((item) => {
    const r = radius(item);
    const a0 = baseAngle(item.id, item.bearing);
    const key = `${r}:${Math.round((a0 * 8) / (2 * Math.PI))}`;
    const n = taken.get(key) ?? 0;
    taken.set(key, n + 1);
    // 0, +1, −1, +2, −2… шагом, который на этом кольце даёт ~60px между центрами: подписи не налезают
    const step = 60 / r;
    const a = a0 + (n === 0 ? 0 : (n % 2 === 1 ? 1 : -1) * Math.ceil(n / 2) * step);
    return { item, x: cx + r * Math.sin(a), y: cy - r * Math.cos(a) };
  });
}

/** Радиус области на схеме: кольца не в масштабе, поэтому берём масштаб кольца «близко» и ограничиваем. */
export function areaPx(ft: number): number {
  return Math.min(90, Math.max(14, ft * 3.5));
}

/** Герои в строю отряда стоят кучкой вокруг центра, чтобы подписи не слипались. */
export function placeParty(heroes: MapHero[], cx = 200, cy = 200): Placed<MapHero>[] {
  const inRank = heroes.filter((h) => !h.zone);
  const out: Placed<MapHero>[] = inRank.map((item, i) => {
    if (inRank.length === 1) return { item, x: cx, y: cy };
    const a = (i / inRank.length) * 2 * Math.PI;
    return { item, x: cx + 22 * Math.sin(a), y: cy - 22 * Math.cos(a) };
  });
  const out2 = placeAround(
    heroes.filter((h) => h.zone),
    (h) => RING[h.zone as Zone],
    cx,
    cy,
  );
  return [...out, ...out2];
}

// --- раскладка «Места» ---

export interface PlacedPlace {
  place: MapPlace;
  col: number;
  row: number;
}

/** Граф мест столбцами: 0 — где герой, дальше — сколько переходов до места; несвязанные — последним столбцом. */
export function layoutPlaces(m: Pick<MapState, "places" | "links" | "here">): PlacedPlace[] {
  const ids = new Set(m.places.map((p) => p.id));
  const adj = new Map<string, Set<string>>();
  const add = (a: string, b: string) => {
    if (!ids.has(a) || !ids.has(b)) return;
    if (!adj.has(a)) adj.set(a, new Set());
    if (!adj.has(b)) adj.set(b, new Set());
    adj.get(a)!.add(b);
    adj.get(b)!.add(a);
  };
  for (const l of m.links) add(l.a, l.b);
  for (const p of m.places) if (p.parent_id) add(p.id, p.parent_id);

  const depth = new Map<string, number>();
  const start = m.here && ids.has(m.here.id) ? m.here.id : m.places[0]?.id;
  if (start) {
    depth.set(start, 0);
    const queue = [start];
    while (queue.length) {
      const cur = queue.shift()!;
      for (const nb of adj.get(cur) ?? []) {
        if (!depth.has(nb)) {
          depth.set(nb, depth.get(cur)! + 1);
          queue.push(nb);
        }
      }
    }
  }
  const far = Math.max(-1, ...depth.values()) + 1;
  const rows = new Map<number, number>();
  return m.places.map((place) => {
    const col = depth.get(place.id) ?? far;
    const row = rows.get(col) ?? 0;
    rows.set(col, row + 1);
    return { place, col, row };
  });
}
