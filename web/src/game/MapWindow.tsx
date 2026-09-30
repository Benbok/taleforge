import { useEffect, type MouseEvent } from "react";
import { TYPE_COLOR, TYPE_ICON } from "./entities";
import { useInspector } from "./inspector";
import {
  areaPx,
  COVER_NAME,
  EDGE,
  ELEVATION_NAME,
  layoutAround,
  layoutPlaces,
  RING,
  useMapWindow,
  type Cover,
  type Elevation,
  type MapState,
} from "./map";

const ZONES: [keyof typeof RING, string][] = [
  ["melee", "вплотную"],
  ["near", "близко"],
  ["far", "далеко"],
];

const ZONE_LABELS: Record<keyof typeof RING, string> = {
  melee: "вплотную · 5 фт",
  near: "близко · 30 фт",
  far: "далеко · 60+ фт",
};

const RING_NAME: Record<keyof typeof RING, string> = { melee: "вплотную", near: "близко", far: "далеко" };

function short(s: string, n: number): string {
  return s.length > n ? `${s.slice(0, n - 1)}…` : s;
}

/** Значки у маркера: высота (▲ возвышение, ▼ низ) и укрытие (◧). */
function Badges({ x, y, elevation, cover }: { x: number; y: number; elevation?: Elevation; cover?: Cover }) {
  const marks = [elevation === "high" ? "▲" : elevation === "low" ? "▼" : "", cover && cover !== "none" ? (cover === "total" ? "■" : "◧") : ""]
    .filter(Boolean)
    .join("");
  if (!marks) return null;
  return (
    <text x={x + 11} y={y - 6} fontSize={9} fill="var(--color-warn, #d9a441)">
      {marks}
    </text>
  );
}

function posNote(elevation?: Elevation, cover?: Cover): string | null {
  const parts = [elevation && elevation !== "ground" ? ELEVATION_NAME[elevation] : null, cover && cover !== "none" ? COVER_NAME[cover] : null];
  return parts.filter(Boolean).join(", ") || null;
}

/** Открыть карточку по маркеру: для SVG якорь — сам маркер, у него есть рамка на экране. */
function useOpen() {
  const open = useInspector((s) => s.open);
  return (id: string, name: string) => (e: MouseEvent<Element>) => open(id, name, e.currentTarget as unknown as HTMLElement);
}

function Around({ m }: { m: MapState }) {
  const open = useOpen();
  const { things, exits, heroes, areas } = layoutAround(m);
  const combat = m.mode === "combat";

  return (
    <div className="flex flex-col gap-3">
      {m.here?.description && <p className="font-narration text-sm leading-relaxed text-ink-2">{m.here.description}</p>}
      <svg viewBox="-50 -20 500 440" className="mx-auto w-full max-w-[30rem] select-none" role="img" aria-label="Схема места">
        <defs>
          <radialGradient id="tf-radar-lens" cx="50%" cy="50%" r="50%">
            <stop offset="0%" stopColor="var(--tf-accent, #c98a4b)" stopOpacity="0.08" />
            <stop offset="60%" stopColor="var(--tf-accent, #c98a4b)" stopOpacity="0.02" />
            <stop offset="95%" stopColor="var(--color-bg, #0f1012)" stopOpacity="0.75" />
            <stop offset="100%" stopColor="var(--color-bg, #0f1012)" stopOpacity="0.95" />
          </radialGradient>
        </defs>

        {/* Фоновый тактический диск */}
        <circle cx={200} cy={200} r={EDGE + 8} fill="url(#tf-radar-lens)" stroke="var(--color-line, #2a2b31)" strokeWidth={1} />
        <circle cx={200} cy={200} r={EDGE + 4} fill="none" stroke="var(--tf-accent, #c98a4b)" strokeWidth={1} strokeOpacity={0.25} strokeDasharray="2 6" />

        {/* Оси видоискателя и румбы */}
        <line x1={200} y1={25} x2={200} y2={375} stroke="var(--tf-accent, #c98a4b)" strokeWidth={1} strokeOpacity={0.18} strokeDasharray="3 4" />
        <line x1={25} y1={200} x2={375} y2={200} stroke="var(--tf-accent, #c98a4b)" strokeWidth={1} strokeOpacity={0.18} strokeDasharray="3 4" />
        <line x1={76} y1={76} x2={324} y2={324} stroke="var(--color-line, #2a2b31)" strokeWidth={1} strokeOpacity={0.3} strokeDasharray="2 6" />
        <line x1={324} y1={76} x2={76} y2={324} stroke="var(--color-line, #2a2b31)" strokeWidth={1} strokeOpacity={0.3} strokeDasharray="2 6" />

        {/* Кольца зон с плашками дистанций */}
        {ZONES.map(([z]) => (
          <g key={z}>
            <circle cx={200} cy={200} r={RING[z]} fill="none" stroke="var(--tf-accent, #c98a4b)" strokeWidth={1} strokeOpacity={0.25} strokeDasharray="3 5" />
            <rect
              x={200 - RING[z] * 0.38 - 66}
              y={200 + RING[z] * 0.92 - 12}
              width={64}
              height={14}
              rx={3}
              fill="var(--color-surface, #17181c)"
              fillOpacity={0.9}
              stroke="var(--color-line, #2a2b31)"
              strokeWidth={0.8}
            />
            <text
              x={200 - RING[z] * 0.38 - 34}
              y={200 + RING[z] * 0.92 - 2}
              textAnchor="middle"
              fontSize={8.5}
              fontFamily="var(--tf-font-mono, monospace)"
              fill="var(--color-muted, #a8a296)"
            >
              {ZONE_LABELS[z]}
            </text>
          </g>
        ))}

        {/* Стороны света (Румбы компаса) */}
        <g className="font-mono select-none">
          <polygon points="200,8 196,17 204,17" fill="var(--tf-accent, #c98a4b)" />
          <text x={200} y={-1} textAnchor="middle" fontSize={11} fontWeight={700} fill="var(--tf-accent, #c98a4b)">
            С
          </text>
          <text x={200} y={402} textAnchor="middle" fontSize={10} fill="var(--color-muted, #888)">
            Ю
          </text>
          <text x={402} y={204} textAnchor="start" fontSize={10} fill="var(--color-muted, #888)">
            В
          </text>
          <text x={-2} y={204} textAnchor="end" fontSize={10} fill="var(--color-muted, #888)">
            З
          </text>
        </g>

        {areas.map(({ item: a, x, y }) => (
          <g key={a.id} className="cursor-pointer" onClick={open(a.id, a.name)} role="button" aria-label={`Область: ${a.name}`}>
            <circle cx={x} cy={y} r={areaPx(a.radius_ft)} fill="var(--tf-ember, #c0563a)" fillOpacity={0.18} stroke="var(--tf-ember, #c0563a)" strokeDasharray="4 3" />
            <text x={x} y={y - areaPx(a.radius_ft) + 12} textAnchor="middle" fontSize={9} fill="var(--tf-ember, #c0563a)">
              {short(a.name, 20)} · {a.radius_ft} фт
            </text>
          </g>
        ))}

        {heroes.length === 0 ? (
          <g>
            <circle cx={200} cy={200} r={14} fill="var(--tf-accent)" fillOpacity={0.2} />
            <circle cx={200} cy={200} r={8} fill="var(--tf-accent)" />
            <text x={200} y={224} textAnchor="middle" fontSize={10} fontWeight={600} fill="var(--color-ink, #ddd)">
              отряд
            </text>
          </g>
        ) : (
          <>
            {/* Тонкий ориентир центра строя */}
            <circle cx={200} cy={200} r={2} fill="var(--tf-accent)" opacity={0.6} />
            <circle cx={200} cy={200} r={24} fill="none" stroke="var(--tf-accent)" strokeWidth={0.8} strokeOpacity={0.15} strokeDasharray="2 3" />
            {heroes.map(({ item: h, x, y }) => (
              <g key={h.id} className="cursor-pointer" onClick={open(h.id, h.name)} role="button" aria-label={h.name}>
                <circle
                  cx={x}
                  cy={y}
                  r={h.mine ? 10 : 8}
                  fill="var(--tf-accent)"
                  fillOpacity={h.down ? 0.35 : 1}
                  stroke={h.mine ? "var(--color-ink, #ddd)" : "none"}
                  strokeWidth={1.5}
                />
                <text x={x} y={y + 4} textAnchor="middle" fontSize={9} fill="var(--color-bg, #111)">
                  ★
                </text>
                <text x={x} y={y + 21} textAnchor="middle" fontSize={10} fill="var(--color-ink, #ddd)">
                  {short(h.name, 14)}
                </text>
                <Badges x={x} y={y} elevation={h.elevation} cover={h.cover} />
              </g>
            ))}
          </>
        )}

        {exits.map(({ item: x, x: px, y: py }) => (
          <g key={x.id} className="cursor-pointer" onClick={open(x.id, x.name)} role="button" aria-label={`Выход: ${x.name}`}>
            <line x1={200 + (px - 200) * 0.9} y1={200 + (py - 200) * 0.9} x2={px} y2={py} stroke={TYPE_COLOR.location} strokeWidth={2} />
            <circle cx={px} cy={py} r={9} fill="var(--color-surface, #222)" stroke={TYPE_COLOR.location} strokeWidth={2} strokeDasharray={x.visited ? undefined : "3 3"} />
            <text x={px} y={py + 4} textAnchor="middle" fontSize={10} fill={TYPE_COLOR.location}>
              {TYPE_ICON.location}
            </text>
            <text x={px} y={py > 200 ? py - 13 : py + 21} textAnchor="middle" fontSize={10} fill="var(--color-ink, #ddd)">
              {short(x.name, 18)}
            </text>
          </g>
        ))}

        {things.map(({ item: t, x, y }) => (
          <g key={t.id} className="cursor-pointer" onClick={open(t.id, t.name)} role="button" aria-label={t.name}>
            <circle cx={x} cy={y} r={9} fill={TYPE_COLOR[t.type]} fillOpacity={t.condition === "мёртв" ? 0.3 : 0.9} />
            <text x={x} y={y + 4} textAnchor="middle" fontSize={10} fill="var(--color-bg, #111)">
              {TYPE_ICON[t.type]}
            </text>
            <text x={x} y={y + 21} textAnchor="middle" fontSize={10} fill="var(--color-ink, #ddd)">
              {short(t.name, 16)}
            </text>
            <Badges x={x} y={y} elevation={t.elevation} cover={t.cover} />
          </g>
        ))}
      </svg>
      {combat && (
        <p className="text-center font-mono text-[11px] text-muted">
          Бой: ▲ на возвышении, ▼ внизу, ◧ за укрытием (+2 или +5 к КД), ■ полное укрытие. Кольца не в масштабе.
        </p>
      )}

      {m.around.length === 0 && m.exits.length === 0 && (
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
          ) : tab === "around" ? (
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
