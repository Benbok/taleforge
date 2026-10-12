import { useEffect, useMemo, useState } from "react";
import { knownBounds, mechanicalToPlan, planToMechanical } from "./locationGeometry";
import { SketchSurface, terrainCells } from "./SketchSurface";
import { useMapWindow, type Cell, type MapLocationPlan, type MapState, type SceneTokenView, type SketchExit } from "./map";
import { MapGlyph } from "./MapGlyph";
import { entityVisual } from "./mapPresets";
import { useMapZoom, ZoomBar } from "./MapZoom";
import { PassageBar } from "./PassageBar";
import { useDraft } from "./draft";
import { useInspector } from "./inspector";

export interface LocationMapSvgProps {
  map: MapLocationPlan;
  liveSketch?: MapLocationPlan["areas"][number]["sketch"] | null;
  tokens?: Cell<SceneTokenView>[];
  activeLevel?: number;
  idPrefix: string;
  onCell?: (areaId: string, cell: [number, number]) => void;
  onPassage?: (exit: SketchExit, areaId: string) => void;
  onEntity?: (id: string, name: string) => void;
}

export function LocationMapSvg({ map, liveSketch, tokens = [], activeLevel, idPrefix, onPassage, onCell, onEntity }: LocationMapSvgProps) {
  const level = activeLevel ?? map.areas.find((area) => area.status === "here")?.level ?? 0;
  const areas = map.areas.filter((area) => area.level === level);
  const bounds = knownBounds(map, level);
  const current = areas.find((area) => area.id === map.here_id && area.status === "here");
  return (
    <svg viewBox={bounds ? `${bounds.minX} ${bounds.minY} ${bounds.maxX - bounds.minX} ${bounds.maxY - bounds.minY}` : "0 0 1 1"} data-location-map={map.root_id}>
      {areas.map((area) => (
        <g key={area.id} data-area-id={area.id} data-area-status={area.status} opacity={area.status === "remembered" ? .45 : 1} transform={`translate(${area.offset[0]} ${area.offset[1]})`}>
          <SketchSurface sketch={area.id === map.here_id ? liveSketch ?? area.sketch : area.sketch} areaId={area.id} idPrefix={`${idPrefix}-${area.id}`} onPassage={area.id === map.here_id && area.status === "here" ? (exit) => onPassage?.(exit, area.id) : undefined} />
          <text x=".25" y=".65" fontSize=".4" fill="var(--tf-ink, #eee)">{area.name}</text>
          {area.id === map.here_id && onCell && Array.from({ length: area.sketch.rows }, (_, y) =>
            Array.from({ length: area.sketch.cols }, (_, x) => (!area.sketch.mask || area.sketch.mask[y]?.[x] === ".") && <rect key={`${x},${y}`} x={x + .1} y={y + .1} width=".8" height=".8" fill="transparent" onClick={() => onCell(area.id, [area.offset[0] + x, area.offset[1] + y])} />))}
          {area.id === map.here_id && onEntity && (liveSketch?.features ?? []).filter((feature) => feature.entity_id).flatMap((feature) =>
            terrainCells(feature.cells).map(([x, y], index) => <rect key={`${feature.entity_id}-${index}`} x={x} y={y} width="1" height="1" fill="transparent" onClick={() => onEntity(feature.entity_id!, feature.name)} />))}
        </g>
      ))}
      {current && tokens.map(({ item, col, row }) => {
        const [x, y] = mechanicalToPlan(current, [col, row], liveSketch?.party ?? current.sketch.party);
        const visual = entityVisual(item.type, item.visual_key);
        return <g key={item.id} data-token-id={item.id} transform={`translate(${x + .15} ${y + .15})`} onClick={onEntity ? () => onEntity(item.id, item.name) : undefined}>
          <MapGlyph name={visual.glyph} width={.7} height={.7} color={visual.color} />
          <title>{item.name}</title>
        </g>;
      })}
    </svg>
  );
}

export interface LocationMapProps {
  map: MapLocationPlan;
  m?: MapState;
  activeLevel?: number;
  idPrefix?: string;
}

export function LocationMap({ map, m, activeLevel, idPrefix = "location-map" }: LocationMapProps) {
  const levels = useMemo(() => [...new Set(map.areas.map((area) => area.level))].sort((a, b) => a - b), [map.areas]);
  const initial = activeLevel ?? map.areas.find((area) => area.status === "here")?.level ?? levels[0] ?? 0;
  const [level, setLevel] = useState(initial);
  const [picked, setPicked] = useState<SketchExit | null>(null);
  const z = useMapZoom();
  const { traverse, traverseTo, stepTo, step } = useMapWindow();
  const insert = useDraft((state) => state.insert);
  const inspect = useInspector((state) => state.open);
  useEffect(() => { setLevel(initial); setPicked(null); }, [map.root_id, map.here_id, initial]);
  const current = map.areas.find((area) => area.id === map.here_id);
  // механические клетки считаются от живого строя: так же их рисует LocationMapSvg для токенов
  const party = m?.sketch?.party ?? current?.sketch.party ?? [0, 0];
  return (
    <section aria-label="Карта комплекса">
      {levels.length > 1 && <div role="group" aria-label="Уровни">
        {levels.map((item) => <button key={item} type="button" aria-label={`Уровень ${item}`} aria-pressed={item === level} onClick={() => setLevel(item)}>{item}</button>)}
      </div>}
      <ZoomBar z={z} />
      <div ref={z.box} {...z.pan} className="max-h-[65vh] overflow-auto">
        <div style={{ width: `${z.zoom * 100}%`, minWidth: "100%" }}>
          <LocationMapSvg map={map} liveSketch={m?.sketch} tokens={m ? locationTokens(m) : []} activeLevel={level} idPrefix={idPrefix}
            onCell={m && current ? (_, cell) => stepTo({ cell: planToMechanical(current, party, cell) }) : undefined}
            onEntity={m ? (id, name) => inspect(id, name) : undefined}
            onPassage={m ? (exit) => setPicked(exit) : undefined} />
        </div>
      </div>
      {picked && current && <PassageBar exit={picked} pending={traverse.busy} canAct={!step.busy}
        destination={map.areas.find((area) => area.id === picked.to)?.name}
        onApproach={() => stepTo({ near: (picked.cells ?? []).map(([x, y]) => [x - party[0], y - party[1]]) })}
        onTraverse={() => picked.passage_ref && traverseTo(picked.passage_ref, current.id)}
        onInteract={() => insert(`Взаимодействую с «${picked.name}».`)} />}
      {(traverse.error || traverse.reason || step.error || step.note) && <p role="status">{traverse.error ?? traverse.reason ?? step.error ?? step.note}</p>}
    </section>
  );
}

export function locationTokens(map: MapState): Cell<SceneTokenView>[] {
  return (map.scene_view ?? []).filter((token) => token.cell).map((token) => ({ item: token, col: token.cell![0], row: token.cell![1], placement: "mechanical" as const }));
}
