import { useEffect, type MouseEvent } from "react";
import { TYPE_COLOR, TYPE_ICON } from "./entities";
import { useInspector } from "./inspector";
import { EDGE, layoutPlaces, placeAround, RING, useMapWindow, type MapExit, type MapState, type MapThing } from "./map";

const ZONES: [keyof typeof RING, string][] = [
  ["melee", "вплотную"],
  ["near", "близко"],
  ["far", "далеко"],
];

function short(s: string, n: number): string {
  return s.length > n ? `${s.slice(0, n - 1)}…` : s;
}

/** Открыть карточку по маркеру: для SVG якорь — сам маркер, у него есть рамка на экране. */
function useOpen() {
  const open = useInspector((s) => s.open);
  return (id: string, name: string) => (e: MouseEvent<Element>) => open(id, name, e.currentTarget as unknown as HTMLElement);
}

function Around({ m }: { m: MapState }) {
  const open = useOpen();
  const things = placeAround<MapThing>(m.around, (t) => RING[t.zone] ?? RING.near);
  const exits = placeAround<MapExit>(m.exits, () => EDGE);

  return (
    <div className="flex flex-col gap-3">
      {m.here?.description && <p className="font-narration text-sm leading-relaxed text-ink-2">{m.here.description}</p>}
      <svg viewBox="-50 -10 500 420" className="mx-auto w-full max-w-[30rem] select-none" role="img" aria-label="Схема места">
        {ZONES.map(([z, name]) => (
          <g key={z}>
            <circle cx={200} cy={200} r={RING[z]} fill="none" stroke="var(--color-muted, #888)" strokeOpacity={0.45} strokeDasharray="3 5" />
            <text x={200 - RING[z] * 0.34 - 4} y={200 + RING[z] * 0.94 - 4} textAnchor="end" fontSize={9} fill="var(--color-muted, #888)">
              {name}
            </text>
          </g>
        ))}
        <text x={200} y={4} textAnchor="middle" fontSize={10} fill="var(--color-muted, #888)">
          С
        </text>
        <circle cx={200} cy={200} r={11} fill="var(--tf-accent)" />
        <text x={200} y={224} textAnchor="middle" fontSize={10} fill="var(--color-ink, #ddd)">
          отряд
        </text>

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
          </g>
        ))}
      </svg>

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
                  {t.bearing && <span className="text-muted"> ({m.bearings[t.bearing]})</span>}
                  {t.condition && t.condition !== "невредим" && <span className="text-muted"> · {t.condition}</span>}
                </span>
              ))}
            </li>
          );
        })}
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
      <div className="overflow-x-auto">
        <svg viewBox={`0 0 ${width} ${height}`} width={width} height={height} className="select-none" role="img" aria-label="Карта мест">
          {m.places
            .filter((p) => p.parent_id && pos.has(p.parent_id))
            .map((p) => (
              <line key={`p${p.id}`} {...edge(p.id, p.parent_id!)} stroke="var(--color-muted, #888)" strokeDasharray="2 4" />
            ))}
          {m.links.map((l) => {
            const e = edge(l.a, l.b);
            return (
              <g key={`${l.a}-${l.b}`}>
                <line {...e} stroke={TYPE_COLOR.location} strokeWidth={1.5} strokeOpacity={0.7} />
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
              <g key={p.id} className="cursor-pointer" onClick={open(p.id, p.name)} role="button" aria-label={p.name}>
                <rect
                  x={x}
                  y={y}
                  width={W}
                  height={H}
                  rx={6}
                  fill={here ? "var(--tf-accent)" : "var(--color-surface, #222)"}
                  fillOpacity={here ? 0.35 : 1}
                  stroke={here ? "var(--tf-accent)" : TYPE_COLOR.location}
                  strokeDasharray={p.status === "known" ? "4 4" : undefined}
                />
                <text x={x + W / 2} y={y + 20} textAnchor="middle" fontSize={11} fill={p.status === "known" ? "var(--color-muted, #888)" : "var(--color-ink, #ddd)"}>
                  {short(p.name, 22)}
                </text>
                {here && (
                  <text x={x + W / 2} y={y + H + 12} textAnchor="middle" fontSize={9} fill="var(--tf-accent)">
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
