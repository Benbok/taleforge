import { useEffect, useMemo, useRef, useState } from "react";
import { knownBounds, mechanicalToPlan, overviewBounds, planToMechanical } from "./locationGeometry";
import { SketchSurface, terrainCells } from "./SketchSurface";
import { useMapWindow, type Cell, type MapLocationPlan, type MapState, type SceneTokenView, type SketchExit } from "./map";
import { MapGlyph } from "./MapGlyph";
import { entityVisual } from "./mapPresets";
import { useMapZoom, ZoomBar } from "./MapZoom";
import { PassageBar } from "./PassageBar";
import { BackdropLayer } from "./MapBackdrop";
import { useDraft } from "./draft";
import { useInspector } from "./inspector";

export interface LocationMapSvgProps {
  map: MapLocationPlan;
  liveSketch?: MapLocationPlan["areas"][number]["sketch"] | null;
  tokens?: Cell<SceneTokenView>[];
  activeLevel?: number;
  idPrefix: string;
  pickedExit?: SketchExit | null;
  pickedPassageRef?: string | null;
  showPassageLabels?: boolean;
  backdrop?: { areaId: string; url: string } | null;
  onCell?: (areaId: string, cell: [number, number]) => void;
  onPassage?: (exit: SketchExit, areaId: string) => void;
  onEntity?: (id: string, name: string, anchor: Element) => void;
}

export function LocationMapSvg({ map, liveSketch, tokens = [], activeLevel, idPrefix, pickedExit, pickedPassageRef, showPassageLabels=false, backdrop, onPassage, onCell, onEntity }: LocationMapSvgProps) {
  const level = activeLevel ?? map.areas.find((area) => area.status === "here")?.level ?? 0;
  const areas = map.areas.filter((area) => area.level === level);
  const bounds = overviewBounds(knownBounds(map, level));
  const current = areas.find((area) => area.id === map.here_id && area.status === "here");
  // Рендерим текущую комнату последней, чтобы её выходы всегда были поверх смежных участков
  const sortedAreas = useMemo(() => {
    return [...areas].sort((a, b) => {
      const aIsCurrent = a.id === map.here_id || a.status === "here";
      const bIsCurrent = b.id === map.here_id || b.status === "here";
      return (aIsCurrent ? 1 : 0) - (bIsCurrent ? 1 : 0);
    });
  }, [areas, map.here_id]);

  return (
    <svg role="img" aria-label="Карта известных участков локации" className="block w-full" viewBox={bounds ? `${bounds.minX} ${bounds.minY} ${bounds.maxX - bounds.minX} ${bounds.maxY - bounds.minY}` : "0 0 1 1"} data-location-map={map.root_id}>
      {sortedAreas.map((area) => {
        const isCurrent = area.id === map.here_id || area.status === "here";
        return (
          <g key={area.id} data-area-id={area.id} data-area-status={area.status} opacity={area.status === "prepared" ? .22 : area.status === "remembered" ? .45 : 1} transform={`translate(${area.offset[0]} ${area.offset[1]})`}>
            {backdrop?.areaId === area.id && <BackdropLayer url={backdrop.url} cols={area.sketch.cols} rows={area.sketch.rows} />}
            <SketchSurface
              floorOpacity={backdrop?.areaId === area.id ? .18 : 1}
              sketch={isCurrent ? liveSketch ?? area.sketch : area.sketch}
              areaId={area.id}
              idPrefix={`${idPrefix}-${area.id}`}
              showPassageLabels={showPassageLabels}
              pickedExit={isCurrent ? pickedExit : undefined}
              pickedPassageRef={isCurrent ? (pickedPassageRef ?? pickedExit?.passage_ref) : undefined}
              onPassage={isCurrent ? (exit) => onPassage?.(exit, area.id) : undefined}
            >
              {isCurrent && onCell && Array.from({ length: area.sketch.rows }, (_, y) =>
                Array.from({ length: area.sketch.cols }, (_, x) => (!area.sketch.mask || area.sketch.mask[y]?.[x] === ".") && (
                  <rect key={`${x},${y}`} x={x + .1} y={y + .1} width=".8" height=".8" fill="transparent" pointerEvents="all" onClick={() => onCell(area.id, [area.offset[0] + x, area.offset[1] + y])} />
                )))}
              {isCurrent && onEntity && (liveSketch?.features ?? []).filter((feature) => feature.entity_id).flatMap((feature) =>
                terrainCells(feature.cells).map(([x, y], index) => (
                  <rect key={`${feature.entity_id}-${index}`} x={x} y={y} width="1" height="1" fill="transparent" pointerEvents="all" onClick={(event) => onEntity(feature.entity_id!, feature.name, event.currentTarget)} />
                )))}
            </SketchSurface>
            <title>{area.name}</title>
          </g>
        );
      })}
      {current && !tokens.some(({ item }) => item.mine) && <g data-party-marker="true" pointerEvents="none" transform={`translate(${current.offset[0] + (liveSketch?.party ?? current.sketch.party)[0] + .5} ${current.offset[1] + (liveSketch?.party ?? current.sketch.party)[1] + .5})`}>
        <circle r=".38" fill="var(--tf-surface)" stroke="var(--tf-accent)" strokeWidth=".09" />
        <path d="M0 -.23 L.17 .19 L0 .1 L-.17 .19 Z" fill="var(--tf-accent)" />
        <title>Позиция отряда</title>
      </g>}
      {current && tokens.map(({ item, col, row }) => {
        const [x, y] = mechanicalToPlan(current, [col, row], liveSketch?.party ?? current.sketch.party);
        const visual = entityVisual(item.type, item.visual_key);
        return <g key={item.id} data-token-id={item.id} className={onEntity ? "cursor-pointer" : undefined} transform={`translate(${x + .15} ${y + .15})`} onClick={onEntity ? (event) => onEntity(item.id, item.name, event.currentTarget) : undefined}>
          {onEntity && <rect x={-.15} y={-.15} width="1" height="1" fill="transparent" pointerEvents="all" />}
          {item.mine && <circle cx=".35" cy=".35" r=".46" fill="var(--tf-surface)" stroke="var(--tf-accent)" strokeWidth=".09" pointerEvents="none" className="pointer-events-none" />}
          <MapGlyph name={visual.glyph} width={.7} height={.7} color={visual.color} pointerEvents="none" className="pointer-events-none" />
          <title>{item.name}{item.mine ? " — ваш герой" : item.companion_of ? " — спутник" : ""}</title>
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
  orientationOnly?: boolean;
  backdrop?: { areaId: string; url: string } | null;
}

export function LocationMap({ map, m, activeLevel, idPrefix = "location-map", orientationOnly = false, backdrop }: LocationMapProps) {
  const levels = useMemo(() => [...new Set(map.areas.map((area) => area.level))].sort((a, b) => a - b), [map.areas]);
  const initial = activeLevel ?? map.areas.find((area) => area.status === "here")?.level ?? levels[0] ?? 0;
  const [level, setLevel] = useState(initial);
  const [picked, setPicked] = useState<SketchExit | null>(null);
  const passageBarRef = useRef<HTMLDivElement>(null);
  const z = useMapZoom();
  const { traverse, traverseTo, stepTo, step } = useMapWindow();
  const insert = useDraft((state) => state.insert);
  const inspect = useInspector((state) => state.open);

  useEffect(() => { setLevel(initial); setPicked(null); }, [map.root_id, map.here_id, initial]);
  useEffect(() => {
    if (picked) {
      passageBarRef.current?.scrollIntoView?.({ behavior: "smooth", block: "nearest" });
    }
  }, [picked]);

  const current = map.areas.find((area) => area.id === map.here_id);
  useEffect(()=>{
    setPicked(previous=>previous ? current?.sketch.exits.find(e=>previous.passage_ref
      ? e.passage_ref===previous.passage_ref
      : e.name===previous.name&&e.side===previous.side&&e.at===previous.at)??null : null);
  },[current?.sketch]);
  // механические клетки считаются от живого строя: так же их рисует LocationMapSvg для токенов
  const party = m?.sketch?.party ?? current?.sketch.party ?? [0, 0];
  return (
    <section className="flex flex-col gap-3" aria-label="Карта комплекса">
      {levels.length > 1 && <div className="flex flex-wrap gap-2" role="group" aria-label="Уровни">
        {levels.map((item) => <button className={`btn min-h-11 px-3 text-sm ${item === level ? "btn-primary" : ""}`} key={item} type="button" aria-label={`Уровень ${item}`} aria-pressed={item === level} onClick={() => { setLevel(item); setPicked(null); }}>{item}</button>)}
      </div>}
      <ZoomBar z={z} />
      <div className="relative rounded-xl border border-line bg-raised">
        {current && (
          <div className="pointer-events-none absolute left-3 top-3 z-10">
            <div className="pointer-events-auto flex items-center gap-1.5 rounded-lg border border-line/80 bg-surface/90 px-2.5 py-1 shadow-sm backdrop-blur-sm">
              <span className="text-accent text-xs" aria-hidden="true">⌖</span>
              <button
                type="button"
                className="font-heading text-sm font-semibold text-ink hover:text-accent hover:underline transition text-left cursor-pointer"
                title="Открыть описание локации"
                onClick={(e) => inspect(current.id, current.name, e.currentTarget)}
              >
                {current.name}
              </button>
            </div>
          </div>
        )}
        <div ref={z.box} {...z.pan} className="max-h-[50dvh] overflow-auto p-2">
          <div style={{ width: `${z.zoom * 100}%`, minWidth: "100%" }}>
            <LocationMapSvg map={map} liveSketch={orientationOnly ? current?.sketch : m?.sketch} tokens={m ? locationTokens(m) : []} activeLevel={level} idPrefix={idPrefix} showPassageLabels={orientationOnly} backdrop={backdrop}
              pickedExit={picked} pickedPassageRef={picked?.passage_ref}
              onCell={!orientationOnly && m && current ? (_, cell) => stepTo({ cell: planToMechanical(current, party, cell) }) : undefined}
              onEntity={m ? (id, name, anchor) => inspect(id, name, anchor) : undefined}
              onPassage={(exit) => setPicked(exit)} />
          </div>
        </div>
      </div>
      <p className="text-xs leading-relaxed text-muted">Медная отметка — ваш герой или отряд. Приглушённые участки — ранее исследованные. Нажмите на проход, чтобы рассмотреть его.</p>
      {picked && current && (
        <div ref={passageBarRef}>
          <PassageBar exit={picked} pending={traverse.busy} canAct={!step.busy} readOnly={orientationOnly}
            onClose={() => setPicked(null)}
            destination={map.areas.find((area) => area.id === picked.to)?.name}
            onApproach={() => stepTo({ near: (picked.cells ?? []).map(([x, y]) => [x - party[0], y - party[1]]) })}
            onTraverse={() => picked.route_ref ? traverseTo("", current.id, picked.route_ref) : picked.passage_ref && traverseTo(picked.passage_ref, current.id)}
            onInteract={() => insert(`Взаимодействую с «${picked.name}».`)} />
        </div>
      )}
      {!orientationOnly && (traverse.error || traverse.reason || step.error || step.note) && <p className="rounded-lg border border-warn/40 bg-warn/10 p-3 text-sm text-ink" role={traverse.error || step.error ? "alert" : "status"}>{traverse.error ?? traverse.reason ?? step.error ?? step.note}</p>}
    </section>
  );
}

export function locationTokens(map: MapState): Cell<SceneTokenView>[] {
  return (map.scene_view ?? []).filter((token) => token.cell).map((token) => ({ item: token, col: token.cell![0], row: token.cell![1], placement: "mechanical" as const }));
}
