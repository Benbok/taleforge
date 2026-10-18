import type { Sketch } from "./map";
import type { Point, Segment } from "./locationGeometry";
import { featureFootprints } from "./featureGeometry";
import { wallTorchMounts, type WallTorchMounts } from "./wallLighting";

/** Paint only: these marks never add obstacles, discoveries or sources of game light. */
export function SketchAtmosphere({ sketch, floor, contours, idPrefix, torchMounts }: {
  sketch: Sketch; floor: Point[]; contours: Segment[]; idPrefix: string; torchMounts?: WallTorchMounts;
}) {
  const mounts = torchMounts ?? wallTorchMounts(sketch, floor, contours);
  const lights = sketch.features.filter((f) => !f.hidden && (
    f.kind === "light" || ["feature:torch", "feature:hearth", "feature:glow"].includes(f.visual_key ?? "")
  )).flatMap((feature) => featureFootprints(feature.cells).map((footprint, index) => ({ feature, footprint, index })));
  const enclosed = sketch.shape !== "open" && sketch.material !== "water";
  const water = sketch.material === "water";
  const floorSet = new Set(floor.map(([x, y]) => `${x},${y}`));
  return <g data-layer="atmosphere" pointerEvents="none" clipPath={`url(#${idPrefix}-floor)`}>
    <defs>
      <radialGradient id={`${idPrefix}-patina-dark`}>
        <stop stopColor="#090f0f" stopOpacity=".09" />
        <stop offset=".55" stopColor="#090f0f" stopOpacity=".035" />
        <stop offset="1" stopColor="#090f0f" stopOpacity="0" />
      </radialGradient>
      <radialGradient id={`${idPrefix}-patina-light`}>
        <stop stopColor={water ? "#9fd5da" : "#d8c9a4"} stopOpacity=".035" />
        <stop offset="1" stopColor={water ? "#9fd5da" : "#d8c9a4"} stopOpacity="0" />
      </radialGradient>
      <radialGradient id={`${idPrefix}-light-warm`}>
        <stop stopColor="#ffce7c" stopOpacity=".22" />
        <stop offset=".4" stopColor="#ed9b40" stopOpacity=".1" />
        <stop offset="1" stopColor="#b66a27" stopOpacity="0" />
      </radialGradient>
      <radialGradient id={`${idPrefix}-light-cool`}>
        <stop stopColor="#a8e4bc" stopOpacity=".19" />
        <stop offset="1" stopColor="#70c4b2" stopOpacity="0" />
      </radialGradient>
    </defs>
    <g data-layer="floor-patina">
      {floor.filter(([x, y]) => x % 2 === 0 && y % 2 === 0).map(([x, y]) => {
        const seed = ((x + 7) * 374761393 ^ (y + 13) * 668265263) >>> 0;
        const dark = seed % 3 !== 0;
        return <ellipse key={`${x},${y}`} cx={x + .3 + (seed % 11) / 10} cy={y + .4 + (seed % 7) / 10}
          rx={.6 + (seed % 5) * .17} ry={.3 + (seed % 3) * .16}
          fill={`url(#${idPrefix}-patina-${dark ? "dark" : "light"})`} />;
      })}
    </g>
    <g data-layer="contact-shadows" fill="none" strokeLinecap="square">
      {contours.map((segment, i) => {
        const [x, y] = segment.from;
        const [xx, yy] = segment.to;
        // A boundary beside a missing cell has a floor cell on just one side.
        const horizontal = y === yy;
        const upper = horizontal && floorSet.has(`${Math.min(x, xx)},${y}`);
        const left = !horizontal && floorSet.has(`${x},${Math.min(y, yy)}`);
        const shade = upper || left;
        return <line key={i} x1={x} y1={y} x2={xx} y2={yy}
          stroke={shade ? "#070d10" : water ? "#a8d7c9" : "#d2c6ac"}
          strokeWidth={enclosed ? (shade ? ".65" : ".13") : ".28"}
          opacity={enclosed ? (shade ? ".24" : ".17") : ".12"} />;
      })}
    </g>
    {lights.map(({ feature, footprint, index }) => {
      const [cx, cy] = mounts.get(feature)?.[index]?.center ?? [footprint.x + footprint.width / 2, footprint.y + footprint.height / 2];
      const cool = feature.visual_key === "feature:glow";
      return <ellipse key={`${feature.id}-${index}`} data-light-source={feature.id}
        cx={cx} cy={cy} rx={cool ? 2 : 3} ry={cool ? 1.7 : 2.5}
        fill={`url(#${idPrefix}-light-${cool ? "cool" : "warm"})`} />;
    })}
  </g>;
}
