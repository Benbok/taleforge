import { useState } from "react";

interface Location {
  id: string;
  name: string;
  region?: string | null;
}
interface Region {
  id: string;
  name: string;
  parent?: string | null;
}
interface Route {
  ref: string;
  from: string;
  to: string;
  bidirectional?: boolean;
  hidden?: boolean;
}

interface Props {
  regions: Region[];
  locations: Location[];
  routes: Route[];
  selected: string | null;
  onSelect(locationRef: string): void;
}

/** Детерминированный список «регион → локация» с маршрутами между конкретными участками, без глобальных координат. */
export default function GeographyView({ regions, locations, routes, selected, onSelect }: Props) {
  const [route, setRoute] = useState<string | null>(null);
  const byRegion = new Map<string, Location[]>();
  for (const loc of locations) byRegion.set(loc.region ?? "", [...(byRegion.get(loc.region ?? "") ?? []), loc]);
  const nameOf = (endpoint: string) => {
    const [node, area] = endpoint.split("/");
    return `${locations.find((l) => l.id === node)?.name ?? node}${area ? ` · ${area}` : ""}`;
  };
  const picked = routes.find((r) => r.ref === route);
  return (
    <section aria-label="География" className="flex flex-col gap-3">
      {[...regions.map((r) => ({ id: r.id, name: r.name })), { id: "", name: "Без региона" }].map((region) => {
        const items = byRegion.get(region.id) ?? [];
        if (!items.length) return null;
        return (
          <div key={region.id || "none"}>
            <h3 className="font-heading text-sm text-muted">{region.name}</h3>
            <ul className="mt-1 flex flex-wrap gap-2">
              {items.map((loc) => (
                <li key={loc.id}>
                  <button type="button" className={`btn min-h-11 px-3 text-sm ${selected === loc.id ? "btn-primary" : ""}`} aria-pressed={selected === loc.id} onClick={() => onSelect(loc.id)}>
                    {loc.name}
                  </button>
                </li>
              ))}
            </ul>
          </div>
        );
      })}
      {routes.length > 0 && (
        <div>
          <h3 className="font-heading text-sm text-muted">Маршруты</h3>
          <ul className="mt-1 flex flex-col gap-1">
            {routes.map((r) => (
              <li key={r.ref}>
                <button type="button" className="text-left text-sm text-ink underline-offset-2 hover:underline" onClick={() => setRoute(r.ref)}>
                  {nameOf(r.from)} {r.bidirectional === false ? "→" : "↔"} {nameOf(r.to)}
                </button>
              </li>
            ))}
          </ul>
          {picked && (
            <dl className="mt-2 rounded-lg border border-line bg-raised p-3 text-sm" aria-label="Маршрут">
              <dt className="text-muted">Выход</dt>
              <dd>{nameOf(picked.from)}</dd>
              <dt className="text-muted">Вход</dt>
              <dd>{nameOf(picked.to)}</dd>
              <dt className="text-muted">Направление</dt>
              <dd>{picked.bidirectional === false ? "в одну сторону" : "в обе стороны"}{picked.hidden ? ", скрытый" : ""}</dd>
            </dl>
          )}
        </div>
      )}
    </section>
  );
}
