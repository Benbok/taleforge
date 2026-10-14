import type { MapKnownArea, MapLocationPlan, Sketch, SketchExit } from "./map";

export type Point = [number, number];
export interface Segment { from: Point; to: Point; }
export interface Bounds { minX: number; minY: number; maxX: number; maxY: number; }

export function localToPlan(area: Pick<MapKnownArea, "offset">, point: Point): Point {
  return [point[0] + area.offset[0], point[1] + area.offset[1]];
}

export function mechanicalToPlan(area: Pick<MapKnownArea, "offset">, mechanical: Point, party: Point): Point {
  return localToPlan(area, [mechanical[0] + party[0], mechanical[1] + party[1]]);
}

export function planToMechanical(area: Pick<MapKnownArea, "offset">, party: Point, plan: Point): Point {
  return [plan[0] - area.offset[0] - party[0], plan[1] - area.offset[1] - party[1]];
}

function floorCells(sketch: Sketch): Set<string> {
  if (sketch.mask) {
    return new Set(sketch.mask.flatMap((row, y) => [...row].flatMap((cell, x) => cell === "." ? [`${x},${y}`] : [])));
  }
  return new Set(Array.from({ length: sketch.rows }, (_, y) => Array.from({ length: sketch.cols }, (_, x) => `${x},${y}`)).flat());
}

export function knownBounds(plan: MapLocationPlan, level: number): Bounds | null {
  const areas = plan.areas.filter((area) => area.level === level);
  if (!areas.length) return null;
  let bounds: Bounds | null = null;
  for (const area of areas) {
    for (const key of floorCells(area.sketch)) {
      const [x, y] = key.split(",").map(Number);
      const [px, py] = localToPlan(area, [x, y]);
      const next = { minX: px, minY: py, maxX: px + 1, maxY: py + 1 };
      bounds = bounds ? {
        minX: Math.min(bounds.minX, next.minX), minY: Math.min(bounds.minY, next.minY),
        maxX: Math.max(bounds.maxX, next.maxX), maxY: Math.max(bounds.maxY, next.maxY),
      } : next;
    }
  }
  return bounds;
}

export function overviewBounds(bounds: Bounds | null, minSpanX = 18, minSpanY = 12, pad = 2): Bounds | null {
  if (!bounds) return null;
  const kw = bounds.maxX - bounds.minX;
  const kh = bounds.maxY - bounds.minY;
  const cx = (bounds.minX + bounds.maxX) / 2;
  const cy = (bounds.minY + bounds.maxY) / 2;
  const spanX = Math.max(kw + pad * 2, minSpanX);
  const spanY = Math.max(kh + pad * 2, minSpanY);
  return {
    minX: Math.round((cx - spanX / 2) * 10) / 10,
    minY: Math.round((cy - spanY / 2) * 10) / 10,
    maxX: Math.round((cx + spanX / 2) * 10) / 10,
    maxY: Math.round((cy + spanY / 2) * 10) / 10,
  };
}

function segmentKey(a: Point, b: Point): string {
  return `${a[0]},${a[1]}:${b[0]},${b[1]}`;
}

export function surfaceGeometry(area: MapKnownArea): { floor: Point[]; contours: Segment[] } {
  const { sketch } = area;
  const floor = floorCells(sketch);
  const segments: Segment[] = [];
  const sides: [number, number, number, number][] = [[0, 0, 1, 0], [1, 0, 1, 1], [1, 1, 0, 1], [0, 1, 0, 0]];
  for (const key of [...floor].sort()) {
    const [x, y] = key.split(",").map(Number);
    const neighbors = [[x, y - 1], [x + 1, y], [x, y + 1], [x - 1, y]];
    for (let i = 0; i < neighbors.length; i++) {
      if (floor.has(`${neighbors[i][0]},${neighbors[i][1]}`)) continue;
      const [x0, y0, x1, y1] = sides[i];
      segments.push({ from: localToPlan(area, [x + x0, y + y0]), to: localToPlan(area, [x + x1, y + y1]) });
    }
  }
  const dedup = new Map<string, Segment>();
  for (const segment of segments) dedup.set(segmentKey(segment.from, segment.to), segment);
  return { floor: [...floor].map((key) => { const [x, y] = key.split(",").map(Number); return localToPlan(area, [x, y]); }), contours: [...dedup.values()] };
}

export function exitSegments(area: MapKnownArea, exit: SketchExit): Segment[] {
  const cells = exit.cells?.length ? exit.cells : [];
  const localCells = cells.length ? cells : [[
    exit.side === "e" ? area.sketch.cols - 1 : exit.side === "w" ? 0 : exit.at,
    exit.side === "s" ? area.sketch.rows - 1 : exit.side === "n" ? 0 : exit.at,
  ]];
  return localCells.map(([x, y]) => {
    const [from, to] = exit.side === "n" ? [[x, y], [x + 1, y]]
      : exit.side === "s" ? [[x, y + 1], [x + 1, y + 1]]
      : exit.side === "w" ? [[x, y], [x, y + 1]]
      : [[x + 1, y], [x + 1, y + 1]];
    return { from: localToPlan(area, from as Point), to: localToPlan(area, to as Point) };
  });
}
