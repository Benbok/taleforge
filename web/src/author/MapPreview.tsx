import { useState } from "react";
import { LocationMapSvg } from "../game/LocationMap";
import type { AuthorMapOut } from "../lib/api.gen";
import { planOfArea } from "../lib/authoring";

export interface AuthorMapPreviewProps {
  map: AuthorMapOut;
  onSelect?(areaRef: string): void;
  /** Пересборка только этой карты; без неё кнопки нет (например, в просмотре географии). */
  rebuild?: { disabled: boolean; running: boolean; onRebuild(): void };
}

/** Просмотр подготовленной карты. Данные приходят props'ами: никаких сокет-команд, героя и знаний игрока. */
export default function MapPreview({ map, onSelect, rebuild }: AuthorMapPreviewProps) {
  const [areaRef, setAreaRef] = useState(map.areas[0]?.area_ref ?? "");
  const plan = planOfArea(map, areaRef);
  const ports = map.areas.find((a) => a.area_ref === areaRef)?.ports ?? {};
  if (!map.areas.length) return <p className="text-sm text-muted">Карта этой локации ещё не готова.</p>;
  return (
    <section aria-label={`Карта: ${map.name}`} className="flex flex-col gap-3">
      <div className="flex flex-wrap items-baseline gap-3">
        <h3 className="font-heading text-lg text-ink">{map.name}</h3>
        <span className="text-sm text-muted">участков: {map.areas.length}</span>
        {map.layout_quality === "normal" && <span className="text-sm text-ok">планировку придумала модель</span>}
        {map.layout_quality === "fallback" && <span className="text-sm text-warn">запасная планировка по шаблону: модель не ответила</span>}
        {rebuild && (
          <button className="btn ml-auto min-h-11 px-3 text-sm" type="button" disabled={rebuild.disabled || rebuild.running} onClick={rebuild.onRebuild}>
            {rebuild.running ? "Пересобираю эту карту…" : "Пересобрать эту карту"}
          </button>
        )}
      </div>
      <div className="flex flex-wrap gap-2" role="group" aria-label="Участки">
        {map.areas.map((area) => (
          <button
            key={area.area_ref}
            type="button"
            className={`btn min-h-11 px-3 text-sm ${area.area_ref === areaRef ? "btn-primary" : ""}`}
            aria-pressed={area.area_ref === areaRef}
            onClick={() => {
              setAreaRef(area.area_ref);
              onSelect?.(area.area_ref);
            }}
          >
            {area.name}
          </button>
        ))}
      </div>
      {plan && (
        <div className="rounded-xl border border-line bg-raised p-2">
          <LocationMapSvg map={plan} idPrefix={`author-${map.location_ref}-${areaRef}`} />
        </div>
      )}
      {Object.keys(ports).length > 0 && (
        <ul className="text-sm text-muted" aria-label="Порты маршрутов">
          {Object.entries(ports).map(([route, port]) => (
            <li key={route}>
              {route}: {JSON.stringify((port as { cells?: unknown }).cells ?? [])}
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
