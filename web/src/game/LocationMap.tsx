import { useMemo, useState } from "react";
import { knownBounds } from "./locationGeometry";
import { SketchSurface } from "./SketchSurface";
import type { Cell, MapLocationPlan, MapState, SceneTokenView, SketchExit } from "./map";

export interface LocationMapSvgProps {
  map: MapLocationPlan;
  liveSketch?: MapLocationPlan["areas"][number]["sketch"] | null;
  tokens?: Cell<SceneTokenView>[];
  activeLevel?: number;
  idPrefix: string;
  onCell?: (areaId: string, cell: [number, number]) => void;
  onPassage?: (exit: SketchExit, areaId: string) => void;
}

export function LocationMapSvg({ map, activeLevel, idPrefix, onPassage }: LocationMapSvgProps) {
  const level = activeLevel ?? map.areas.find((area) => area.status === "here")?.level ?? 0;
  const areas = map.areas.filter((area) => area.level === level);
  const bounds = knownBounds(map, level);
  return (
    <svg viewBox={bounds ? `${bounds.minX} ${bounds.minY} ${bounds.maxX - bounds.minX} ${bounds.maxY - bounds.minY}` : "0 0 1 1"} data-location-map={map.root_id}>
      {areas.map((area) => (
        <g key={area.id} data-area-id={area.id} data-area-status={area.status} transform={`translate(${area.offset[0]} ${area.offset[1]})`}>
          <SketchSurface sketch={area.sketch} areaId={area.id} idPrefix={`${idPrefix}-${area.id}`} onPassage={(exit) => onPassage?.(exit, area.id)} />
        </g>
      ))}
    </svg>
  );
}

export interface LocationMapProps {
  map: MapLocationPlan;
  activeLevel?: number;
  idPrefix?: string;
}

export function LocationMap({ map, activeLevel, idPrefix = "location-map" }: LocationMapProps) {
  const levels = useMemo(() => [...new Set(map.areas.map((area) => area.level))].sort((a, b) => a - b), [map.areas]);
  const initial = activeLevel ?? map.areas.find((area) => area.status === "here")?.level ?? levels[0] ?? 0;
  const [level, setLevel] = useState(initial);
  return (
    <section aria-label="Карта комплекса">
      {levels.length > 1 && <div role="group" aria-label="Уровни">
        {levels.map((item) => <button key={item} type="button" aria-label={`Уровень ${item}`} aria-pressed={item === level} onClick={() => setLevel(item)}>{item}</button>)}
      </div>}
      <LocationMapSvg map={map} activeLevel={level} idPrefix={idPrefix} />
    </section>
  );
}

export function locationTokens(map: MapState): Cell<SceneTokenView>[] {
  return (map.scene_view ?? []).filter((token) => token.cell).map((token) => ({ item: token, col: token.cell![0], row: token.cell![1], placement: "mechanical" as const }));
}
