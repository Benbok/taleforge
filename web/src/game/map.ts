// Карта: схема места («Вокруг») и граф открытых мест («Места»). Сервер собирает её из реестра мира
// (app/core/map.py): запрос сокетом map.get, ответ событием map.state. Пока окно открыто, карта обновляется
// после каждого хода мастера (scene.updated).
import { create } from "zustand";
import type { EntityType, Envelope } from "../lib/types";
import type { MapState as GeneratedMapState } from "../lib/api.gen";
import { useGame } from "../stores/game";

export type Zone = "melee" | "near" | "far";
export type Bearing = "n" | "ne" | "e" | "se" | "s" | "sw" | "w" | "nw";

export type Elevation = "low" | "ground" | "high";
export type Cover = "none" | "half" | "three_quarters" | "total";

export interface MapThing {
  id: string;
  name: string;
  type: EntityType;
  visual_key?: string | null; // ключ рисунка из Entity.state, только из проверенного каталога пресетов
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
  id: string | null;
  room_ref?: string | null;
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

/** Где стоит отряд словами: само место и то, внутри чего оно («Зал Мёртвых · Склеп Давоса»). */
export function whereTrail(m: Pick<MapState, "here" | "places">): string | null {
  if (!m.here) return null;
  const byId = new Map(m.places.map((p) => [p.id, p]));
  const names = [m.here.name];
  let parent = byId.get(m.here.id)?.parent_id ?? null;
  const seen = new Set([m.here.id]);
  while (parent && !seen.has(parent) && names.length < 3) {
    seen.add(parent);
    const p = byId.get(parent);
    if (!p) break;
    names.push(p.name);
    parent = p.parent_id;
  }
  return names.join(" · ");
}

/** Подпись комнаты на карте книги: номер, а у знакомой комнаты — и название. */
export function roomLabel(r: { number: string; name: string | null }): string {
  return r.name ? `${r.number} · ${r.name}` : r.number;
}

/** Карта места готового приключения: картинка из книги, комнаты отряда и герои на клетках (доли картинки). */
export interface MapBook {
  module_id: string;
  map_id: string;
  name: string;
  grid: { cols: number; rows: number; left: number; top: number; right: number; bottom: number } | null;
  here: string | null;
  rooms: { number: string; x: number; y: number; status: "here" | "visited" | "known"; name: string | null; cells?: number[][] }[];
  tokens: { id: string; name: string; mine: boolean; room: string; x: number; y: number; down: boolean; type?: EntityType; cell?: [number, number]; visual_key?: string | null }[];
}

/** Эскиз места, нарисованный мастером (app/core/sketch.py): клетки по 5 футов, (0, 0) — северо-западный угол. */
export interface SketchExit {
  name: string;
  side: "n" | "e" | "s" | "w";
  at: number;
  kind: "door" | "bars" | "window" | "arch" | "stairs" | "hatch" | "gap" | "passage";
  state?: "open" | "closed" | "locked";
  to?: string | null;
  room_ref?: string | null;
  beyond?: string | null;
  hidden?: boolean;
}

export interface SketchFeature {
  id?: string | null;
  entity_id?: string | null;
  entity_type?: EntityType | null;
  visual_key?: string | null;
  name: string;
  kind: "furniture" | "cover" | "hazard" | "light" | "object" | "nature";
  cells: number[][];
  cover?: Cover;
  hidden?: boolean;
}

export interface Sketch {
  edit_rev?: number | null;
  shape: "room" | "corridor" | "cave" | "street" | "open";
  cols: number;
  rows: number;
  party: [number, number];
  walls: number[][];
  exits: SketchExit[];
  features: SketchFeature[];
  book?: boolean; // эскиз построен непосредственно из размеченной сетки книги
  unplaced_exits?: { name: string; to?: string | null; room_ref?: string | null }[]; // выход есть в книге, но клетка двери неизвестна
}

export type SceneTokenType = "hero" | "creature" | "npc" | "item" | "landmark";

export interface SceneTokenView {
  id: string;
  name: string;
  type: SceneTokenType;
  visual_key?: string | null;
  mine: boolean;
  down: boolean;
  zone: Zone | null;
  bearing: Bearing | null;
  cell?: [number, number] | null;
}

/** Представление карты для UI. Основные поля наследуют серверный контракт;
 * визуальные перечисления нормализуются только на границе сокета. */
export interface MapState extends Pick<GeneratedMapState, "here" | "places" | "links" | "bearings"> {
  scene_view?: SceneTokenView[];
  book?: MapBook | null;
  sketch?: Sketch | null;
  around: MapThing[];
  party?: MapHero[];
  areas?: MapArea[];
  mode?: "free" | "combat";
  exits: MapExit[];
}

const ZONES: Zone[] = ["melee", "near", "far"];
const ELEVATIONS: Elevation[] = ["low", "ground", "high"];
const COVERS: Cover[] = ["none", "half", "three_quarters", "total"];
const SHAPES: Sketch["shape"][] = ["room", "corridor", "cave", "street", "open"];
const EXIT_KINDS: SketchExit["kind"][] = ["door", "bars", "window", "arch", "stairs", "hatch", "gap", "passage"];
const FEATURE_KINDS: SketchFeature["kind"][] = ["furniture", "cover", "hazard", "light", "object", "nature"];
const EXIT_STATES: NonNullable<SketchExit["state"]>[] = ["open", "closed", "locked"];

function listed<T extends string>(value: string | null | undefined, values: readonly T[], fallback: T): T {
  return values.find((v) => v === value) ?? fallback;
}

function safeBearing(value: string | null | undefined): Bearing | null {
  return BEARINGS.find((b) => b === value) ?? null;
}

/** Проводной MapState строго типизирован в api.gen.ts, здесь лишь приводим
 * расширяемые серверные строки к ограниченным словарям рисования. */
export function mapForDisplay(data: GeneratedMapState): MapState {
  const sketch: Sketch | null = data.sketch ? {
    ...data.sketch,
    shape: listed(data.sketch.shape, SHAPES, "room"),
    exits: data.sketch.exits.map((e) => ({
      ...e,
      kind: listed(e.kind, EXIT_KINDS, "passage"),
      state: e.state ? listed(e.state, EXIT_STATES, "open") : undefined,
    })),
    features: data.sketch.features.map((feature) => ({
      ...feature,
      entity_type: feature.entity_type === "item" || feature.entity_type === "landmark"
        ? feature.entity_type
        : undefined,
      kind: listed(feature.kind, FEATURE_KINDS, "object"),
      cover: feature.cover ? listed(feature.cover, COVERS, "none") : undefined,
    })),
  } : null;
  return {
    here: data.here,
    places: data.places,
    links: data.links,
    bearings: data.bearings,
    book: data.book ? {
      ...data.book,
      tokens: data.book.tokens.map((token) => ({ ...token, type: token.type === "hero" ? undefined : token.type })),
    } : null,
    sketch,
    mode: data.mode,
    party: data.party.map((h) => ({
      ...h,
      zone: h.zone == null ? null : listed(h.zone, ZONES, "near"),
      bearing: safeBearing(h.bearing),
      elevation: listed(h.elevation, ELEVATIONS, "ground"),
      cover: listed(h.cover, COVERS, "none"),
    })),
    around: data.around.map((t) => ({
      ...t,
      zone: listed(t.zone, ZONES, "near"),
      zone_name: t.zone_name ?? "",
      bearing: safeBearing(t.bearing),
      elevation: listed(t.elevation, ELEVATIONS, "ground"),
      cover: listed(t.cover, COVERS, "none"),
    })),
    areas: data.areas.map((a) => ({ ...a, zone: listed(a.zone, ZONES, "near"), bearing: safeBearing(a.bearing) })),
    exits: data.exits.map((e) => ({ ...e, bearing: safeBearing(e.bearing) })),
    scene_view: data.scene_view.map((t) => ({
      ...t,
      zone: t.zone == null ? null : listed(t.zone, ZONES, "near"),
      bearing: safeBearing(t.bearing),
    })),
  };
}

type Tab = "around" | "places" | "book";

/** Куда идёт герой: на клетку или к ближайшей свободной клетке рядом с целью (клетки от строя отряда). */
export interface StepRequest {
  cell?: [number, number];
  near?: [number, number][];
}

/** Ответ сервера на шаг (map.step.result). */
export interface StepResult {
  request_id?: string | null;
  ok: boolean;
  error?: string;
  who?: string;
  moved_ft?: number;
  left_ft?: number;
  dash?: boolean;
  notes?: string[];
  confirm_needed?: boolean;
  warnings?: string[];
}

export interface StepState {
  busy: boolean;
  note: string | null;
  error: string | null;
  warnings: string[] | null;
  pending: StepRequest | null; // ждёт подтверждения игрока
}

const NO_STEP: StepState = { busy: false, note: null, error: null, warnings: null, pending: null };

/** Строка о шаге для игрока: сколько прошёл, сколько осталось в бою, что случилось по дороге. */
export function stepNote(r: StepResult): string {
  if (!r.moved_ft) return `${r.who ?? "Герой"} уже здесь`;
  const parts = [`${r.who ?? "Герой"} прошёл ${r.moved_ft} фт`];
  if (r.dash) parts.push("рывок: действие потрачено");
  if (r.left_ft != null) parts.push(`осталось ${r.left_ft} фт`);
  return [parts.join(", "), ...(r.notes ?? [])].join(". ");
}

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
  step: StepState;
  stepTo(req: StepRequest, confirm?: boolean): void;
  stepResult(r: StepResult): void;
  cancelStep(): void;
}

let stepSeq = 0;

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
  step: NO_STEP,
  stepTo(req, confirm = false) {
    const sent = useGame.getState().socket?.send("map.step", { ...req, confirm, request_id: `s${++stepSeq}` }) ?? false;
    set({ step: sent ? { ...NO_STEP, busy: true, note: "Иду…", pending: req } : { ...NO_STEP, error: "нет связи с сервером: шаг не отправлен" } });
  },
  stepResult(r) {
    if (!r.ok) set({ step: { ...NO_STEP, error: r.error ?? "шаг не удался" } });
    else if (r.confirm_needed) set({ step: { ...NO_STEP, warnings: r.warnings ?? [], pending: get().step.pending } });
    else {
      set({ step: { ...NO_STEP, note: stepNote(r) } });
      get().request();
    }
  },
  cancelStep() {
    set({ step: NO_STEP });
  },
}));

/** Событие сокета для карты: ответ сервера или повод перезапросить открытую карту. */
export function mapEvent(e: Envelope): void {
  const w = useMapWindow.getState();
  if (e.type === "map.state") w.receive(mapForDisplay(e.payload));
  else if (e.type === "map.step.result") w.stepResult(e.payload);
  else if (w.open && (e.type === "scene.updated" || e.type === "state.snapshot" || e.type === "knowledge.revealed" || e.type === "map.changed")) w.request();
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

/** Механическая клетка записана движком; книжная — известна по модулю.
 * Схематическая вычислена для рисунка и не является целью перемещения. */
export type CellPlacement = "mechanical" | "book" | "schematic";

export interface Cell<T> {
  item: T;
  col: number; // восток вправо, точная клетка может оказаться за краем экрана
  row: number; // юг вниз
  placement: CellPlacement;
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

/** Абсолютные клетки из книги -> координаты «Вокруг» относительно строя.
 *  Используем только автоматически выведенный из книги эскиз: ручной эскиз
 *  мастера может иметь другую систему отсчёта.
 */
export function bookAroundCells(m: MapState): Map<string, [number, number]> {
  const sk = m.sketch;
  const book = m.book;
  if (!sk?.book || !book?.grid || !book.here) return new Map();
  const room = book.rooms.find((r) => r.number === book.here);
  if (!room?.cells?.length) return new Map();
  const c0 = Math.min(...room.cells.map((r) => r[0]));
  const r0 = Math.min(...room.cells.map((r) => r[1]));
  const projected = new Map<string, [number, number]>();
  for (const token of book.tokens) {
    if (token.room !== book.here || !token.cell) continue;
    projected.set(token.id, [token.cell[0] - c0 - sk.party[0], token.cell[1] - r0 - sk.party[1]]);
  }
  return projected;
}

/** Выход книги, для которого известна связность, но не положение проёма на стене.
 * Не является координатой и не должен попадать в layoutGrid / алгоритм шагов.
 */
export interface UnlocatedBookExit {
  key: string;
  name: string;
  destinationId: string | null;
  visited: boolean | null;
}

/** Показываем неизвестные проходы отдельными навигационными маркерами.
 * Если сервер не раскрыл идентификатор назначения, не выдаём его клиенту и
 * не позволяем открыть карточку. Старые карты без passages поддерживаются.
 */
export function unlocatedBookExits(m: Pick<MapState, "sketch" | "exits">): UnlocatedBookExit[] {
  if (!m.sketch?.book) return [];
  const destinations = new Map(m.exits.map((e) => [e.room_ref ?? e.id, e]));
  const located = new Set(m.sketch.exits.map((e) => e.to).filter(Boolean));
  return (m.sketch.unplaced_exits ?? [])
    .map((exit, index) => ({ exit, index }))
    .filter(({ exit }) => !exit.to || !located.has(exit.to))
    .map(({ exit, index }) => {
      const known = destinations.get(exit.room_ref ?? exit.to ?? null);
      return {
        key: exit.to ?? exit.room_ref ?? `unlocated-${index}`,
        name: known?.name ?? exit.name,
        destinationId: known?.id ?? null,
        visited: known?.visited ?? null,
      };
    });
}

/** Раскладка «Вокруг» по клеткам: каждый в клетке по своей зоне и стороне, двое в одной точке — в соседних.
 *  С эскизом места значки встают только на его пол, а выходы, нарисованные в эскизе, не дублируются. */
export function layoutGrid(m: MapState): GridLayout {
  const frame = m.sketch ? sketchFrame(m.sketch) : null;
  const bookCells = bookAroundCells(m);
  const allowed = frame?.allowed;
  const reach = frame ? frame.reach : GRID_R;
  // Не рисуем приблизительный маркер выхода, если книга не знает его координаты.
  const drawn = new Set(
    [...(m.sketch?.exits ?? []), ...(m.sketch?.unplaced_exits ?? [])]
      .map((x) => x.to)
      .filter(Boolean) as string[],
  );
  const taken = new Set<string>();
  const put = <T>(item: T, at: [number, number], limit = reach): Cell<T> => {
    if (frame) {
      // «далеко» за стеной маленькой комнаты — у её края в ту же сторону
      at = [Math.max(frame.minCol, Math.min(frame.maxCol, at[0])), Math.max(frame.minRow, Math.min(frame.maxRow, at[1]))];
    }
    const [col, row] = freeCell(at[0], at[1], taken, limit, allowed);
    taken.add(`${col},${row}`);
    return { item, col, row, placement: "schematic" };
  };
  // Точная клетка не сдвигается к краю изображения: иначе меняется механическая дистанция.
  // Книжная клетка известна геометрически, но необязательно записана в состоянии боя.
  const exact = <T>(item: T, [col, row]: [number, number], placement: "mechanical" | "book"): Cell<T> => {
    taken.add(`${col},${row}`);
    return { item, col, row, placement };
  };
  const party = m.party ?? [];
  const placed = new Map<string, Cell<MapHero> | Cell<MapThing>>();
  for (const h of party) {
    const cell = h.cell ?? bookCells.get(h.id);
    if (cell) placed.set(h.id, exact(h, cell, h.cell ? "mechanical" : "book"));
  }
  for (const t of m.around) {
    const cell = t.cell ?? bookCells.get(t.id);
    if (cell) placed.set(t.id, exact(t, cell, t.cell ? "mechanical" : "book"));
  }
  // потом герои в строю — вокруг центра, потом все остальные по зонам; выходы — по краю схемы
  const heroes = [
    ...party.filter((h) => !placed.has(h.id) && !h.zone).map((h) => put(h, [0, 0])),
    ...party.filter((h) => !placed.has(h.id) && h.zone).map((h) => put(h, target(h.id, h.bearing, ZONE_CELLS[h.zone as Zone]))),
    ...party.filter((h) => placed.has(h.id)).map((h) => placed.get(h.id) as Cell<MapHero>),
  ];
  const things = m.around.map(
    (t) =>
      (placed.get(t.id) as Cell<MapThing> | undefined) ??
      put(t, target(t.id, t.bearing, ZONE_CELLS[t.zone] ?? ZONE_CELLS.near)),
  );
  const exits = m.exits
    .filter((x) => x.id !== null && !(m.sketch?.book && x.room_ref) && !drawn.has(x.id))
    .map((x) => {
      const [c, r] = target(x.id ?? x.room_ref ?? "exit", x.bearing, reach);
      return put(x, [Math.max(-reach, Math.min(reach, c)), Math.max(-reach, Math.min(reach, r))]);
    });
  // область не занимает клетку: она лежит под значками
  const areas = (m.areas ?? []).map((a) => {
    const [col, row] = target(a.id, a.bearing, ZONE_CELLS[a.zone] ?? ZONE_CELLS.near);
    return { item: a, col, row, placement: "schematic" as const };
  });
  return { heroes, things, exits, areas };
}

/** Точная клетка за пределом видимой схемы не подменяется граничной. */
export function inMapFrame(position: Pick<Cell<unknown>, "col" | "row">, sketch?: Sketch | null): boolean {
  if (sketch) {
    const frame = sketchFrame(sketch);
    return (
      position.col >= frame.minCol && position.col <= frame.maxCol &&
      position.row >= frame.minRow && position.row <= frame.maxRow
    );
  }
  return Math.abs(position.col) <= GRID_R && Math.abs(position.row) <= GRID_R;
}

/** Клик на условный значок не может стать точным запросом map.step. */
export function mechanicalNear<T>(position: Cell<T>): [number, number][] {
  return position.placement === "mechanical" ? [[position.col, position.row]] : [];
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

/** Начало фразы для кнопки «Взаимодействовать»: цель названа, действие игрок дописывает сам. */
export function interactText(name: string): string {
  return `«${name}»: `;
}

/** Вещи на одной клетке — одной стопкой: несколько предметов на обысканном столе, добыча под павшим врагом.
 * ``under`` — на клетке стоит герой, и стопка рисуется маленькой меткой у края клетки, чтобы её было видно. */
export interface CellStack {
  col: number;
  row: number;
  items: MapThing[];
  under: boolean;
}

export function stackCells(things: { item: MapThing; col: number; row: number }[], heroes: { col: number; row: number }[]): CellStack[] {
  const byCell = new Map<string, CellStack>();
  for (const { item, col, row } of things) {
    const key = `${col},${row}`;
    const s = byCell.get(key) ?? { col, row, items: [], under: false };
    s.items.push(item);
    byCell.set(key, s);
  }
  for (const h of heroes) {
    const s = byCell.get(`${h.col},${h.row}`);
    if (s) s.under = true;
  }
  return [...byCell.values()];
}

/** Подпись стопки: «Кинжал, Ключ» или «Кинжал и ещё 3». */
export function stackTitle(items: { name: string }[]): string {
  if (items.length <= 2) return items.map((t) => t.name).join(", ");
  return `${items[0].name} и ещё ${items.length - 1}`;
}
