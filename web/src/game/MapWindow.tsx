import { useEffect, useState, type MouseEvent } from "react";
import BookMap from "./BookMap";
import { entityVisual, EXIT_VISUALS, FEATURE_VISUALS, MAP_PRESETS } from "./mapPresets";
import { MapGlyph } from "./MapGlyph";
import { useDraft } from "./draft";
import { TYPE_COLOR, TYPE_ICON } from "./entities";
import { useInspector } from "./inspector";
import { fitLabel, GridLines, Token } from "./GridBoard";
import {
  CELL_FT,
  COVER_NAME,
  ELEVATION_NAME,
  GRID_R,
  interactText,
  layoutGrid,
  stackCells,
  stackTitle,
  layoutPlaces,
  useMapWindow,
  ZONE_CELLS,
  type Zone,
  type Cover,
  type Elevation,
  type MapState,
  type Sketch,
  type SketchExit,
  type StepRequest,
  type CellStack,
  exitCell,
  sketchFrame,
  whereTrail,
} from "./map";

const ZONES: [Zone, string][] = [
  ["melee", "вплотную"],
  ["near", "близко"],
  ["far", "далеко"],
];

const ZONE_LABELS: Record<Zone, string> = {
  melee: "вплотную · 5 фт",
  near: "близко · 30 фт",
  far: "далеко · 60+ фт",
};

const RING_NAME: Record<Zone, string> = { melee: "вплотную", near: "близко", far: "далеко" };

function short(s: string, n: number): string {
  return s.length > n ? `${s.slice(0, n - 1)}…` : s;
}

/** Пометки у значка: высота (▲ возвышение, ▼ низ) и укрытие (◧, ■ полное). */
function badge(elevation?: Elevation, cover?: Cover): string | undefined {
  const marks = [elevation === "high" ? "▲" : elevation === "low" ? "▼" : "", cover && cover !== "none" ? (cover === "total" ? "■" : "◧") : ""];
  return marks.join("") || undefined;
}

// Схема «Вокруг» — клетки по 5 футов, отряд в клетке (0, 0). Без эскиза — квадрат 27×27 с кругами дальности,
// с эскизом — само место и клетка запаса по краям для выходов.
const CELL = 15;
const SIDE = 2 * GRID_R + 1;
const PAD = 20;

interface View {
  c0: number;
  r0: number;
  cols: number;
  rows: number;
}

function viewOf(sk: Sketch | null | undefined): View {
  if (!sk) return { c0: -GRID_R, r0: -GRID_R, cols: SIDE, rows: SIDE };
  const f = sketchFrame(sk);
  const wExits = sk.exits.filter((x) => x.side === "w");
  const eExits = sk.exits.filter((x) => x.side === "e");
  const nExits = sk.exits.filter((x) => x.side === "n");
  const sExits = sk.exits.filter((x) => x.side === "s");

  const maxWLen = Math.max(0, ...wExits.map((x) => (x.beyond || x.name || "").length));
  const maxELen = Math.max(0, ...eExits.map((x) => (x.beyond || x.name || "").length));

  // На одну букву шрифта 7px уходит ~4.5px, размер клетки CELL = 15px
  const mW = wExits.length > 0 ? Math.max(3, Math.min(6, Math.ceil((maxWLen * 4.5) / CELL) + 1)) : 2;
  const mE = eExits.length > 0 ? Math.max(3, Math.min(6, Math.ceil((maxELen * 4.5) / CELL) + 1)) : 2;
  const mN = nExits.length > 0 ? 3 : 2;
  const mS = sExits.length > 0 ? 3 : 2;

  return {
    c0: f.minCol - mW,
    r0: f.minRow - mN,
    cols: f.maxCol - f.minCol + 1 + mW + mE,
    rows: f.maxRow - f.minRow + 1 + mN + mS,
  };
}

const EXIT_KIND: Record<SketchExit["kind"], string> = {
  door: "дверь",
  bars: "решётка",
  window: "окно",
  arch: "арка",
  stairs: "лестница",
  hatch: "люк",
  gap: "пролом",
  passage: "проход",
};
const EXIT_STATE: Record<string, string> = { open: "открыто", closed: "закрыто", locked: "заперто" };

function posNote(elevation?: Elevation, cover?: Cover): string | null {
  const parts = [elevation && elevation !== "ground" ? ELEVATION_NAME[elevation] : null, cover && cover !== "none" ? COVER_NAME[cover] : null];
  return parts.filter(Boolean).join(", ") || null;
}

/** Что игрок выбрал на схеме: предмет эскиза, выход или значок. ``near`` — клетки цели от строя отряда. */
interface Pick {
  name: string;
  near: [number, number][];
  exit?: SketchExit;
  /** несколько вещей на одной клетке: у каждой своя кнопка «Взаимодействовать» */
  items?: { id: string; name: string }[];
}

/** Открыть карточку по маркеру: для SVG якорь — сам маркер, у него есть рамка на экране. */
function useOpen() {
  const open = useInspector((s) => s.open);
  return (id: string, name: string) => (e: MouseEvent<Element>) => open(id, name, e.currentTarget as unknown as HTMLElement);
}

/** Эскиз места: пол и стены, крупные предметы и выходы по краю с тем, что за ними. */
function SketchLayer({
  sk,
  px,
  py,
  onOpen,
  onPick,
}: {
  sk: Sketch;
  px: (c: number) => number;
  py: (r: number) => number;
  onOpen: (id: string, name: string) => (e: MouseEvent<Element>) => void;
  onPick: (p: Pick) => void;
}) {
  const f = sketchFrame(sk);
  const cells: [number, number][] = [];
  for (let c = f.minCol; c <= f.maxCol; c++) for (let r = f.minRow; r <= f.maxRow; r++) cells.push([c, r]);
  const at = (c: number, r: number) => ({ x: px(c) - CELL / 2, y: py(r) - CELL / 2 });
  const rounded = sk.shape === "cave";
  return (
    <g aria-hidden="false">
      {cells.map(([c, r]) => {
        const p = at(c, r);
        const wall = f.walls.has(`${c},${r}`);
        return (
          <rect
            key={`${c},${r}`}
            x={p.x}
            y={p.y}
            width={CELL}
            height={CELL}
            rx={rounded && wall ? 4 : 0}
            fill={wall ? "var(--color-line, #2a2b31)" : "var(--color-raised, #202127)"}
            stroke="var(--color-line, #2a2b31)"
            strokeOpacity={0.35}
            strokeWidth={0.5}
          />
        );
      })}
      {/* Мягкий свет факела вокруг центра отряда */}
      <circle
        cx={px(0)}
        cy={py(0)}
        r={CELL * 4.5}
        fill="var(--tf-accent, #c98a4b)"
        fillOpacity={0.06}
        className="pointer-events-none select-none"
      />
      <rect
        x={px(f.minCol) - CELL / 2}
        y={py(f.minRow) - CELL / 2}
        width={(f.maxCol - f.minCol + 1) * CELL}
        height={(f.maxRow - f.minRow + 1) * CELL}
        rx={rounded ? 10 : 0}
        fill="none"
        stroke="var(--color-ink-2, #cfc8bb)"
        strokeWidth={sk.shape === "open" ? 0.8 : 2}
        strokeDasharray={sk.shape === "open" || sk.shape === "street" ? "4 3" : undefined}
        style={{ filter: "drop-shadow(0 2px 5px rgba(0,0,0,0.3))" }}
      />
      {sk.features.map((ft, i) =>
        ft.cells.map(([c0, r0, c1, r1], j) => {
          const p = at(c0 - f.dc, r0 - f.dr);
          const w = (c1 - c0 + 1) * CELL;
          const h = (r1 - r0 + 1) * CELL;
          const cells: [number, number][] = [];
          for (const [a0, b0, a1, b1] of ft.cells) for (let c = a0; c <= a1; c++) for (let r = b0; r <= b1; r++) cells.push([c - f.dc, r - f.dr]);
          return (
            <g key={`${i}-${j}`} className="cursor-pointer" role="button" aria-label={ft.name} onClick={() => onPick({ name: ft.name, near: cells })}>
              <title>{ft.name}</title>
              <rect x={p.x + 1.5} y={p.y + 1.5} width={w - 3} height={h - 3} rx={2} fill={FEATURE_VISUALS[ft.kind].color} fillOpacity={0.17} stroke={FEATURE_VISUALS[ft.kind].color} strokeWidth={1} />
              {j === 0 && (
                <MapGlyph name={FEATURE_VISUALS[ft.kind].glyph}
                  x={p.x + 3} y={p.y + (h - Math.min(CELL - 6, 10)) / 2}
                  width={Math.min(CELL - 6, 10)} height={Math.min(CELL - 6, 10)}
                  color={FEATURE_VISUALS[ft.kind].color} className="pointer-events-none" />
              )}
              {j === 0 && w >= CELL * 2 && (
                <text
                  x={p.x + w / 2 + 5}
                  y={p.y + h / 2 + 2.5}
                  textAnchor="middle"
                  fontSize={6.5}
                  fill="var(--color-ink, #ddd)"
                  paintOrder="stroke"
                  stroke="var(--color-surface, #17181c)"
                  strokeWidth={2}
                  strokeLinejoin="round"
                >
                  {short(ft.name, Math.max(6, Math.floor(w / 3.5)))}
                </text>
              )}
            </g>
          );
        }),
      )}
      {sk.exits.map((x, i) => {
        const [c, r] = exitCell(sk, x);
        const cx = px(c);
        const cy = py(r);
        const shut = x.state === "locked" || x.state === "closed";
        const color = shut ? "var(--tf-ember, #c0563a)" : EXIT_VISUALS[x.kind].color;
        const label = `${x.name}: ${EXIT_KIND[x.kind]}${x.state ? `, ${EXIT_STATE[x.state]}` : ""}${x.beyond ? `, за ним ${x.beyond}` : ""}`;
        const title = x.beyond || x.name;
        const titleText = title ? short(title, 14) : "";
        const isWest = x.side === "w";
        const isEast = x.side === "e";
        const isHoriz = isWest || isEast;

        // Размеры плашки выхода
        const textW = titleText ? titleText.length * 4.5 + 4 : 0;
        const pillW = isHoriz ? (titleText ? CELL + textW : CELL - 2) : (titleText ? Math.max(CELL, textW + 8) : CELL - 2);
        const pillH = CELL - 2;

        let pillX = cx - pillW / 2;
        let pillY = cy - pillH / 2;
        if (isWest) {
          pillX = cx + CELL / 2 - 1 - pillW;
        } else if (isEast) {
          pillX = cx - CELL / 2 + 1;
        }

        return (
          <g
            key={i}
            className="cursor-pointer group"
            onClick={(e) => {
              onPick({ name: x.name, near: [[c, r]], exit: x });
              if (x.to) onOpen(x.to, x.name)(e);
            }}
            role="button"
            aria-label={label}
          >
            <title>{label}</title>
            <rect
              x={pillX}
              y={pillY}
              width={pillW}
              height={pillH}
              rx={3.5}
              fill="var(--color-surface, #17181c)"
              stroke={color}
              strokeWidth={1.2}
              className="transition-all duration-150 group-hover:stroke-accent group-hover:brightness-110"
              style={{ filter: "drop-shadow(0 1px 3px rgba(0,0,0,0.3))" }}
            />
            <MapGlyph name={EXIT_VISUALS[x.kind].glyph}
              x={(isHoriz ? cx : pillX + 6.5) - 5}
              y={cy - 5} width={10} height={10}
              color={color} className="pointer-events-none" />
            {titleText && (
              <text
                x={isWest ? cx - CELL / 2 - 2.5 : isEast ? cx + CELL / 2 + 2.5 : pillX + 15}
                y={cy + 2.5}
                textAnchor={isWest ? "end" : "start"}
                fontSize={6.8}
                fontWeight={500}
                fill="var(--color-ink, #ddd)"
                className="pointer-events-none select-none"
              >
                {titleText}
              </text>
            )}
          </g>
        );
      })}
    </g>
  );
}

const SHAPE_NAME: Record<Sketch["shape"], string> = {
  room: "помещение",
  corridor: "коридор",
  cave: "пещера",
  street: "улица",
  open: "открытое место",
};

/** Под эскизом словами: форма и размер, выходы и что за ними, крупные предметы. */
function SketchLegend({ sk }: { sk: Sketch }) {
  return (
    <ul className="flex flex-col gap-1 text-sm">
      <li>
        <span className="font-mono text-xs uppercase text-muted">место: </span>
        {SHAPE_NAME[sk.shape]} {sk.cols * 5}×{sk.rows * 5} футов
      </li>
      {sk.exits.length > 0 && (
        <li>
          <span className="font-mono text-xs uppercase text-muted">выходы: </span>
          {sk.exits
            .map((x) => `${x.name} (${[EXIT_KIND[x.kind], x.state && x.state !== "open" ? EXIT_STATE[x.state] : null, x.beyond ? `за ним ${x.beyond}` : null].filter(Boolean).join(", ")})`)
            .join("; ")}
        </li>
      )}
      {(sk.unplaced_exits?.length ?? 0) > 0 && (
        <li>
          <span className="font-mono text-xs uppercase text-muted">проходы без разметки: </span>
          {sk.unplaced_exits!.map((x) => x.name).join("; ")}. Точное положение дверей на карте книги не определено.
        </li>
      )}
      {sk.features.length > 0 && (
        <li>
          <span className="font-mono text-xs uppercase text-muted">видно: </span>
          {sk.features.map((f) => f.name).join(", ")}
        </li>
      )}
    </ul>
  );
}

/** Компактная роза ветров в углу тактической карты. */
function CompassRose({ x, y }: { x: number; y: number }) {
  return (
    <g transform={`translate(${x}, ${y})`} className="select-none pointer-events-none" aria-label="Компас: Север вверху">
      <circle cx={0} cy={0} r={11} fill="var(--color-surface, #17181c)" fillOpacity={0.88} stroke="var(--color-line, #333)" strokeWidth={0.8} />
      <line x1={0} y1={-9} x2={0} y2={9} stroke="var(--color-line, #444)" strokeWidth={0.6} />
      <line x1={-9} y1={0} x2={9} y2={0} stroke="var(--color-line, #444)" strokeWidth={0.6} />
      <polygon points="0,-9 -2.5,-2 0,-3.5 2.5,-2" fill="var(--tf-accent, #c98a4b)" />
      <polygon points="0,9 -2,2 0,3 2,2" fill="var(--color-muted, #777)" />
      <text x={0} y={-11.5} textAnchor="middle" fontSize={7.5} fontWeight={700} fill="var(--tf-accent, #c98a4b)">
        С
      </text>
      <text x={13} y={2.5} fontSize={5.5} fill="var(--color-muted, #888)" textAnchor="start">
        В
      </text>
      <text x={0} y={16.5} fontSize={5.5} fill="var(--color-muted, #888)" textAnchor="middle">
        Ю
      </text>
      <text x={-13} y={2.5} fontSize={5.5} fill="var(--color-muted, #888)" textAnchor="end">
        З
      </text>
    </g>
  );
}

function Around({ m }: { m: MapState }) {
  const open = useOpen();
  const { things, exits, heroes, areas } = layoutGrid(m);
  const [pick, setPick] = useState<Pick | null>(null);
  const isSelected = (c: number, r: number) => pick?.near?.some(([col, row]) => col === c && row === r) ?? false;
  const { step, stepTo, cancelStep } = useMapWindow();
  const go = (req: StepRequest) => stepTo(req);
  const canWalk = heroes.some((h) => h.item.mine) && !step.busy;
  const occupied = new Set([...things, ...exits, ...heroes].map((x) => `${x.col},${x.row}`));
  const combat = m.mode === "combat";
  const sk = m.sketch ?? null;
  const v = viewOf(sk);
  const W = v.cols * CELL;
  const H = v.rows * CELL;
  const px = (c: number) => (c - v.c0) * CELL + CELL / 2;
  const py = (r: number) => (r - v.r0) * CELL + CELL / 2;
  const MX = px(0);
  const MY = py(0);
  const frame = sk ? sketchFrame(sk) : null;
  const floor: [number, number][] = [];
  for (let c = v.c0; c < v.c0 + v.cols; c++)
    for (let r = v.r0; r < v.r0 + v.rows; r++) if ((!frame || frame.allowed(c, r)) && !occupied.has(`${c},${r}`)) floor.push([c, r]);
  const pickThing = (id: string, name: string, col: number, row: number) => (e: MouseEvent<Element>) => {
    setPick({ name, near: [[col, row]] });
    open(id, name)(e);
  };
  const stacks = stackCells(things, heroes);
  const pickStack = (st: CellStack) => () => {
    if (st.items.length === 1) {
      const t = st.items[0];
      setPick({ name: t.name, near: [[st.col, st.row]], items: [{ id: t.id, name: t.name }] });
      return;
    }
    setPick({ name: stackTitle(st.items), near: [[st.col, st.row]], items: st.items.map((t) => ({ id: t.id, name: t.name })) });
  };

  return (
    <div className="flex flex-col gap-3">
      <p className="font-heading text-sm font-semibold text-ink">
        <span className="text-accent">⌖</span> {whereTrail(m)}
      </p>
      {m.here?.description && <p className="font-narration text-sm leading-relaxed text-ink-2">{m.here.description}</p>}
      <svg viewBox={`${-PAD} ${-PAD} ${W + 2 * PAD} ${H + 2 * PAD}`} className="mx-auto w-full max-w-[30rem] select-none" role="img" aria-label="Схема места">
        <rect x={0} y={0} width={W} height={H} fill="var(--color-surface, #17181c)" />
        {sk ? <SketchLayer sk={sk} px={px} py={py} onOpen={open} onPick={setPick} /> : <GridLines x={0} y={0} cols={SIDE} rows={SIDE} size={CELL} />}

        {/* Свободные клетки: нажатие ведёт туда героя игрока */}
        {canWalk &&
          floor.map(([c, r]) => (
            <rect
              key={`step-${c},${r}`}
              className="tf-step cursor-pointer"
              x={px(c) - CELL / 2}
              y={py(r) - CELL / 2}
              width={CELL}
              height={CELL}
              fill="var(--tf-accent, #c98a4b)"
              onClick={() => go({ cell: [c, r] })}
              aria-label={`Идти в клетку ${c}, ${r}`}
            />
          ))}

        {/* Дальности: 5 фт, 30 фт, «далеко» у края; у места с эскизом их заменяет само место */}
        {!sk && ZONES.map(([z]) => (
          <g key={z} aria-hidden="true">
            <circle cx={MX} cy={MY} r={(ZONE_CELLS[z] + 0.5) * CELL} fill="none" stroke="var(--tf-accent, #c98a4b)" strokeWidth={0.8} strokeOpacity={0.35} strokeDasharray="3 4" />
            <text x={MX - (ZONE_CELLS[z] + 0.5) * CELL * 0.71 - 2} y={MY - (ZONE_CELLS[z] + 0.5) * CELL * 0.71 - 2} textAnchor="end" fontSize={7} fontFamily="var(--tf-font-mono, monospace)" fill="var(--color-muted, #a8a296)">
              {ZONE_LABELS[z]}
            </text>
          </g>
        ))}

        {/* Компас (роза ветров в правом верхнем углу) */}
        <CompassRose x={W + 2} y={-4} />

        {areas.map(({ item: a, col, row }) => (
          <g key={a.id} className="cursor-pointer" onClick={open(a.id, a.name)} role="button" aria-label={`Область: ${a.name}`}>
            <circle cx={px(col)} cy={py(row)} r={Math.max(0.5, a.radius_ft / CELL_FT) * CELL} fill="var(--tf-ember, #c0563a)" fillOpacity={0.18} stroke="var(--tf-ember, #c0563a)" strokeDasharray="4 3" />
            <text x={px(col)} y={py(row) - Math.max(0.5, a.radius_ft / CELL_FT) * CELL + 9} textAnchor="middle" fontSize={8} fill="var(--tf-ember, #c0563a)">
              {short(a.name, 20)} · {a.radius_ft} фт
            </text>
          </g>
        ))}

        {heroes.length === 0 && <Token cx={MX} cy={MY} size={CELL} visual={MAP_PRESETS.hero} label="отряд" ariaLabel="Отряд" />}
        {exits.map(({ item: x, col, row }) => (
          <Token
            key={x.id}
            cx={px(col)}
            cy={py(row)}
            size={CELL}
            visual={MAP_PRESETS.location}
            label={fitLabel(x.name, occupied, col, row, false)}
            dashed={!x.visited}
            selected={isSelected(col, row)}
            onClick={pickThing(x.id, x.name, col, row)}
            ariaLabel={`Выход: ${x.name}`}
          />
        ))}
        {stacks
          .filter((st) => !st.under)
          .map((st) => {
            const t = st.items[0];
            const isSel = isSelected(st.col, st.row);
            if (st.items.length === 1)
              return (
                <Token
                  key={t.id}
                  cx={px(st.col)}
                  cy={py(st.row)}
                  size={CELL}
                  visual={entityVisual(t.type, t.visual_key)}
                  label={fitLabel(t.name, occupied, st.col, st.row, false)}
                  faded={t.condition === "мёртв"}
                  badge={badge(t.elevation, t.cover)}
                  selected={isSel}
                  onClick={pickThing(t.id, t.name, st.col, st.row)}
                  ariaLabel={t.name}
                />
              );
            const title = stackTitle(st.items);
            return (
              <Token
                key={`stack:${st.col},${st.row}`}
                cx={px(st.col)}
                cy={py(st.row)}
                size={CELL}
                visual={entityVisual(t.type, t.visual_key)}
                label={fitLabel(title, occupied, st.col, st.row, false)}
                badge={`×${st.items.length}`}
                selected={isSel}
                onClick={pickStack(st)}
                ariaLabel={title}
              />
            );
          })}
        {heroes.map(({ item: h, col, row }) => (
          <Token
            key={h.id}
            cx={px(col)}
            cy={py(row)}
            size={CELL}
            visual={MAP_PRESETS.hero}
            label={fitLabel(h.name, occupied, col, row, true)}
            ring={h.mine}
            faded={h.down}
            badge={badge(h.elevation, h.cover)}
            selected={isSelected(col, row)}
            onClick={open(h.id, h.name)}
            ariaLabel={h.name}
          />
        ))}
        {/* вещи под ногами героя: метка в углу клетки, иначе значок героя их закроет */}
        {stacks
          .filter((st) => st.under)
          .map((st) => (
            <g key={`under:${st.col},${st.row}`} className="cursor-pointer" role="button" aria-label={stackTitle(st.items)} onClick={pickStack(st)}>
              <title>{stackTitle(st.items)}</title>
              <circle cx={px(st.col) + CELL * 0.36} cy={py(st.row) + CELL * 0.36} r={CELL * 0.17} fill={TYPE_COLOR[st.items[0].type]} stroke="var(--color-bg, #111)" strokeWidth={1} />
              <text x={px(st.col) + CELL * 0.36} y={py(st.row) + CELL * 0.36 + 2.5} textAnchor="middle" fontSize={7} fill="var(--color-bg, #111)">
                {st.items.length}
              </text>
            </g>
          ))}
      </svg>
      <StepBar pick={canWalk || step.busy ? pick : null} onClose={() => setPick(null)} go={go} />
      {(step.note || step.error || step.warnings) && (
        <div role="status" className={`rounded border px-3 py-2 text-sm ${step.error ? "border-ember text-ember" : "border-line text-ink-2"}`}>
          {step.error ?? (step.warnings ? step.warnings.join("; ") : step.note)}
          {step.warnings && step.pending && (
            <span className="ml-2 inline-flex gap-2">
              <button className="btn px-2 py-0.5 text-xs" onClick={() => stepTo(step.pending as StepRequest, true)}>
                Всё равно идти
              </button>
              <button className="btn px-2 py-0.5 text-xs" onClick={cancelStep}>
                Отмена
              </button>
            </span>
          )}
        </div>
      )}
      {heroes.some((h) => h.item.mine) && !step.note && !step.error && !step.warnings && (
        <p className="text-center font-mono text-[11px] text-muted">Нажми свободную клетку — герой пойдёт туда. Нажми предмет или выход — подойти или взаимодействовать. Цифра — сколько вещей лежит на клетке.</p>
      )}
      {combat && (
        <p className="text-center font-mono text-[11px] text-muted">
          Бой: ▲ на возвышении, ▼ внизу, ◧ за укрытием (+2 или +5 к КД), ■ полное укрытие. Клетка — 5 футов; «далеко» нарисовано у края схемы.
        </p>
      )}

      {sk && <SketchLegend sk={sk} />}
      {m.around.length === 0 && m.exits.length === 0 && !sk && (
        <p className="text-center font-mono text-xs text-muted">Мастер ещё не отметил, что здесь есть.</p>
      )}
      <ul className="flex flex-col gap-1 text-sm">
        {ZONES.map(([z, name]) => {
          const list = m.around.filter((t) => t.zone === z);
          if (!list.length) return null;
          return (
            <li key={z}>
              <span className="font-mono text-xs uppercase text-muted">{name}: </span>
              {list.map((t, i) => (
                <span key={t.id}>
                  {i > 0 && ", "}
                  <button className="underline decoration-dotted underline-offset-4" style={{ color: TYPE_COLOR[t.type] }} onClick={open(t.id, t.name)}>
                    {TYPE_ICON[t.type]} {t.name}
                  </button>
                  {(t.bearing || posNote(t.elevation, t.cover)) && (
                    <span className="text-muted"> ({[t.bearing ? m.bearings[t.bearing] : null, posNote(t.elevation, t.cover)].filter(Boolean).join(", ")})</span>
                  )}
                  {t.condition && t.condition !== "невредим" && <span className="text-muted"> · {t.condition}</span>}
                </span>
              ))}
            </li>
          );
        })}
        {(m.party ?? []).some((h) => h.zone || posNote(h.elevation, h.cover)) && (
          <li>
            <span className="font-mono text-xs uppercase text-muted">отряд: </span>
            {(m.party ?? []).map((h, i) => (
              <span key={h.id}>
                {i > 0 && ", "}
                <button className="underline decoration-dotted underline-offset-4" style={{ color: "var(--tf-accent)" }} onClick={open(h.id, h.name)}>
                  ★ {h.name}
                </button>
                <span className="text-muted">
                  {" "}
                  ({[h.zone ? `${RING_NAME[h.zone]}${h.bearing ? `, ${m.bearings[h.bearing]}` : ""}` : "в строю", posNote(h.elevation, h.cover)].filter(Boolean).join(", ")})
                </span>
              </span>
            ))}
          </li>
        )}
        {(m.areas ?? []).length > 0 && (
          <li>
            <span className="font-mono text-xs uppercase text-muted">области: </span>
            {(m.areas ?? []).map((a, i) => (
              <span key={a.id}>
                {i > 0 && ", "}
                <button className="underline decoration-dotted underline-offset-4" style={{ color: "var(--tf-ember)" }} onClick={open(a.id, a.name)}>
                  {a.name}
                </button>
                <span className="text-muted"> (радиус {a.radius_ft} фт)</span>
              </span>
            ))}
          </li>
        )}
        {m.exits.length > 0 && (
          <li>
            <span className="font-mono text-xs uppercase text-muted">куда можно пройти: </span>
            {m.exits.map((x, i) => (
              <span key={x.id}>
                {i > 0 && ", "}
                <button className="underline decoration-dotted underline-offset-4" style={{ color: TYPE_COLOR.location }} onClick={open(x.id, x.name)}>
                  {x.name}
                </button>
                <span className="text-muted">
                  {" "}
                  ({[x.via, x.bearing ? m.bearings[x.bearing] : null, x.visited ? null : "ещё не были"].filter(Boolean).join(", ")})
                </span>
              </span>
            ))}
          </li>
        )}
      </ul>
    </div>
  );
}

/** Выбранная цель на схеме: подойти к ней или начать фразу о ней в поле ввода (решение Arty: что именно делать,
 * игрок дописывает сам, а мастер решает). */
function StepBar({ pick, onClose, go }: { pick: Pick | null; onClose: () => void; go: (r: StepRequest) => void }) {
  const insert = useDraft((s) => s.insert);
  const openCard = useOpen();
  if (!pick) return null;
  return (
    <div className="flex flex-wrap items-center gap-2 rounded border border-line px-3 py-2 text-sm">
      <span className="font-heading text-ink">{pick.name}</span>
      <button className="btn px-2 py-0.5 text-xs" onClick={() => go({ near: pick.near })}>
        Подойти
      </button>
      {pick.items && pick.items.length > 1 ? (
        <ul className="flex w-full flex-col gap-1" aria-label="Что здесь лежит">
          {pick.items.map((t) => (
            <li key={t.id} className="flex items-center gap-2">
              <button className="text-ink underline decoration-dotted underline-offset-4" onClick={(e) => openCard(t.id, t.name)(e)}>
                {t.name}
              </button>
              <button
                className="btn px-2 py-0.5 text-xs"
                onClick={() => {
                  insert(interactText(t.name));
                  onClose();
                }}
              >
                Взаимодействовать
              </button>
            </li>
          ))}
        </ul>
      ) : (
        <button
          className="btn px-2 py-0.5 text-xs"
          onClick={() => {
            insert(interactText(pick.name));
            onClose();
          }}
        >
          Взаимодействовать
        </button>
      )}
      <button className="ml-auto text-muted hover:text-ink" onClick={onClose} aria-label="Снять выбор">
        ×
      </button>
    </div>
  );
}

const COL = 170;
const ROW = 58;
const W = 140;
const H = 32;

function Places({ m }: { m: MapState }) {
  const open = useOpen();
  if (!m.places.length) return <p className="text-center font-mono text-xs text-muted">Отряд ещё не открыл ни одного места.</p>;
  const laid = layoutPlaces(m);
  const pos = new Map(laid.map((p) => [p.place.id, { x: 20 + p.col * COL, y: 20 + p.row * ROW }]));
  const cols = Math.max(...laid.map((p) => p.col)) + 1;
  const rows = Math.max(...laid.map((p) => p.row)) + 1;
  const width = 20 + cols * COL;
  const height = 30 + rows * ROW;
  const edge = (a: string, b: string) => {
    const p = pos.get(a)!;
    const q = pos.get(b)!;
    return { x1: p.x + W / 2, y1: p.y + H / 2, x2: q.x + W / 2, y2: q.y + H / 2 };
  };

  return (
    <div className="flex flex-col gap-2">
      <div className="overflow-x-auto rounded-lg border border-line bg-bg/50 p-2">
        <svg viewBox={`0 0 ${width} ${height}`} width={width} height={height} className="select-none" role="img" aria-label="Карта мест">
          <defs>
            <pattern id="places-grid" width="24" height="24" patternUnits="userSpaceOnUse">
              <path d="M 24 0 L 0 0 0 24" fill="none" stroke="var(--color-line, #2a2b31)" strokeWidth="0.6" strokeOpacity="0.4" />
            </pattern>
          </defs>
          <rect width={width} height={height} fill="url(#places-grid)" />
          {m.places
            .filter((p) => p.parent_id && pos.has(p.parent_id))
            .map((p) => (
              <line key={`p${p.id}`} {...edge(p.id, p.parent_id!)} stroke="var(--color-muted, #888)" strokeWidth={1} strokeDasharray="2 4" strokeOpacity={0.6} />
            ))}
          {m.links.map((l) => {
            const e = edge(l.a, l.b);
            return (
              <g key={`${l.a}-${l.b}`}>
                <line {...e} stroke={TYPE_COLOR.location} strokeWidth={1.8} strokeOpacity={0.75} />
                {l.label && (
                  <text x={(e.x1 + e.x2) / 2} y={(e.y1 + e.y2) / 2 - 4} textAnchor="middle" fontSize={9} fill="var(--color-muted, #888)">
                    {short(l.label, 14)}
                  </text>
                )}
              </g>
            );
          })}
          {laid.map(({ place: p }) => {
            const { x, y } = pos.get(p.id)!;
            const here = p.status === "here";
            return (
              <g key={p.id} className="cursor-pointer group" onClick={open(p.id, p.name)} role="button" aria-label={p.name}>
                <rect
                  x={x}
                  y={y}
                  width={W}
                  height={H}
                  rx={6}
                  fill={here ? "var(--tf-accent)" : "var(--color-surface, #222)"}
                  fillOpacity={here ? 0.22 : 0.95}
                  stroke={here ? "var(--tf-accent)" : p.status === "visited" ? TYPE_COLOR.location : "var(--color-line, #2a2b31)"}
                  strokeWidth={here ? 1.8 : 1}
                  strokeDasharray={p.status === "known" ? "4 4" : undefined}
                />
                <text
                  x={x + W / 2}
                  y={y + 20}
                  textAnchor="middle"
                  fontSize={11}
                  fontWeight={here ? 600 : 400}
                  fill={p.status === "known" ? "var(--color-muted, #888)" : "var(--color-ink, #ddd)"}
                >
                  {here ? `⌖ ${short(p.name, 18)}` : short(p.name, 22)}
                </text>
                {here && (
                  <text x={x + W / 2} y={y + H + 12} textAnchor="middle" fontSize={9} fontWeight={600} fill="var(--tf-accent)">
                    вы здесь
                  </text>
                )}
              </g>
            );
          })}
        </svg>
      </div>
      <p className="font-mono text-[11px] text-muted">
        Сплошная рамка — были там, пунктир — знаете о месте, но не были. Тонкий пунктир ведёт к месту, внутри которого это.
      </p>
    </div>
  );
}

/** Окно карты: что вокруг героя и какие места отряд уже открыл. */
export default function MapWindow() {
  const { open, tab, data, loading, error, hide, setTab } = useMapWindow();

  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && !useInspector.getState().id && hide();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, hide]);

  if (!open) return null;
  return (
    <div className="fixed inset-0 z-40 flex items-end justify-center bg-black/50 md:items-center" onMouseDown={(e) => e.target === e.currentTarget && hide()}>
      <div role="dialog" aria-label="Карта" className="tf-pop flex max-h-[92dvh] w-full max-w-2xl flex-col overflow-hidden rounded-t-xl border border-line bg-surface md:rounded-xl">
        <header className="flex items-start justify-between gap-3 border-b border-line p-4">
          <div className="min-w-0">
            <h2 className="truncate font-heading text-xl font-bold text-ink">{data?.here ? data.here.name : "Карта"}</h2>
            <p className="font-mono text-xs text-muted">
              {loading ? "Обновляю карту…" : error ?? "Мастер дополняет карту по ходу игры"}
            </p>
          </div>
          <button className="text-2xl leading-none text-muted hover:text-ink" onClick={hide} aria-label="Закрыть">
            ×
          </button>
        </header>
        <nav className="flex gap-1 border-b border-line px-2" aria-label="Разделы карты">
          {(
            [
              ["around", "Вокруг"],
              ...(data?.book ? ([["book", "Карта книги"]] as const) : []),
              ["places", "Места"],
            ] as const
          ).map(([t, name]) => (
            <button
              key={t}
              className={`shrink-0 border-b-2 px-3 py-2 text-sm ${tab === t ? "border-accent text-ink" : "border-transparent text-muted"}`}
              onClick={() => setTab(t)}
            >
              {name}
            </button>
          ))}
        </nav>
        <div className="overflow-y-auto p-4">
          {!data ? (
            <p className="text-center font-mono text-xs text-muted">{error ?? "Загружаю карту…"}</p>
          ) : tab === "book" && data.book ? (
            <BookMap book={data.book} where={whereTrail(data)} />
          ) : tab === "around" || tab === "book" ? (
            data.here ? (
              <Around m={data} />
            ) : (
              <p className="text-center font-mono text-xs text-muted">Мастер ещё не объявил, где находится отряд.</p>
            )
          ) : (
            <Places m={data} />
          )}
        </div>
      </div>
    </div>
  );
}

/** Кнопка карты: в шапке игры и в панели сцены. */
export function MapButton({ className = "" }: { className?: string }) {
  const show = useMapWindow((s) => s.show);
  return (
    <button type="button" className={`btn btn-outline-copper h-8 px-2.5 text-xs font-mono tracking-wider ${className}`} onClick={() => show()} aria-label="Открыть карту">
      ⌖ КАРТА
    </button>
  );
}
