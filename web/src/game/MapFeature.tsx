import { MapGlyph } from "./MapGlyph";
import { featureFootprints, type FeatureFootprint } from "./featureGeometry";
import { featureVisual, type FeatureVisual } from "./mapPresets";
import type { SketchFeature } from "./map";

const WOOD = "var(--tf-map-prop-wood, #966b45)";
const STONE = "var(--tf-map-prop-stone, #777d7a)";
const LEAVES = "var(--tf-map-foliage, #386849)";

function Artwork({ footprint: f, visual: v }: { footprint: FeatureFootprint; visual: FeatureVisual }) {
  const { x, y, width: w, height: h, cells } = f;
  const cx = x + w / 2, cy = y + h / 2;
  const frame = { x: x + .12, y: y + .12, width: Math.max(.1, w - .24), height: Math.max(.1, h - .24) };
  switch (v.form) {
    case "bench":
      return <g fill={WOOD} stroke="#c3a172" strokeWidth=".04">
        {w >= h ? <>
          <path d={`M${x + .2} ${cy - .25}v.5 M${x + w - .2} ${cy - .25}v.5`} stroke="#4c3a29" strokeWidth=".12" />
          <rect x={x + .08} y={cy - .15} width={w - .16} height=".3" rx=".03" />
        </> : <>
          <path d={`M${cx - .25} ${y + .2}h.5 M${cx - .25} ${y + h - .2}h.5`} stroke="#4c3a29" strokeWidth=".12" />
          <rect x={cx - .15} y={y + .08} width=".3" height={h - .16} rx=".03" />
        </>}
      </g>;
    case "table": case "counter":
      return <g stroke="#2b2119" strokeWidth=".035" opacity=".85">
        {cells.map(([c, r]) => <g key={`${c},${r}`}>
          <path d={`M${c} ${r + .3}h1 M${c} ${r + .7}h1`} />
          <path d={`M${c + .1} ${r + .08}h.8`} stroke="#ecd1a0" opacity=".45" />
        </g>)}
        {v.form === "table" && <rect {...frame} rx=".08" fill="none" stroke="#e2bc87" strokeWidth=".04" />}
        {v.form === "counter" && <path d={f.path} fill="none" stroke="#dfba80" strokeWidth=".18" opacity=".6" />}
      </g>;
    case "bed":
      return <g>
        <rect {...frame} rx=".09" fill="#657b7f" stroke="#b3c2bc" strokeWidth=".045" />
        <rect x={x + .2} y={y + .2} width={w >= h ? Math.min(.4, w * .24) : w - .4}
          height={w >= h ? h - .4 : Math.min(.4, h * .24)} rx=".09" fill="#d6cbb1" />
        <path d={w >= h ? `M${x + w * .42} ${y + .2}V${y + h - .2} M${x + w - .25} ${y + .2}V${y + h - .2}`
          : `M${x + .2} ${y + h * .42}H${x + w - .2} M${x + .2} ${y + h - .25}H${x + w - .2}`}
          stroke="#a0b0aa" strokeWidth=".05" />
      </g>;
    case "shelf":
      return <g>{cells.map(([c, r]) => <g key={`${c},${r}`}>
        <path d={`M${c + .14} ${r + .12}v.76 M${c + .86} ${r + .12}v.76 M${c} ${r + .5}h1`} stroke="#3d2a1c" strokeWidth=".07" />
        <rect x={c + .24} y={r + .13} width=".22" height=".27" rx=".03" fill="#b7a16e" />
        <rect x={c + .53} y={r + .57} width=".24" height=".26" rx=".03" fill="#7c8b6a" />
      </g>)}</g>;
    case "barrel":
      return <g>{cells.map(([c, r]) => <g key={`${c},${r}`}>
        <circle cx={c + .5} cy={r + .5} r=".4" fill={WOOD} stroke="#302a23" strokeWidth=".08" />
        <path d={`M${c + .28} ${r + .18}v.64 M${c + .72} ${r + .18}v.64`} stroke="#c6b993" strokeWidth=".075" />
        <circle cx={c + .5} cy={r + .5} r=".08" fill="#4d3624" />
      </g>)}</g>;
    case "crate":
      return <g>{cells.map(([c, r]) => <g key={`${c},${r}`}>
        <rect x={c + .08} y={r + .08} width=".84" height=".84" rx=".03" fill={WOOD} stroke="#d4b07c" strokeWidth=".055" />
        <path d={`M${c + .16} ${r + .16}l.68.68 M${c + .84} ${r + .16}l-.68.68`} stroke="#493523" strokeWidth=".08" />
      </g>)}</g>;
    case "chest":
      return <g>
        <rect {...frame} rx=".045" fill="none" stroke="#d4b07c" strokeWidth=".08" />
        <>
          <path d={`M${x + .25} ${y}v${h} M${x + w - .25} ${y}v${h}`} stroke="#d4ba76" strokeWidth=".1" />
          <rect x={cx - .12} y={cy - .1} width=".24" height=".2" rx=".02" fill="#dec17e" />
        </>
      </g>;
    case "hearth":
      return <g>
        <rect {...frame} rx=".15" fill="#343633" stroke="#8c8c79" strokeWidth=".07" />
        <ellipse cx={cx} cy={cy} rx={Math.max(.1, w * .32)} ry={Math.max(.1, h * .28)} fill="#b95732" />
        <ellipse cx={cx} cy={cy} rx={Math.max(.08, w * .18)} ry={Math.max(.08, h * .16)} fill="#f0bb60" />
        <path d={`M${cx - .22} ${cy + .12}l.44-.07 M${cx - .18} ${cy - .08}l.35.12`} stroke="#543a27" strokeWidth=".08" />
      </g>;
    case "torch":
      return <g>
        <circle cx={cx} cy={cy} r={Math.min(w, h) * .34} fill="#564b34" stroke="#aa9864" strokeWidth=".045" />
        <path d={`M${cx} ${cy - .3}C${cx - .3} ${cy} ${cx - .23} ${cy + .25} ${cx} ${cy + .25}C${cx + .3} ${cy + .23} ${cx + .15} ${cy - .1} ${cx} ${cy - .3}Z`}
          fill="#e89b48" /><ellipse cx={cx} cy={cy + .1} rx=".09" ry=".12" fill="#f5d17d" />
      </g>;
    case "glow":
      return <g>
        <ellipse cx={cx} cy={cy} rx={w * .47} ry={h * .42} fill="#7ec6b4" opacity=".12" />
        <ellipse cx={cx} cy={cy} rx={w * .31} ry={h * .28} fill="#99d6b9" opacity=".18" />
        <path d={`M${x + w * .2} ${cy}q${w * .15} -.14 ${w * .3} 0t${w * .3} 0`} fill="none" stroke="#b4ddba" strokeWidth=".04" />
      </g>;
    case "lichen":
      return <g fill="#8eb99b">{cells.map(([c, r]) => <g key={`${c},${r}`}>
        <ellipse cx={c + .5} cy={r + .5} rx=".43" ry=".35" fill="#609e84" opacity=".13" />
        <path d={`M${c + .2} ${r + .35}l.13-.1.1.12-.1.1Z M${c + .5} ${r + .5}l.15-.13.1.16-.15.12Z M${c + .3} ${r + .7}l.09-.09.08.1Z`} />
      </g>)}</g>;
    case "nest":
      return <g>
        <ellipse cx={cx} cy={cy} rx={w * .43} ry={h * .4} fill="#5a563b" stroke="#9b9568" strokeWidth=".07" />
        <ellipse cx={cx} cy={cy} rx={w * .29} ry={h * .25} fill="#474b34" />
        <path d={`M${x + .16} ${cy}l.18-.15 M${cx} ${y + .15}l.15.12 M${x + w - .25} ${cy}l.12.18 M${cx - .2} ${y + h - .16}l.3-.07`}
          stroke="#b0a36f" strokeWidth=".045" />
      </g>;
    case "pillar":
      return <g>{cells.map(([c, r]) => <g key={`${c},${r}`}>
        <rect x={c + .08} y={r + .08} width=".84" height=".84" rx=".05" fill="#585f60" />
        <circle cx={c + .5} cy={r + .5} r=".32" fill="#969a8c" stroke="#cad0bb" strokeWidth=".035" />
        <circle cx={c + .5} cy={r + .5} r=".22" fill="none" stroke="#626b64" strokeWidth=".04" />
      </g>)}</g>;
    case "rock": case "rubble":
      return <g>{cells.map(([c, r]) => <g key={`${c},${r}`}>
        <path d={`M${c + .08} ${r + .32}l.23-.23.43.07.19.32-.13.35-.46.08-.29-.23Z`}
          fill={v.form === "rubble" ? "#7c7868" : STONE} stroke="#a4a58e" strokeWidth=".035" />
        <path d={`M${c + .31} ${r + .09}l.17.34.45.05 M${c + .48} ${r + .43}l-.27.3`}
          fill="none" stroke="#434d4c" strokeWidth=".05" />
        {v.form === "rubble" && <path d={`M${c + .05} ${r + .82}l.15-.06.06.19Z M${c + .78} ${r + .08}l.17.12-.08.14Z`} fill="#b0a48a" />}
      </g>)}</g>;
    case "tree": case "shrub":
      return <g>{cells.map(([c, r]) => <g key={`${c},${r}`}>
        <ellipse cx={c + .53} cy={r + .54} rx=".44" ry=".4" fill="#1e3b2e" />
        <circle cx={c + .34} cy={r + .46} r=".3" fill={LEAVES} />
        <circle cx={c + .62} cy={r + .34} r=".29" fill="#497a50" />
        <circle cx={c + .58} cy={r + .66} r=".26" fill="#315d40" />
        {v.form === "tree" && <path d={`M${c + .5} ${r + .37}v.28l.14.09 M${c + .5} ${r + .57}l-.15-.12`}
          stroke="#a6b783" strokeWidth=".04" opacity=".65" />}
      </g>)}</g>;
    case "reeds":
      return <g stroke="#92a46c" strokeWidth=".04">{cells.map(([c, r]) => <path key={`${c},${r}`}
        d={`M${c + .5} ${r + .85}q-.28-.28-.31-.65 M${c + .5} ${r + .85}q.1-.4.3-.65 M${c + .5} ${r + .85}v-.75 M${c + .5} ${r + .85}q-.1-.4.08-.55`} />)}</g>;
    case "crystal":
      return <g>{cells.map(([c, r]) => <g key={`${c},${r}`}>
        <path d={`M${c + .5} ${r + .1}l.24.3-.1.42-.27-.12-.13-.38Z`} fill="#6fa69e" stroke="#a7d3c1" strokeWidth=".04" />
        <path d={`M${c + .5} ${r + .1}v.5l.14.22`} fill="none" stroke="#d7f0d5" strokeWidth=".04" />
      </g>)}</g>;
    case "bones":
      return <g stroke="#c7bda0" strokeWidth=".09" strokeLinecap="round">{cells.map(([c, r]) => <path key={`${c},${r}`}
        d={`M${c + .25} ${r + .28}l.5.44 M${c + .26} ${r + .68}l.44-.42`} />)}</g>;
    case "net":
      return <g fill="none" stroke="#adab83" strokeWidth=".035">{cells.map(([c, r]) => <path key={`${c},${r}`}
        d={`M${c + .15} ${r}l.85.85 M${c} ${r + .2}l.8.8 M${c + .5} ${r}l.5.5 M${c} ${r + .5}l.5.5 M${c} ${r + .8}l.8-.8 M${c + .2} ${r + 1}l.8-.8 M${c} ${r + .4}l.4-.4 M${c + .6} ${r + 1}l.4-.4`} />)}</g>;
    case "crane":
      return <g stroke="#d2b585" strokeWidth=".08" fill="none">
        <circle cx={cx} cy={cy} r={Math.min(w, h) * .25} fill="#4b4f4b" stroke="#9fa08b" />
        <path d={`M${x + .2} ${y + h - .2}L${x + w - .2} ${y + .2} M${x + .3} ${y + h - .2}L${x + w - .2} ${y + .3}`} />
        <circle cx={x + w - .23} cy={y + .23} r=".09" fill="#c8b890" />
      </g>;
    case "mooring":
      return <g stroke="#b0a994" strokeWidth=".08">
        <ellipse cx={cx} cy={cy} rx={w * .3} ry={h * .24} fill="#3c4b4c" />
        <path d={`M${cx - w * .28} ${cy}h${w * .56}`} />
      </g>;
    case "altar":
      return <g>
        <rect {...frame} rx=".08" fill="#8b8a77" stroke="#c9c3a0" strokeWidth=".07" />
        <circle cx={cx} cy={cy} r={Math.min(w, h) * .2} fill="none" stroke="#d6bd7c" strokeWidth=".05" />
        <path d={`M${cx} ${cy - .15}v.3 M${cx - .15} ${cy}h.3`} stroke="#e4cf96" strokeWidth=".05" />
      </g>;
    default: {
      const distance = ([c, r]: [number, number]) => (c + .5 - cx) ** 2 + (r + .5 - cy) ** 2;
      const [c, r] = [...cells].sort((a, b) => distance(a) - distance(b) || a[1] - b[1] || a[0] - b[0])[0];
      return <MapGlyph name={v.glyph} x={c + .15} y={r + .15} width={.7} height={.7} color={v.color} />;
    }
  }
}

export function MapFeature({ feature, idPrefix, onFeature }: {
  feature: SketchFeature; idPrefix: string; onFeature?: (id: string, name: string) => void;
}) {
  const visual = featureVisual(feature);
  const wood = ["table", "bench", "bed", "counter", "shelf", "barrel", "crate", "chest", "crane"].includes(visual.form);
  const natural = ["tree", "shrub", "reeds"].includes(visual.form);
  const loose = natural || ["barrel", "pillar", "rock", "rubble", "crystal", "bones", "net", "mooring", "torch", "glow", "lichen", "nest", "bench"].includes(visual.form);
  const color = wood ? WOOD : natural ? "#294f38" : ["rock", "rubble", "pillar", "altar", "hearth"].includes(visual.form) ? STONE : visual.color;
  return <g data-feature-id={feature.entity_id ?? feature.id} data-feature-solid={feature.solid ? "true" : undefined}
    onClick={feature.entity_id && onFeature ? () => onFeature(feature.entity_id!, feature.name) : undefined}>
    {featureFootprints(feature.cells).map((footprint, index) => {
      const clipId = `${idPrefix}-${index}`;
      return <g key={index} data-feature-form={visual.form}>
        <defs><clipPath id={clipId}><path d={footprint.path} fillRule="evenodd" /></clipPath></defs>
        {!loose && <path d={footprint.path} fillRule="evenodd" fill="#080b0c" opacity=".35" transform="translate(.055 .075)" />}
        <path d={footprint.path} fillRule="evenodd" fill={color} opacity={loose ? "0" : ".85"}
          stroke="#202823" strokeWidth=".08" strokeLinejoin="round"
          data-feature-body="true" data-footprint-area={footprint.cells.length} />
        <g clipPath={`url(#${clipId})`} pointerEvents="none"><Artwork footprint={footprint} visual={visual} /></g>
        {feature.solid && !loose && <path d={footprint.path} fill="none" stroke="#d3c8a2" opacity=".18" strokeWidth=".03" pointerEvents="none" />}
      </g>;
    })}
    <title>{feature.name}</title>
  </g>;
}
