import { exitSegments, surfaceGeometry } from "./locationGeometry";
import type { MapKnownArea, Sketch, SketchExit } from "./map";
import { MapGlyph } from "./MapGlyph";
import { FEATURE_VISUALS } from "./mapPresets";

export interface SketchSurfaceProps {
  sketch: Sketch;
  areaId?: string;
  idPrefix: string;
  onPassage?: (exit: SketchExit) => void;
  onFeature?: (id: string, name: string) => void;
}

const MATERIALS = new Set(["stone", "earth", "grass", "water", "wood"]);

export function terrainCells(rects: number[][]): [number, number][] {
  return rects.flatMap(([x0, y0, x1 = x0, y1 = y0]) =>
    Array.from({ length: y1 - y0 + 1 }, (_, y) =>
      Array.from({ length: x1 - x0 + 1 }, (_, x) => [x0 + x, y0 + y] as [number, number])).flat());
}

export function SketchSurface({ sketch, areaId = "area", idPrefix, onPassage, onFeature }: SketchSurfaceProps) {
  const area: MapKnownArea = { id: areaId, name: areaId, offset: [0, 0], level: 0, status: "here", revision: 0, sketch };
  const geometry = surfaceGeometry(area);
  const material = MATERIALS.has(sketch.material ?? "") ? sketch.material! : "stone";
  const clipId = `${idPrefix}-floor`;
  return (
    <g role="img" data-sketch-surface={areaId}>
      <defs>
        <pattern id={`${idPrefix}-pattern-${material}`} width="1" height="1" patternUnits="userSpaceOnUse">
          <rect width="1" height="1" fill={`var(--tf-map-${material}, var(--tf-map-floor, #3b3b3b))`} />
          <path d="M0 0L1 1M1 0L0 1" stroke="var(--tf-map-mark, #ffffff18)" strokeWidth=".06" />
        </pattern>
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
          {terrainCells(terrain.cells).map(([x, y], j) => <rect key={j} x={x} y={y} width="1" height="1" fill="var(--tf-map-bridge, #a77b52)" />)}
        </g>
      ))}
      <g data-layer="contours">
        {geometry.contours.map((segment, i) => <line key={i} x1={segment.from[0]} y1={segment.from[1]} x2={segment.to[0]} y2={segment.to[1]} data-wall={sketch.shape === "open" ? undefined : "true"} stroke="var(--tf-map-wall, #111)" strokeWidth={sketch.shape === "open" ? ".025" : ".12"} />)}
      </g>
      {(sketch.walls ?? []).map(([x, y], i) => <rect key={`wall-${i}`} x={x} y={y} width="1" height="1" fill="var(--tf-map-wall, #111)" />)}
      {sketch.features.map((feature, i) => {
        const visual = FEATURE_VISUALS[feature.kind] ?? FEATURE_VISUALS.object;
        const first = feature.cells[0];
        if (!first) return null;
        return <g key={`feature-${i}`} data-feature-id={feature.entity_id ?? feature.id}
          onClick={feature.entity_id && onFeature ? () => onFeature(feature.entity_id!, feature.name) : undefined}>
          {terrainCells(feature.cells).map(([x, y], j) => <rect key={j} x={x + .1} y={y + .1} width=".8" height=".8" fill="var(--tf-muted, #766)" opacity=".3" />)}
          <MapGlyph name={visual.glyph} x={first[0] + .15} y={first[1] + .15} width={.7} height={.7} color={visual.color} />
          <title>{feature.name}</title>
        </g>;
      })}
      {(sketch.edges ?? []).map((edge, i) => {
        const vertical = edge.side === "e" || edge.side === "w";
        const x = edge.side === "e" ? sketch.cols : 0;
        const y = edge.side === "s" ? sketch.rows : 0;
        const line = vertical
          ? { x1: x, y1: edge.start, x2: x, y2: edge.start + edge.length }
          : { x1: edge.start, y1: y, x2: edge.start + edge.length, y2: y };
        return <line key={`edge-${i}`} {...line} data-edge-meaning={edge.meaning} data-wall={edge.meaning === "obstacle" ? "true" : undefined} stroke="var(--tf-map-edge, #756)" strokeWidth={edge.meaning === "obstacle" ? ".12" : ".04"} strokeDasharray={edge.meaning === "boundary" ? ".2 .2" : undefined} />;
      })}
      {sketch.exits.map((exit, i) => {
        const segs = exitSegments(area, exit);
        return <g key={`exit-${i}`} data-passage-ref={exit.passage_ref ?? undefined} onClick={() => onPassage?.(exit)}
          role={onPassage ? "button" : undefined} tabIndex={onPassage ? 0 : undefined} aria-label={onPassage ? `Проход: ${exit.name}` : undefined}
          className={onPassage ? "tf-map-passage cursor-pointer" : undefined}
          onKeyDown={(event) => { if (onPassage && (event.key === "Enter" || event.key === " ")) { event.preventDefault(); onPassage(exit); } }}>
          {onPassage && segs.map((segment, j) => <rect key={`hit-${j}`} x={Math.min(segment.from[0], segment.to[0]) - .35} y={Math.min(segment.from[1], segment.to[1]) - .35} width={Math.abs(segment.to[0] - segment.from[0]) + .7} height={Math.abs(segment.to[1] - segment.from[1]) + .7} fill="transparent" />)}
          {segs.map((segment, j) => <line key={j} x1={segment.from[0]} y1={segment.from[1]} x2={segment.to[0]} y2={segment.to[1]} data-opening="true" stroke="var(--tf-map-opening, #e9d8a6)" strokeWidth=".2" />)}
          <title>{exit.name}</title>
        </g>;
      })}
    </g>
  );
}
