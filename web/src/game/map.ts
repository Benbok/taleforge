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
  /** Клетка от строя отряда, если мастер поставил точно (в бою — всегда). */
  cell?: [number, number] | null;
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
  cell?: [number, number] | null;
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

/** Карта места готового приключения: картинка из книги, комнаты отряда и герои на клетках (доли картинки). */
export interface MapBook {
  module_id: string;
  map_id: string;
  name: string;
  grid: { cols: number; rows: number; left: number; top: number; right: number; bottom: number } | null;
  here: string | null;
  rooms: { number: string; x: number; y: number; status: "here" | "visited" | "known"; name: string | null; cells?: number[][] }[];
  tokens: { id: string; name: string; mine: boolean; room: string; x: number; y: number; down: boolean }[];
}

/** Эскиз места, нарисованный мастером (app/core/sketch.py): клетки по 5 футов, (0, 0) — северо-западный угол. */
export interface SketchExit {
  name: string;
  side: "n" | "e" | "s" | "w";
  at: number;
  kind: "door" | "bars" | "window" | "arch" | "stairs" | "hatch" | "gap" | "passage";
  state?: "open" | "closed" | "locked";
  to?: string | null;
  beyond?: string | null;
  hidden?: boolean;
}

export interface SketchFeature {
  name: string;
  kind: "furniture" | "cover" | "hazard" | "light" | "object" | "nature";
  cells: number[][];
  cover?: Cover;
  hidden?: boolean;
}

export interface Sketch {
  shape: "room" | "corridor" | "cave" | "street" | "open";
  cols: number;
  rows: number;
  party: [number, number];
  walls: number[][];
  exits: SketchExit[];
  features: SketchFeature[];
}

export interface MapState {
  book?: MapBook | null;
  sketch?: Sketch | null;
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

type Tab = "around" | "places" | "book";

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
  else if (w.open && (type === "scene.updated" || type === "state.snapshot" || type === "knowledge.revealed" || type === "map.changed")) w.request();
}

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

// --- раскладка «Вокруг» на клетках ---

/** Клетка — 5 футов. Вплотную — соседняя клетка, близко — 30 футов (6 клеток). «Далеко» (120 футов по правилам)
 *  рисуется на 12 клетках, у края схемы: иначе схема станет в 49 клеток и значки не разглядеть. */
export const CELL_FT = 5;
export const ZONE_CELLS: Record<Zone, number> = { melee: 1, near: 6, far: 12 };
export const GRID_R = 13; // схема — квадрат (2·13+1) клеток, центр отряда в клетке (0, 0)

export interface Cell<T> {
  item: T;
  col: number; // от −GRID_R до GRID_R, восток вправо
  row: number; // от −GRID_R до GRID_R, юг вниз
}

export interface GridLayout {
  areas: Cell<MapArea>[];
  things: Cell<MapThing>[];
  heroes: Cell<MapHero>[];
  exits: Cell<MapExit>[];
}

type Allowed = (col: number, row: number) => boolean;

/** Ближайшая к точке свободная клетка: сначала сама, потом по кольцам вокруг неё в устойчивом порядке.
 *  ``allowed`` — где вообще можно стоять (пол эскиза без стен и предметов). */
export function freeCell(col: number, row: number, taken: Set<string>, limit = GRID_R, allowed?: Allowed): [number, number] {
  const ok = (c: number, r: number) =>
    Math.abs(c) <= limit && Math.abs(r) <= limit && !taken.has(`${c},${r}`) && (!allowed || allowed(c, r));
  for (let d = 0; d <= 2 * limit; d++) {
    const ring: [number, number][] = [];
    for (let dc = -d; dc <= d; dc++)
      for (let dr = -d; dr <= d; dr++) if (Math.max(Math.abs(dc), Math.abs(dr)) === d) ring.push([col + dc, row + dr]);
    // ближе по прямой — раньше; при равенстве — по строке, затем по столбцу, чтобы раскладка не прыгала
    ring.sort((a, b) => Math.hypot(a[0] - col, a[1] - row) - Math.hypot(b[0] - col, b[1] - row) || a[1] - b[1] || a[0] - b[0]);
    const hit = ring.find(([c, r]) => ok(c, r));
    if (hit) return hit;
  }
  return [col, row];
}

function target(id: string, bearing: Bearing | null, cells: number): [number, number] {
  const a = baseAngle(id, bearing);
  return [Math.round(cells * Math.sin(a)) || 0, Math.round(-cells * Math.cos(a)) || 0]; // без −0
}

/** Раскладка «Вокруг» по клеткам: каждый в клетке по своей зоне и стороне, двое в одной точке — в соседних.
 *  С эскизом места значки встают только на его пол, а выходы, нарисованные в эскизе, не дублируются. */
export function layoutGrid(m: MapState): GridLayout {
  const frame = m.sketch ? sketchFrame(m.sketch) : null;
  const allowed = frame?.allowed;
  const reach = frame ? frame.reach : GRID_R;
  const drawn = new Set((m.sketch?.exits ?? []).map((x) => x.to).filter(Boolean) as string[]);
  const taken = new Set<string>();
  const put = <T>(item: T, at: [number, number], limit = reach): Cell<T> => {
    if (frame) {
      // «далеко» за стеной маленькой комнаты — у её края в ту же сторону
      at = [Math.max(frame.minCol, Math.min(frame.maxCol, at[0])), Math.max(frame.minRow, Math.min(frame.maxRow, at[1]))];
    }
    const [col, row] = freeCell(at[0], at[1], taken, limit, allowed);
    taken.add(`${col},${row}`);
    return { item, col, row };
  };
  // стоящие на клетке (бой на сетке) — ровно там, их клетки заняты раньше всех; без эскиза — в пределах схемы
  const exact = <T>(item: T, [c, r]: [number, number]): Cell<T> => {
    const col = frame ? c : Math.max(-GRID_R, Math.min(GRID_R, c));
    const row = frame ? r : Math.max(-GRID_R, Math.min(GRID_R, r));
    taken.add(`${col},${row}`);
    return { item, col, row };
  };
  const party = m.party ?? [];
  const placed = new Map<string, Cell<MapHero> | Cell<MapThing>>();
  for (const h of party) if (h.cell) placed.set(h.id, exact(h, h.cell));
  for (const t of m.around) if (t.cell) placed.set(t.id, exact(t, t.cell));
  // потом герои в строю — вокруг центра, потом все остальные по зонам; выходы — по краю схемы
  const heroes = [
    ...party.filter((h) => !h.cell && !h.zone).map((h) => put(h, [0, 0])),
    ...party.filter((h) => !h.cell && h.zone).map((h) => put(h, target(h.id, h.bearing, ZONE_CELLS[h.zone as Zone]))),
    ...party.filter((h) => h.cell).map((h) => placed.get(h.id) as Cell<MapHero>),
  ];
  const things = m.around.map(
    (t) =>
      (placed.get(t.id) as Cell<MapThing> | undefined) ??
      put(t, target(t.id, t.bearing, ZONE_CELLS[t.zone] ?? ZONE_CELLS.near)),
  );
  const exits = m.exits
    .filter((x) => !drawn.has(x.id))
    .map((x) => {
      const [c, r] = target(x.id, x.bearing, reach);
      return put(x, [Math.max(-reach, Math.min(reach, c)), Math.max(-reach, Math.min(reach, r))]);
    });
  // область не занимает клетку: она лежит под значками
  const areas = (m.areas ?? []).map((a) => {
    const [col, row] = target(a.id, a.bearing, ZONE_CELLS[a.zone] ?? ZONE_CELLS.near);
    return { item: a, col, row };
  });
  return { heroes, things, exits, areas };
}

/** Эскиз в координатах схемы: отряд в клетке (0, 0), как в раскладке по зонам. */
export interface SketchFrame {
  /** Сдвиг: клетка эскиза (c, r) рисуется в клетке схемы (c − dc, r − dr). */
  dc: number;
  dr: number;
  minCol: number;
  minRow: number;
  maxCol: number;
  maxRow: number;
  walls: Set<string>;
  /** Клетки предметов эскиза: туда значки не ставятся. */
  solid: Set<string>;
  allowed: (col: number, row: number) => boolean;
  /** Сколько клеток от отряда до дальнего края места: предел поиска свободной клетки. */
  reach: number;
}

export function sketchFrame(sk: Sketch): SketchFrame {
  const [dc, dr] = sk.party;
  const walls = new Set(sk.walls.map(([c, r]) => `${c - dc},${r - dr}`));
  const solid = new Set<string>();
  for (const f of sk.features)
    for (const [c0, r0, c1, r1] of f.cells)
      for (let c = c0; c <= c1; c++) for (let r = r0; r <= r1; r++) solid.add(`${c - dc},${r - dr}`);
  const minCol = -dc;
  const minRow = -dr;
  const maxCol = sk.cols - 1 - dc;
  const maxRow = sk.rows - 1 - dr;
  const allowed = (c: number, r: number) =>
    c >= minCol && c <= maxCol && r >= minRow && r <= maxRow && !walls.has(`${c},${r}`) && !solid.has(`${c},${r}`);
  const reach = Math.max(-minCol, maxCol, -minRow, maxRow, 1);
  return { dc, dr, minCol, minRow, maxCol, maxRow, walls, solid, allowed, reach };
}

/** Клетка снаружи края, где рисуется выход эскиза, в координатах схемы. */
export function exitCell(sk: Sketch, x: SketchExit): [number, number] {
  const [dc, dr] = sk.party;
  if (x.side === "n") return [x.at - dc, -1 - dr];
  if (x.side === "s") return [x.at - dc, sk.rows - dr];
  if (x.side === "w") return [-1 - dc, x.at - dr];
  return [sk.cols - dc, x.at - dr];
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
