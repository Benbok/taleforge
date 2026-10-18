import { featureFootprints } from "./featureGeometry";
import type { Point, Segment } from "./locationGeometry";
import type { Sketch, SketchFeature, SketchExit } from "./map";
import { featureVisual } from "./mapPresets";

export interface WallTorchMount {
  side: SketchExit["side"];
  center: Point;
  angle: number;
}
export type WallTorchMounts = ReadonlyMap<SketchFeature, (WallTorchMount | undefined)[]>;

const SIDES: SketchExit["side"][] = ["n", "e", "s", "w"];
function cellSide(c: number, r: number, side: SketchExit["side"]): Segment {
  return side === "n" ? { from: [c, r], to: [c + 1, r] }
    : side === "e" ? { from: [c + 1, r], to: [c + 1, r + 1] }
    : side === "s" ? { from: [c, r + 1], to: [c + 1, r + 1] }
    : { from: [c, r], to: [c, r + 1] };
}
const segmentKey = ({ from: a, to: b }: Segment) => [a.join(","), b.join(",")].sort().join(":");

/** Mount only beside an existing indoor wall. Never change occupied cells or infer new lights. */
export function wallTorchMounts(sketch: Sketch, floor: Point[], contours: Segment[]): WallTorchMounts {
  const result = new Map<SketchFeature, (WallTorchMount | undefined)[]>();
  if (sketch.environment === "outdoor" || ["open", "street"].includes(sketch.shape) || sketch.material === "water") return result;
  const floorSet = new Set(floor.map((point) => point.join(",")));
  const walls = new Set(contours.map(segmentKey));
  const openings = new Set<string>();
  for (const exit of sketch.exits) {
    // Older sketches specify only at/width; newer sketches carry actual mask-boundary cells.
    const cells = exit.cells?.length ? featureFootprints(exit.cells).flatMap((f) => f.cells)
      : Array.from({ length: Math.max(1, exit.width ?? 1) }, (_, i): Point => [
        exit.side === "e" ? sketch.cols - 1 : exit.side === "w" ? 0 : exit.at + i,
        exit.side === "s" ? sketch.rows - 1 : exit.side === "n" ? 0 : exit.at + i,
      ]);
    for (const [c, r] of cells) openings.add(segmentKey(cellSide(c, r, exit.side)));
  }
  for (const edge of sketch.edges ?? []) {
    if (edge.meaning === "obstacle") continue;
    for (let i = edge.start; i < edge.start + edge.length; i++) {
      const c = edge.side === "e" ? sketch.cols - 1 : edge.side === "w" ? 0 : i;
      const r = edge.side === "s" ? sketch.rows - 1 : edge.side === "n" ? 0 : i;
      openings.add(segmentKey(cellSide(c, r, edge.side)));
    }
  }
  for (const feature of sketch.features) {
    if (feature.hidden || featureVisual(feature).form !== "torch") continue;
    result.set(feature, featureFootprints(feature.cells).map((footprint) => {
      for (const [c, r] of [...footprint.cells].sort((a, b) => a[1] - b[1] || a[0] - b[0])) {
        if (!floorSet.has(`${c},${r}`)) continue;
        for (const side of SIDES) {
          const key = segmentKey(cellSide(c, r, side));
          if (!walls.has(key) || openings.has(key)) continue;
          const center: Point = [c + (side === "w" ? .24 : side === "e" ? .76 : .5), r + (side === "n" ? .24 : side === "s" ? .76 : .5)];
          return { side, center, angle: SIDES.indexOf(side) * 90 };
        }
      }
      return undefined;
    }));
  }
  return result;
}
