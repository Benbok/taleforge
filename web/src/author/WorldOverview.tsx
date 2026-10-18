import { useMemo, useState } from "react";
import type { WorldOverview as Overview } from "../lib/api.gen";

// Схема всего мира: места — блоки с участками, внутри — проходы между участками, между местами —
// маршруты от конкретного участка к конкретному участку. Координаты условные: это схема связей, а не карта.

const W = 250;
const GAP_X = 110;
const GAP_Y = 70;
const HEAD = 40;
const ROW = 34;
const ROW_GAP = 10;
const PAD = 14;
const COLS = 3;

type Box = { x: number; y: number; h: number };
type Pick = { kind: "area"; loc: string; area: string } | { kind: "route"; ref: string } | null;

function areaY(box: Box, index: number) {
  return box.y + HEAD + index * (ROW + ROW_GAP) + ROW / 2;
}

export default function WorldOverview({ overview }: { overview: Overview }) {
  const [pick, setPick] = useState<Pick>(null);
  const locations = overview.locations ?? [];
  const routes = overview.routes ?? [];

  const layout = useMemo(() => {
    const boxes: Record<string, Box> = {};
    const cols = Math.min(COLS, Math.max(locations.length, 1));
    let y = 20;
    for (let row = 0; row * cols < locations.length; row++) {
      const slice = locations.slice(row * cols, row * cols + cols);
      const heights = slice.map((l) => HEAD + Math.max((l.areas ?? []).length, 1) * (ROW + ROW_GAP) + PAD);
      slice.forEach((l, i) => {
        boxes[l.ref] = { x: 60 + i * (W + GAP_X), y, h: heights[i] };
      });
      y += Math.max(...heights) + GAP_Y;
    }
    return { boxes, width: 60 + cols * (W + GAP_X), height: y };
  }, [locations]);

  const anchor = (loc: string, area: string | null | undefined) => {
    const box = layout.boxes[loc];
    if (!box) return null;
    const areas = locations.find((l) => l.ref === loc)?.areas ?? [];
    const i = area ? areas.findIndex((a) => a.area_ref === area) : -1;
    return { box, y: i >= 0 ? areaY(box, i) : box.y + HEAD / 2 };
  };

  const routePath = (r: (typeof routes)[number]) => {
    const a = anchor(r.from_ref, r.from_area);
    const b = anchor(r.to_ref, r.to_area);
    if (!a || !b) return null;
    const rightward = b.box.x >= a.box.x + W / 2;
    const leftward = b.box.x + W / 2 <= a.box.x;
    const sx = rightward ? a.box.x + W : leftward ? a.box.x : a.box.x + W;
    const ex = rightward ? b.box.x : leftward ? b.box.x + W : b.box.x + W;
    const bulge = !rightward && !leftward ? 70 : Math.max(40, Math.abs(ex - sx) / 2.5);
    const c1 = rightward ? sx + bulge : leftward ? sx - bulge : sx + bulge;
    const c2 = rightward ? ex - bulge : leftward ? ex + bulge : ex + bulge;
    return `M ${sx} ${a.y} C ${c1} ${a.y}, ${c2} ${b.y}, ${ex} ${b.y}`;
  };

  const areaName = (loc: string, area?: string | null) => {
    const l = locations.find((x) => x.ref === loc);
    const a = l?.areas?.find((x) => x.area_ref === area);
    return `${l?.name ?? loc}${a ? ` · ${a.name}` : ""}`;
  };

  const picked = useMemo(() => {
    if (!pick) return null;
    if (pick.kind === "route") return { route: routes.find((r) => r.ref === pick.ref) };
    const loc = locations.find((l) => l.ref === pick.loc);
    const area = loc?.areas?.find((a) => a.area_ref === pick.area);
    const inner = (loc?.passages ?? []).filter((p) => p.from_area === pick.area || p.to_area === pick.area);
    const outer = routes.filter((r) => (r.from_ref === pick.loc && r.from_area === pick.area) || (r.to_ref === pick.loc && r.to_area === pick.area));
    return { loc, area, inner, outer };
  }, [pick, locations, routes]);

  const isPicked = (loc: string, area: string) => pick?.kind === "area" && pick.loc === loc && pick.area === area;
  const routeLit = (r: (typeof routes)[number]) =>
    (pick?.kind === "route" && pick.ref === r.ref) ||
    (pick?.kind === "area" && ((r.from_ref === pick.loc && r.from_area === pick.area) || (r.to_ref === pick.loc && r.to_area === pick.area)));

  if (!locations.length) return <p className="text-sm text-muted">Мест ещё нет: схема появится после шага «Места, NPC и предметы».</p>;

  return (
    <section aria-label="Схема мира" className="flex flex-col gap-3">
      <div className="overflow-x-auto rounded-xl border border-line bg-surface">
        <svg role="img" aria-label="Схема мест, участков и переходов" viewBox={`0 0 ${layout.width} ${layout.height}`} className="block min-w-[720px] w-full" style={{ fontFamily: "inherit" }}>
          <defs>
            <marker id="ov-arrow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse">
              <path d="M 0 0 L 10 5 L 0 10 z" fill="var(--tf-accent)" />
            </marker>
          </defs>
          {locations.map((loc) => {
            const box = layout.boxes[loc.ref];
            const areas = loc.areas ?? [];
            const region = loc.region ? overview.regions?.[loc.region] ?? loc.region : null;
            return (
              <g key={loc.ref} data-location={loc.ref}>
                <rect x={box.x} y={box.y} width={W} height={box.h} rx={14} fill="var(--tf-raised)" stroke="var(--tf-border)" strokeWidth={1.5} />
                <text x={box.x + 16} y={box.y + 24} fontSize={15} fontWeight={600} fill="var(--tf-text)">{loc.name}</text>
                {region && <text x={box.x + W - 14} y={box.y + 24} fontSize={11} textAnchor="end" fill="var(--tf-muted)">{region}</text>}
                {(loc.passages ?? []).map((p, i) => {
                  const a = areas.findIndex((x) => x.area_ref === p.from_area);
                  const b = areas.findIndex((x) => x.area_ref === p.to_area);
                  if (a < 0 || b < 0) return null;
                  const ya = areaY(box, a);
                  const yb = areaY(box, b);
                  const depth = 10 + Math.abs(b - a) * 6;
                  return (
                    <path
                      key={`${p.from_area}-${p.to_area}-${i}`}
                      d={`M ${box.x + 18} ${ya} C ${box.x + 18 - depth} ${ya}, ${box.x + 18 - depth} ${yb}, ${box.x + 18} ${yb}`}
                      fill="none"
                      stroke="var(--tf-muted)"
                      strokeWidth={1.5}
                      strokeDasharray={p.hidden ? "4 4" : undefined}
                    >
                      <title>{`${p.name || "проход"}${p.hidden ? " (тайный)" : ""}`}</title>
                    </path>
                  );
                })}
                {areas.map((area, i) => {
                  const y = areaY(box, i) - ROW / 2;
                  const lit = isPicked(loc.ref, area.area_ref);
                  const people = (area.npcs ?? []).length;
                  const things = (area.items ?? []).length;
                  return (
                    <g
                      key={area.area_ref}
                      role="button"
                      tabIndex={0}
                      aria-label={`${loc.name}: ${area.name}`}
                      className="cursor-pointer focus:outline-none"
                      onClick={() => setPick({ kind: "area", loc: loc.ref, area: area.area_ref })}
                      onKeyDown={(e) => (e.key === "Enter" || e.key === " ") && setPick({ kind: "area", loc: loc.ref, area: area.area_ref })}
                    >
                      <rect
                        x={box.x + 18}
                        y={y}
                        width={W - 36}
                        height={ROW}
                        rx={8}
                        fill={lit ? "var(--tf-accent)" : "var(--tf-surface)"}
                        stroke={area.entry ? "var(--tf-patina)" : "var(--tf-border)"}
                        strokeWidth={area.entry ? 2 : 1}
                        strokeDasharray={area.secret ? "5 3" : undefined}
                      />
                      <text x={box.x + 30} y={y + ROW / 2 + 4} fontSize={12.5} fill={lit ? "var(--tf-accent-text)" : "var(--tf-text)"}>
                        {area.name.length > 22 ? `${area.name.slice(0, 21)}…` : area.name}
                      </text>
                      {(people > 0 || things > 0) && (
                        <text x={box.x + W - 28} y={y + ROW / 2 + 4} fontSize={11} textAnchor="end" fill={lit ? "var(--tf-accent-text)" : "var(--tf-muted)"}>
                          {[people ? `👤${people}` : "", things ? `◆${things}` : ""].filter(Boolean).join(" ")}
                        </text>
                      )}
                    </g>
                  );
                })}
              </g>
            );
          })}
          {routes.map((r) => {
            const d = routePath(r);
            if (!d) return null;
            const lit = routeLit(r);
            return (
              <path
                key={r.ref}
                d={d}
                fill="none"
                stroke="var(--tf-accent)"
                strokeOpacity={pick && !lit ? 0.25 : 1}
                strokeWidth={lit ? 3.5 : 2.25}
                strokeDasharray={r.hidden ? "7 5" : undefined}
                markerEnd={r.bidirectional ? undefined : "url(#ov-arrow)"}
                className="cursor-pointer"
                onClick={() => setPick({ kind: "route", ref: r.ref })}
              >
                <title>{`${areaName(r.from_ref, r.from_area)} ${r.bidirectional ? "↔" : "→"} ${areaName(r.to_ref, r.to_area)}${r.hidden ? " (тайный)" : ""}`}</title>
              </path>
            );
          })}
        </svg>
      </div>
      <ul className="flex flex-wrap gap-x-5 gap-y-1 text-xs text-muted" aria-label="Обозначения">
        <li><span className="text-accent">━</span> маршрут между местами, стрелка — только в одну сторону</li>
        <li><span className="text-accent">╍</span> тайный маршрут</li>
        <li>изгиб слева от участков — проход внутри места</li>
        <li><span className="text-patina">▢</span> вход в место</li>
        <li>пунктирный участок — тайный</li>
        <li>👤 NPC, ◆ ключевые предметы и улики</li>
      </ul>
      {picked && (
        <div className="rounded-xl border border-line bg-raised p-3 text-sm" aria-label="Подробности" role="region">
          {"route" in picked && picked.route ? (
            <p>
              <span className="font-medium">Маршрут:</span> {areaName(picked.route.from_ref, picked.route.from_area)} {picked.route.bidirectional ? "↔" : "→"}{" "}
              {areaName(picked.route.to_ref, picked.route.to_area)}
              {picked.route.hidden ? ", тайный" : ""}
            </p>
          ) : "area" in picked && picked.area ? (
            <div className="flex flex-col gap-1">
              <p className="font-heading text-base text-ink">{picked.loc?.name} · {picked.area.name}</p>
              <p className="text-muted">{[picked.area.entry ? "вход в место" : "", picked.area.secret ? "тайный участок" : ""].filter(Boolean).join(", ") || "обычный участок"}</p>
              <p><span className="font-medium">NPC:</span> {(picked.area.npcs ?? []).join(", ") || "никого"}</p>
              <p><span className="font-medium">Предметы и улики:</span> {(picked.area.items ?? []).join(", ") || "нет"}</p>
              <p>
                <span className="font-medium">Проходы внутри места:</span>{" "}
                {picked.inner?.length
                  ? picked.inner.map((p) => `${p.name || "проход"} → ${picked.loc?.areas?.find((a) => a.area_ref === (p.from_area === picked.area?.area_ref ? p.to_area : p.from_area))?.name ?? "наружу"}`).join("; ")
                  : "нет"}
              </p>
              <p>
                <span className="font-medium">Маршруты:</span>{" "}
                {picked.outer?.length
                  ? picked.outer.map((r) => (r.from_ref === picked.loc?.ref && r.from_area === picked.area?.area_ref ? `→ ${areaName(r.to_ref, r.to_area)}` : `${r.bidirectional ? "↔" : "←"} ${areaName(r.from_ref, r.from_area)}`)).join("; ")
                  : "нет"}
              </p>
            </div>
          ) : null}
        </div>
      )}
    </section>
  );
}
