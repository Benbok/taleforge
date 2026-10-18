import type { ReactNode } from "react";
import { exitSegments, surfaceGeometry } from "./locationGeometry";
import type { MapKnownArea, Sketch, SketchExit } from "./map";
import { MapFeature } from "./MapFeature";
import { SketchMaterials } from "./SketchMaterials";

export interface SketchSurfaceProps {
  sketch: Sketch;
  areaId?: string;
  idPrefix: string;
  onPassage?: (exit: SketchExit) => void;
  onFeature?: (id: string, name: string) => void;
  pickedExit?: SketchExit | null;
  pickedPassageRef?: string | null;
  children?: ReactNode;
}

const MATERIALS = new Set(["stone", "earth", "grass", "water", "wood"]);

export function terrainCells(rects: number[][]): [number, number][] {
  return rects.flatMap(([x0, y0, x1 = x0, y1 = y0]) =>
    Array.from({ length: y1 - y0 + 1 }, (_, y) =>
      Array.from({ length: x1 - x0 + 1 }, (_, x) => [x0 + x, y0 + y] as [number, number])).flat());
}

export function SketchSurface({ sketch, areaId = "area", idPrefix, onPassage, onFeature, pickedExit, pickedPassageRef, children }: SketchSurfaceProps) {
  const area: MapKnownArea = { id: areaId, name: areaId, offset: [0, 0], level: 0, status: "here", revision: 0, sketch };
  const geometry = surfaceGeometry(area);
  const material = MATERIALS.has(sketch.material ?? "") ? sketch.material! : "stone";
  const clipId = `${idPrefix}-floor`;
  const decoratedWalls = new Set(sketch.features.filter((f) => f.solid && !f.hidden)
    .flatMap((f) => terrainCells(f.cells).map(([x, y]) => `${x},${y}`)));
  return (
    <g role="img" data-sketch-surface={areaId}>
      <defs>
        <SketchMaterials idPrefix={idPrefix} material={material} rough={sketch.shape === "cave"} />
        <clipPath id={clipId}>
          {geometry.floor.map(([x, y]) => <rect key={`${x},${y}`} x={x} y={y} width="1" height="1" />)}
        </clipPath>
      </defs>
      <rect width={sketch.cols} height={sketch.rows} fill={`url(#${idPrefix}-pattern-${material})`} clipPath={`url(#${clipId})`} />
      {(sketch.terrain ?? []).filter((t) => t.kind !== "bridge").map((terrain, i) => (
        <g key={`terrain-${i}`} data-terrain={terrain.kind} clipPath={`url(#${clipId})`}>
          {terrainCells(terrain.cells).map(([x, y], j) => <rect key={j} x={x} y={y} width="1" height="1" fill={`var(--tf-map-${terrain.kind}, ${terrain.kind === "stream" ? "#77a9c6" : "#b6a66a"})`} opacity=".65" />)}
        </g>
      ))}
      {(sketch.terrain ?? []).filter((t) => t.kind === "bridge").map((terrain, i) => (
        <g key={`bridge-${i}`} data-terrain="bridge" clipPath={`url(#${clipId})`}>
          {terrainCells(terrain.cells).map(([x, y], j) => <rect key={j} x={x} y={y} width="1" height="1" fill={`url(#${idPrefix}-bridge-planks)`} />)}
        </g>
      ))}
      <rect width={sketch.cols} height={sketch.rows} fill={`url(#${idPrefix}-tactical-grid)`} clipPath={`url(#${clipId})`} pointerEvents="none" />
      <g data-layer="contours">
        {geometry.contours.map((segment, i) => <g key={i}>
          {sketch.shape !== "open" && material !== "water" && <line x1={segment.from[0]} y1={segment.from[1]} x2={segment.to[0]} y2={segment.to[1]} stroke="#080c0e" opacity=".45" strokeWidth=".32" />}
          <line x1={segment.from[0]} y1={segment.from[1]} x2={segment.to[0]} y2={segment.to[1]} data-wall={sketch.shape === "open" || material === "water" ? undefined : "true"} stroke={material === "water" ? "var(--tf-map-water-mark, #67999e)" : "var(--tf-map-wall, #111)"} strokeWidth={sketch.shape === "open" || material === "water" ? ".025" : ".12"} />
        </g>)}
      </g>
      {(sketch.walls ?? []).filter(([x, y]) => !decoratedWalls.has(`${x},${y}`)).map(([x, y], i) => (
        <rect
          key={`wall-${i}`}
          x={x}
          y={y}
          width="1"
          height="1"
          fill="var(--tf-map-wall, #111)"
          stroke="var(--tf-map-wall-stroke, #222428)"
          strokeWidth=".03"
        />
      ))}
      {sketch.features.map((feature, i) => <MapFeature key={`feature-${i}`} feature={feature} idPrefix={`${idPrefix}-feature-${i}`} onFeature={onFeature} />)}
      {(sketch.edges ?? []).map((edge, i) => {
        const vertical = edge.side === "e" || edge.side === "w";
        const x = edge.side === "e" ? sketch.cols : 0;
        const y = edge.side === "s" ? sketch.rows : 0;
        const line = vertical
          ? { x1: x, y1: edge.start, x2: x, y2: edge.start + edge.length }
          : { x1: edge.start, y1: y, x2: edge.start + edge.length, y2: y };
        return <line key={`edge-${i}`} {...line} data-edge-meaning={edge.meaning} data-wall={edge.meaning === "obstacle" ? "true" : undefined} stroke="var(--tf-map-edge, #756)" strokeWidth={edge.meaning === "obstacle" ? ".12" : ".04"} strokeDasharray={edge.meaning === "boundary" ? ".2 .2" : undefined} />;
      })}
      {children}
      {sketch.exits.map((exit, i) => {
        const segs = exitSegments(area, exit);
        const isPicked = Boolean(
          (pickedPassageRef && exit.passage_ref === pickedPassageRef) ||
          (pickedExit && (
            (exit.passage_ref && pickedExit.passage_ref === exit.passage_ref) ||
            (exit.name === pickedExit.name && exit.side === pickedExit.side && exit.at === pickedExit.at)
          ))
        );
        return <g key={`exit-${i}`} data-passage-ref={exit.passage_ref ?? undefined} onClick={onPassage ? () => onPassage(exit) : undefined}
          role={onPassage ? "button" : undefined} tabIndex={onPassage ? 0 : undefined} aria-label={onPassage ? `Проход: ${exit.name}` : undefined}
          className={onPassage ? `tf-map-passage cursor-pointer ${isPicked ? "is-picked" : ""}` : undefined}
          onKeyDown={(event) => { if (onPassage && (event.key === "Enter" || event.key === " ")) { event.preventDefault(); onPassage(exit); } }}>
          {onPassage && segs.map((segment, j) => <rect key={`hit-${j}`} x={Math.min(segment.from[0], segment.to[0]) - .55} y={Math.min(segment.from[1], segment.to[1]) - .55} width={Math.abs(segment.to[0] - segment.from[0]) + 1.1} height={Math.abs(segment.to[1] - segment.from[1]) + 1.1} fill="transparent" pointerEvents="all" />)}
          {segs.map((segment, j) => <line key={j} x1={segment.from[0]} y1={segment.from[1]} x2={segment.to[0]} y2={segment.to[1]} data-opening="true" stroke={isPicked ? "var(--tf-accent)" : "var(--tf-map-opening, #e9d8a6)"} strokeWidth={isPicked ? ".34" : ".2"} />)}
          <title>{exit.name}</title>
        </g>;
      })}
    </g>
  );
}
