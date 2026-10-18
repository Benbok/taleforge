import { MapGlyph } from "./MapGlyph";
import { featureFootprints, type FeatureFootprint } from "./featureGeometry";
import { featureVisual, type FeatureVisual } from "./mapPresets";
import type { SketchFeature } from "./map";
import type { WallTorchMount } from "./wallLighting";

const WOOD = "var(--tf-map-prop-wood, #966b45)";
const STONE = "var(--tf-map-prop-stone, #777d7a)";
const LEAVES = "var(--tf-map-foliage, #386849)";
const INK = "#30291f";
const BRASS = "#c8ac70";

/** Stable local noise: adding/reordering cells or renaming an object never reshuffles it. */
function variation(id: string, c: number, r: number, detail = 0) {
  let hash = 2166136261;
  for (const char of `${id}:${c},${r}:${detail}`) hash = Math.imul(hash ^ char.charCodeAt(0), 16777619);
  hash ^= hash >>> 16;
  hash = Math.imul(hash, 0x45d9f3b);
  return (hash >>> 0) / 4294967296;
}

function WoodGrain({ footprint, seed }: { footprint: FeatureFootprint; seed: string }) {
  return <g fill="none" strokeLinecap="round">{footprint.cells.map(([c, r]) => {
    const knot = .22 + variation(seed, c, r) * .55;
    return <g key={`${c},${r}`}>
      <path d={`M${c} ${r + .25}h1 M${c} ${r + .51}h1 M${c} ${r + .77}h1`} stroke="#35251a" strokeWidth=".025" opacity=".55" />
      <path d={`M${c + .05} ${r + .29}q.3-.025.51.005t.37-.01 M${c + .08} ${r + .8}q.25.025.48 0t.36.01`}
        stroke="#ebc38d" strokeWidth=".018" opacity=".4" />
      <ellipse cx={c + knot} cy={r + .64} rx=".085" ry=".024" stroke="#3d2a1b" strokeWidth=".02" opacity=".55" />
      <path d={`M${c + knot - .15} ${r + .61}q.15-.045.3 0 M${c + knot - .18} ${r + .68}q.18.035.36 0`}
        stroke="#422c1c" strokeWidth=".014" opacity=".4" />
    </g>;
  })}</g>;
}

function Artwork({ footprint: f, visual: v, seed, mount }: { footprint: FeatureFootprint; visual: FeatureVisual; seed: string; mount?: WallTorchMount }) {
  const { x, y, width: w, height: h, cells } = f;
  const cx = x + w / 2, cy = y + h / 2;
  const frame = { x: x + .12, y: y + .12, width: Math.max(.1, w - .24), height: Math.max(.1, h - .24) };
  switch (v.form) {
    case "bench": {
      const horizontal = w >= h;
      const length = (horizontal ? w : h) - .14;
      return <g transform={`translate(${cx} ${cy})${horizontal ? "" : " rotate(90)"}`}>
        <path d={`M${-length / 2 + .12}-.29v.62 M${length / 2 - .12}-.29v.62`} stroke="#171e1c" strokeWidth=".13" />
        <rect x={-length / 2 + .045} y="-.145" width={length} height=".4" rx=".04" fill="#101714" opacity=".5" />
        {[-.18, .025].map((offset) => <g key={offset}>
          <rect x={-length / 2} y={offset} width={length} height=".17" rx=".025" fill={WOOD} stroke="#d1aa73" strokeWidth=".035" />
          <path d={`M${-length / 2 + .08} ${offset + .09}q${length / 3}-.035 ${length * .6} 0t${length * .28} 0`} fill="none" stroke="#513821" strokeWidth=".018" />
          {[-1, 1].map((side) => <circle key={side} cx={side * (length / 2 - .12)} cy={offset + .085} r=".025" fill={INK} />)}
        </g>)}
      </g>;
    }
    case "table": case "counter":
      return <g>
        <WoodGrain footprint={f} seed={seed} />
        <path d={f.path} fill="none" stroke="#e3bd86" strokeWidth=".12" opacity=".7" />
        <path d={f.path} fill="none" stroke="#35271d" strokeWidth=".075" transform="translate(-.07 -.07)" opacity=".7" />
        {cells.map(([c, r]) => {
          const turn = variation(seed, c, r);
          return <g key={`${c},${r}`}>
            {v.form === "table" && turn > .36 && <g transform={`translate(${c + .43} ${r + .45}) rotate(${turn * 28 - 14})`}>
              <ellipse cx=".025" cy=".045" rx=".21" ry=".18" fill="#201d18" opacity=".45" />
              <circle r=".19" fill="#c9c1a0" stroke="#ece0b8" strokeWidth=".025" />
              <circle r=".13" fill="#9b987e" stroke="#e0d4af" strokeWidth=".02" />
              <path d="M-.26-.15v.3 M-.29-.15v.075h.06V-.15 M.27-.15v.3" fill="none" stroke="#d3cab0" strokeWidth=".022" />
              <circle cx=".24" cy="-.23" r=".072" fill="#2e2922" stroke={BRASS} strokeWidth=".025" />
              <path d="M.3-.26q.1.02.005.08" fill="none" stroke={BRASS} strokeWidth=".025" />
            </g>}
            {v.form === "counter" && turn > .55 && <g>
              <rect x={c + .22} y={r + .27} width=".5" height=".4" rx=".045" fill="#583b29" stroke="#b39363" strokeWidth=".025" />
              <ellipse cx={c + .45} cy={r + .46} rx=".15" ry=".12" fill="#af9270" stroke="#dfc294" strokeWidth=".025" />
              <path d={`M${c + .52} ${r + .24}l.15.13`} stroke="#c9c8af" strokeWidth=".04" />
            </g>}
          </g>;
        })}
      </g>;
    case "bed": {
      const horizontal = w >= h;
      const length = horizontal ? w : h, breadth = horizontal ? h : w;
      return <g transform={`translate(${cx} ${cy})${horizontal ? "" : " rotate(90)"}`}>
        <rect x={-length / 2 + .1} y={-breadth / 2 + .13} width={length - .2} height={breadth - .2} rx=".06" fill="#31291e" />
        <rect x={-length / 2 + .16} y={-breadth / 2 + .16} width={length - .32} height={breadth - .32} rx=".1" fill="#b6b09b" stroke="#e4d5b0" strokeWidth=".04" />
        <rect x={-length / 2 + .25} y={-breadth / 2 + .22} width={Math.min(.4, length * .25)} height={Math.max(.2, breadth - .44)} rx=".1" fill="#ded3b8" stroke="#9f967e" strokeWidth=".025" />
        <path d={`M${-length / 2 + .3} ${-breadth / 2 + .3}q.11-.05.22.015`} fill="none" stroke="#fff0cc" strokeWidth=".025" />
        <rect x={-length / 2 + length * .37} y={-breadth / 2 + .19} width={length * .63 - .19} height={breadth - .38} rx=".055" fill="#526c73" stroke="#8aa09b" strokeWidth=".035" />
        <path d={`M${-length / 2 + length * .43} ${-breadth / 2 + .21}v${breadth - .42}`} stroke="#afbeb0" strokeWidth=".1" />
        <path d={`M${length / 2 - .3} ${-breadth / 2 + .24}v${breadth - .48} M${-length / 2 + length * .5} ${breadth / 2 - .3}h${length * .5 - .31}`}
          fill="none" stroke="#b6c6b6" strokeWidth=".022" strokeDasharray=".04 .055" opacity=".7" />
        {[-1, 1].map((side) => <g key={side}>
          <rect x={side < 0 ? -length / 2 + .04 : length / 2 - .14} y={-breadth / 2 + .08} width=".1" height={breadth - .16} rx=".025" fill={WOOD} stroke="#cfa773" strokeWidth=".025" />
          {[-1, 1].map((end) => <circle key={end} cx={side * (length / 2 - .09)} cy={end * (breadth / 2 - .1)} r=".065" fill="#775033" stroke="#d0ac76" strokeWidth=".025" />)}
        </g>)}
      </g>;
    }
    case "shelf":
      return <g><WoodGrain footprint={f} seed={seed} />{cells.map(([c, r]) => <g key={`${c},${r}`}>
        <rect x={c + .1} y={r + .1} width=".8" height=".8" fill="#28271f" opacity=".65" />
        {[.16, .55].map((level, row) => <g key={level}>
          {[.19, .32, .46, .61].map((offset, i) => <g key={offset} transform={`translate(${c + offset} ${r + level}) rotate(${variation(seed, c, r, row * 4 + i) * 12 - 6})`}>
            <rect width={i === 2 ? .12 : .095} height=".24" rx=".012" fill={["#a38656", "#67766b", "#976552", "#8b8b6c"][i]} stroke="#261f18" strokeWidth=".015" />
            <path d="M.015.04h.065 M.015.19h.065" stroke="#d7c294" strokeWidth=".018" />
          </g>)}
          <path d={`M${c + .1} ${r + level + .29}h.8`} stroke="#c19861" strokeWidth=".065" />
          <path d={`M${c + .1} ${r + level + .33}h.8`} stroke="#3b2b1e" strokeWidth=".035" />
        </g>)}
        <path d={`M${c + .13} ${r + .1}v.8 M${c + .87} ${r + .1}v.8`} stroke="#c5a06b" strokeWidth=".07" />
      </g>)}</g>;
    case "barrel":
      return <g>{cells.map(([c, r]) => <g key={`${c},${r}`} transform={`translate(${c + .5} ${r + .5})`}>
        <ellipse cx=".055" cy=".08" rx=".41" ry=".38" fill="#131b16" opacity=".55" />
        <circle r=".39" fill={WOOD} stroke="#292b25" strokeWidth=".085" />
        <circle r=".345" fill="none" stroke="#afa88b" strokeWidth=".035" />
        {[-.21, -.07, .08, .23].map((offset) => {
          const edge = Math.sqrt(.32 ** 2 - offset ** 2);
          return <path key={offset} d={`M${-edge} ${offset}h${edge * 2}`} stroke="#523a28" strokeWidth=".025" />;
        })}
        <path d="M-.2-.25q.2-.1.4 0 M-.25.1q.2-.04.42.015" fill="none" stroke="#e0b478" strokeWidth=".02" opacity=".7" />
        {[[-.27, -.25], [.27, -.25], [-.27, .25], [.27, .25]].map(([a, b], i) => <circle key={i} cx={a} cy={b} r=".023" fill="#d0c8a9" />)}
        <circle cx={.06 + variation(seed, c, r) * .09} cy=".07" r=".06" fill="#68492e" stroke="#d3ae74" strokeWidth=".02" />
      </g>)}</g>;
    case "crate":
      return <g><WoodGrain footprint={f} seed={seed} />{cells.map(([c, r]) => <g key={`${c},${r}`}>
        <rect x={c + .1} y={r + .1} width=".8" height=".8" rx=".02" fill="none" stroke="#e1b47b" strokeWidth=".09" />
        <rect x={c + .17} y={r + .17} width=".66" height=".66" fill="none" stroke="#473322" strokeWidth=".04" />
        <path d={`M${c + .18} ${r + .21}l.64.64 M${c + .82} ${r + .21}l-.64.64`} stroke="#392c20" strokeWidth=".105" />
        <path d={`M${c + .18} ${r + .18}l.64.64 M${c + .82} ${r + .18}l-.64.64`} stroke="#be945e" strokeWidth=".075" />
        {[.13, .87].flatMap((a) => [.13, .87].map((b) => <circle key={`${a},${b}`} cx={c + a} cy={r + b} r=".025" fill="#38372e" />))}
      </g>)}</g>;
    case "chest":
      return <g>
        <WoodGrain footprint={f} seed={seed} />
        <rect {...frame} rx=".06" fill="none" stroke="#dab37b" strokeWidth=".06" />
        <path d={`M${x + .16} ${cy + .12}H${x + w - .16}`} stroke="#342b20" strokeWidth=".055" />
        {[x + Math.min(.3, w * .25), x + w - Math.min(.3, w * .25)].map((a) => <g key={a}>
          <path d={`M${a} ${y + .04}v${h - .08}`} stroke="#393b31" strokeWidth=".13" />
          <path d={`M${a - .025} ${y + .05}v${h - .1}`} stroke={BRASS} strokeWidth=".025" />
          {[y + .16, y + h - .16].map((b) => <circle key={b} cx={a} cy={b} r=".023" fill="#ded1a3" />)}
          <rect x={a - .09} y={y + .07} width=".18" height=".09" rx=".02" fill="#77765d" stroke="#d0bd87" strokeWidth=".02" />
        </g>)}
        <rect x={cx - .12} y={cy - .02} width=".24" height=".23" rx=".035" fill={BRASS} stroke="#3b3527" strokeWidth=".025" />
        <circle cx={cx} cy={cy + .065} r=".035" fill="#282b24" />
        <path d={`M${cx} ${cy + .085}v.06`} stroke="#282b24" strokeWidth=".025" />
      </g>;
    case "hearth":
      return <g>
        <rect {...frame} rx=".15" fill="#242826" stroke="#b0ac92" strokeWidth=".11" />
        {cells.map(([c, r]) => <g key={`${c},${r}`}>
          <path d={`M${c + .22} ${r + .14}v.11 M${c + .7} ${r + .14}v.11 M${c + .14} ${r + .45}h.1 M${c + .78} ${r + .65}h.1 M${c + .45} ${r + .77}v.1`} stroke="#4d5248" strokeWidth=".04" />
          <ellipse cx={c + .5} cy={r + .5} rx=".32" ry=".28" fill="#c76930" opacity=".2" />
          <path d={`M${c + .28} ${r + .6}l.44-.13 M${c + .28} ${r + .4}l.42.22`} stroke="#74432a" strokeWidth=".12" strokeLinecap="round" />
          <path d={`M${c + .29} ${r + .56}l.41-.11`} stroke="#e98e3b" strokeWidth=".025" strokeDasharray=".04 .045" />
          <path d={`M${c + .48} ${r + .22}q-.31.3-.12.44.06.05.21-.01.22-.1.03-.3l-.04.12Z`} fill="#df7f36" />
          <path d={`M${c + .49} ${r + .4}q-.17.18-.02.22.16-.03.02-.22Z`} fill="#ffe0a0" />
        </g>)}
      </g>;
    case "torch":
      if (mount) return <g data-wall-torch="true" data-wall-side={mount.side}
        transform={`translate(${mount.center[0]} ${mount.center[1]}) rotate(${mount.angle})`}>
        <path d="M-.13-.22h.26v.075h-.26Z" fill="#495044" stroke="#b29e6d" strokeWidth=".025" />
        <circle cx="-.085" cy="-.18" r=".018" fill="#d8c18c" />
        <circle cx=".085" cy="-.18" r=".018" fill="#d8c18c" />
        <path d="M0-.15v.19" stroke="#252f27" strokeWidth=".075" />
        <path d="M-.025-.13v.15" stroke="#bba475" strokeWidth=".023" />
        <ellipse cx=".025" cy=".07" rx=".14" ry=".1" fill="#101e18" opacity=".45" />
        <ellipse cy=".045" rx=".125" ry=".09" fill="#434737" stroke="#bba375" strokeWidth=".025" />
        <circle r=".18" fill="#efa84c" opacity=".12" />
        <path d="M0-.155Q-.2.035-.075.12q.1.06.17-.025Q.18.015.035-.07L.015 0Z" fill="#ed9b43" />
        <path d="M.005-.04q-.1.12-.015.15.11-.015.015-.15Z" fill="#ffe6a6" />
      </g>;
      return <g>
        <ellipse cx={cx + .06} cy={cy + .1} rx=".3" ry=".26" fill="#141c17" opacity=".55" />
        <circle cx={cx} cy={cy} r={Math.min(w, h) * .4} fill="#e4a54c" opacity=".1" />
        <circle cx={cx} cy={cy} r={Math.min(w, h) * .27} fill="#45483b" stroke="#b3a273" strokeWidth=".045" />
        <path d={`M${cx - .23} ${cy}h.46 M${cx} ${cy - .23}v.46`} stroke="#272e28" strokeWidth=".06" />
        <path d={`M${cx} ${cy - .33}C${cx - .3} ${cy} ${cx - .23} ${cy + .25} ${cx} ${cy + .25}C${cx + .3} ${cy + .23} ${cx + .15} ${cy - .1} ${cx} ${cy - .33}Z`}
          fill="#e99943" />
        <path d={`M${cx} ${cy - .04}q-.2.26-.01.24.19-.02.01-.24Z`} fill="#ffe3a3" />
        <circle cx={cx + .12} cy={cy - .23} r=".025" fill="#f7cf7d" />
      </g>;
    case "glow":
      return <g>
        <ellipse cx={cx} cy={cy} rx={w * .47} ry={h * .42} fill="#7ec6b4" opacity=".12" />
        <ellipse cx={cx} cy={cy} rx={w * .31} ry={h * .28} fill="#99d6b9" opacity=".18" />
        <path d={`M${x + w * .2} ${cy}q${w * .15} -.14 ${w * .3} 0t${w * .3} 0`} fill="none" stroke="#b4ddba" strokeWidth=".04" />
        {cells.map(([c, r]) => <g key={`${c},${r}`} fill="#d9ead1">
          <circle cx={c + .25 + variation(seed, c, r) * .4} cy={r + .35} r=".03" />
          <circle cx={c + .65} cy={r + .63} r=".02" />
        </g>)}
      </g>;
    case "lichen":
      return <g fill="#8eb99b">{cells.map(([c, r]) => <g key={`${c},${r}`}>
        <ellipse cx={c + .5} cy={r + .5} rx=".43" ry=".35" fill="#609e84" opacity=".13" />
        {[0, 1, 2, 3, 4].map((i) => <g key={i} transform={`translate(${c + .2 + variation(seed, c, r, i) * .6} ${r + .2 + variation(seed, c, r, i + 5) * .6})`}>
          <path d="M-.06.08q-.13-.08-.05-.14Q-.03-.13 0-.02q.08-.12.14-.05.07.12-.12.16Z" fill={i % 2 ? "#8eb99b" : "#659b7e"} />
          <path d="M0 .06v-.06l.07-.03" fill="none" stroke="#bfce9c" strokeWidth=".018" />
        </g>)}
      </g>)}</g>;
    case "nest":
      return <g>
        <ellipse cx={cx + .06} cy={cy + .08} rx={w * .43} ry={h * .4} fill="#141e17" opacity=".45" />
        <ellipse cx={cx} cy={cy} rx={w * .43} ry={h * .4} fill="#726549" stroke="#a39366" strokeWidth=".05" />
        <ellipse cx={cx} cy={cy} rx={w * .29} ry={h * .25} fill="#343e2c" />
        {Array.from({ length: 14 }, (_, i) => {
          const angle = i * Math.PI / 7, jitter = variation(seed, x, y, i);
          const a = cx + Math.cos(angle) * w * .35, b = cy + Math.sin(angle) * h * .32;
          return <path key={i} d={`M${a - .1} ${b - .06}l${.16 + jitter * .1} ${jitter * .12}`} stroke={i % 2 ? "#beaa76" : "#4c4b30"} strokeWidth=".03" />;
        })}
        <path d={`M${cx - .16} ${cy - .05}q.15-.15.3.03t-.31.13`} fill="none" stroke="#8a8660" strokeWidth=".035" />
      </g>;
    case "pillar":
      return <g>{cells.map(([c, r]) => <g key={`${c},${r}`}>
        <rect x={c + .12} y={r + .14} width=".84" height=".84" rx=".04" fill="#18211d" opacity=".5" />
        <rect x={c + .08} y={r + .08} width=".84" height=".84" rx=".04" fill="#636c66" stroke="#a8ad98" strokeWidth=".035" />
        <path d={`M${c + .12} ${r + .88}h.76v-.76`} fill="none" stroke="#39463f" strokeWidth=".065" />
        <circle cx={c + .5} cy={r + .5} r=".32" fill="#969a8c" stroke="#cad0bb" strokeWidth=".035" />
        <circle cx={c + .5} cy={r + .5} r=".235" fill="#7b847a" stroke="#515f55" strokeWidth=".035" />
        <path d={`M${c + .31} ${r + .45}a.2.2 0 0 1 .24-.15`} fill="none" stroke="#d0d2b8" strokeWidth=".035" />
        <path d={`M${c + .63} ${r + .67}l-.06-.12.035-.07`} fill="none" stroke="#46564b" strokeWidth=".022" />
      </g>)}</g>;
    case "rock": case "rubble":
      return <g>{cells.map(([c, r]) => {
        const n = variation(seed, c, r), size = v.form === "rubble" ? .64 : .92;
        return <g key={`${c},${r}`} transform={`translate(${c + .5} ${r + .5}) rotate(${n * 54 - 27}) scale(${size})`}>
          <path d="M-.41-.12-.23-.4.16-.38.43-.08.3.34-.08.43-.4.2Z" transform="translate(.07 .09)" fill="#15221d" opacity=".55" />
          <path d={`M-.43-.15-.23-.4.16 ${-.33 - n * .1}.43-.08.3.34-.08.43-.4.2Z`} fill={v.form === "rubble" ? "#898372" : STONE} stroke="#a6ac97" strokeWidth=".03" />
          <path d="M-.43-.15-.23-.4.16-.38.01-.07Z" fill="#c2c3a7" opacity=".5" />
          <path d="M.01-.07.43-.08.3.34-.08.43Z" fill="#354a43" opacity=".45" />
          <path d="M-.23-.4.01-.07-.4.2 M.01-.07.43-.08" fill="none" stroke="#d0ccaf" strokeWidth=".025" opacity=".7" />
          <path d={`M-.13.08l.08.13-.04.09 M.18-.18l${.04 + n * .06}.08`} fill="none" stroke="#394c44" strokeWidth=".025" />
          {v.form === "rubble" && <g>
            <path d="M-.68.18-.42.28-.5.54-.75.4Z M.36-.64.66-.49.58-.25.32-.36Z M.3.43.65.38.72.65.48.73Z" fill="#9a9179" stroke="#cdc3a1" strokeWidth=".035" />
            <path d="M-.68.18-.5.34-.75.4 M.36-.64.46-.44.58-.25 M.3.43.54.55.72.65" fill="none" stroke="#555e50" strokeWidth=".035" />
            <path d="M-.68-.34l.1-.08.07.13Z M.08.65l.09.03-.06.09Z" fill="#beb391" />
          </g>}
        </g>;
      })}</g>;
    case "tree": case "shrub":
      return <g>{cells.map(([c, r]) => {
        const n = variation(seed, c, r), tree = v.form === "tree", size = tree ? 1 : .8;
        return <g key={`${c},${r}`} transform={`translate(${c + .5} ${r + .5}) rotate(${n * 70 - 35}) scale(${size})`}>
          <ellipse cx=".07" cy=".1" rx=".43" ry=".38" fill="#12281e" opacity=".65" />
          <path d="M-.1.37.01.13.14.35 M.02.14-.18.25" fill="none" stroke="#7d6744" strokeWidth=".07" strokeLinecap="round" />
          {[0, 1, 2, 3, 4, 5, 6].map((i) => {
            const a = i * Math.PI / 3.5 + n, radius = .21 + variation(seed, c, r, i + 1) * .09;
            const px = Math.cos(a) * .22, py = Math.sin(a) * .2 - .035;
            return <g key={i}>
              <circle cx={px + .02} cy={py + .035} r={radius} fill="#203f2e" />
              <circle cx={px - .015} cy={py - .015} r={radius * .9} fill={[LEAVES, "#47714b", "#567b50", "#365f40"][i % 4]} />
              <path d={`M${px - radius * .56} ${py - radius * .13}q${radius * .15} ${-radius * .6} ${radius * .65} ${-radius * .45}`}
                fill="none" stroke="#9eac70" strokeWidth=".025" opacity=".5" strokeLinecap="round" />
            </g>;
          })}
          <path d="M-.12.03.01.1.12-.06 M.01.1l.04.15" fill="none" stroke="#b0ad78" strokeWidth=".03" opacity=".6" />
          {!tree && <g fill="#bb9a5e"><circle cx="-.19" cy="-.1" r=".03" /><circle cx=".15" cy=".18" r=".025" /><circle cx=".2" cy="-.11" r=".023" /></g>}
        </g>;
      })}</g>;
    case "reeds":
      return <g>{cells.map(([c, r]) => <g key={`${c},${r}`} transform={`translate(${c + .5} ${r + .8}) rotate(${variation(seed, c, r) * 24 - 12})`}>
        <ellipse cy=".02" rx=".27" ry=".09" fill="#233e2b" opacity=".55" />
        <path d="M0 0q-.28-.24-.31-.62 M0 0q.1-.38.3-.62 M0 0v-.68 M0 0q-.1-.4.08-.53 M0 0q.24-.2.33-.21" fill="none" stroke="#899a60" strokeWidth=".035" />
        <path d="M-.31-.54l-.015-.13 M.28-.54l.03-.13 M0-.59v-.16" stroke="#b49b66" strokeWidth=".065" strokeLinecap="round" />
        <path d="M-.02-.06q-.26-.03-.29-.2Q-.1-.26-.02-.06 M.02-.1q.24-.07.24-.25Q.07-.31.02-.1" fill="#53764b" />
      </g>)}</g>;
    case "crystal":
      return <g>{cells.map(([c, r]) => <g key={`${c},${r}`} transform={`translate(${c + .5} ${r + .5}) rotate(${variation(seed, c, r) * 40 - 20})`}>
        <ellipse cx=".06" cy=".12" rx=".34" ry=".28" fill="#163b34" opacity=".5" />
        <path d="M-.3-.02-.19-.23-.06.03-.09.31-.28.2Z M.11.1.3-.13.38.1.27.35.09.32Z" fill="#537f7a" stroke="#8ec1ad" strokeWidth=".025" />
        <path d="M0-.4.24-.1.14.32-.13.2-.26-.18Z" fill="#6fa69e" stroke="#b8ddc5" strokeWidth=".035" />
        <path d="M0-.4.03.02.14.32-.13.2Z" fill="#c0e2ca" opacity=".6" />
        <path d="M0-.4.03.02-.26-.18 M.03.02.24-.1" fill="none" stroke="#e1f0d5" strokeWidth=".025" />
      </g>)}</g>;
    case "bones":
      return <g>{cells.map(([c, r]) => <g key={`${c},${r}`} transform={`translate(${c + .5} ${r + .5}) rotate(${variation(seed, c, r) * 90 - 45})`}>
        <path d="M-.27-.2.26.24 M-.25.22.2-.22" stroke="#303a2f" strokeWidth=".12" strokeLinecap="round" transform="translate(.025 .035)" />
        <path d="M-.27-.2.26.24 M-.25.22.2-.22" stroke="#c7bda0" strokeWidth=".075" strokeLinecap="round" />
        {[[-.27, -.2], [.26, .24], [-.25, .22], [.2, -.22]].map(([a, b], i) => <g key={i} fill="#ded0ae"><circle cx={a - .025} cy={b} r=".05" /><circle cx={a + .025} cy={b - .025} r=".05" /></g>)}
        <path d="M-.02-.29q.05-.12.17-.08.12.05.06.18l-.06.05-.13-.03Z" fill="#ddd0ae" stroke="#827e65" strokeWidth=".022" />
        <path d="M.045-.24l.025.015 M.13-.22l.02.015" stroke="#4a5344" strokeWidth=".04" />
      </g>)}</g>;
    case "net":
      return <g fill="none">{cells.map(([c, r]) => <g key={`${c},${r}`}>
        <path d={`M${c + .15} ${r}l.85.85 M${c} ${r + .2}l.8.8 M${c + .5} ${r}l.5.5 M${c} ${r + .5}l.5.5 M${c} ${r + .8}l.8-.8 M${c + .2} ${r + 1}l.8-.8 M${c} ${r + .4}l.4-.4 M${c + .6} ${r + 1}l.4-.4`}
          stroke="#292e25" strokeWidth=".055" transform="translate(.025 .025)" />
        <path d={`M${c + .15} ${r}l.85.85 M${c} ${r + .2}l.8.8 M${c + .5} ${r}l.5.5 M${c} ${r + .5}l.5.5 M${c} ${r + .8}l.8-.8 M${c + .2} ${r + 1}l.8-.8 M${c} ${r + .4}l.4-.4 M${c + .6} ${r + 1}l.4-.4`}
          stroke="#bab18a" strokeWidth=".025" />
        <circle cx={c + .52} cy={r + .48} r=".04" fill="#c5b58c" />
      </g>)}</g>;
    case "crane":
      return <g fill="none">
        <WoodGrain footprint={f} seed={seed} />
        <circle cx={cx} cy={cy} r={Math.min(w, h) * .27} fill="#3a423a" stroke="#b6b397" strokeWidth=".055" />
        <circle cx={cx} cy={cy} r={Math.min(w, h) * .15} stroke="#808971" strokeWidth=".035" />
        <path d={`M${x + .2} ${y + h - .2}L${x + w - .2} ${y + .2}`} stroke="#3b2b1c" strokeWidth=".2" />
        <path d={`M${x + .2} ${y + h - .23}L${x + w - .23} ${y + .2}`} stroke="#c8a06a" strokeWidth=".12" />
        <path d={`M${x + .27} ${y + h - .22}L${x + w - .23} ${y + .27}`} stroke="#eed09b" strokeWidth=".025" />
        <circle cx={x + w - .23} cy={y + .23} r=".09" fill="#4b4f3d" stroke="#cab78a" strokeWidth=".035" />
        <path d={`M${x + w - .23} ${y + .23}v.3q.1.14.17.01`} stroke="#c9c7ab" strokeWidth=".03" />
        <circle cx={cx} cy={cy} r=".065" fill={BRASS} stroke="#4e503d" strokeWidth=".025" />
      </g>;
    case "mooring":
      return <g>
        <ellipse cx={cx + .05} cy={cy + .08} rx={w * .33} ry={h * .26} fill="#16241e" opacity=".55" />
        <ellipse cx={cx} cy={cy} rx={w * .31} ry={h * .25} fill="#47554c" stroke="#9aab93" strokeWidth=".035" />
        <path d={`M${cx - w * .26} ${cy}h${w * .52}`} stroke="#202f29" strokeWidth=".16" strokeLinecap="round" />
        <path d={`M${cx - w * .26} ${cy - .025}h${w * .52}`} stroke="#a7b39a" strokeWidth=".055" strokeLinecap="round" />
        <ellipse cx={cx} cy={cy + .03} rx={w * .2} ry={h * .16} fill="none" stroke="#bea779" strokeWidth=".06" />
        <path d={`M${cx + w * .16} ${cy + h * .12}q.15.1.22.22`} fill="none" stroke="#c7b28a" strokeWidth=".045" />
      </g>;
    case "altar":
      return <g>
        <rect {...frame} rx=".06" fill="#8b8a77" stroke="#c9c3a0" strokeWidth=".07" />
        <rect x={x + .2} y={y + .2} width={w - .4} height={h - .4} rx=".03" fill="none" stroke="#5a6758" strokeWidth=".04" />
        <path d={`M${cx - .17} ${y + .17}h.34v${h - .34}h-.34Z`} fill="#6a4d42" stroke="#baa070" strokeWidth=".025" />
        <circle cx={cx} cy={cy} r={Math.min(w, h) * .2} fill="#747b67" stroke="#ddc28a" strokeWidth=".035" />
        <path d={`M${cx} ${cy - .14}v.28 M${cx - .14} ${cy}h.28`} stroke="#e4cf96" strokeWidth=".035" />
        {[x + .28, x + w - .28].map((a) => <g key={a}>
          <circle cx={a} cy={y + .3} r=".075" fill="#484d3d" stroke={BRASS} strokeWidth=".025" />
          <circle cx={a} cy={y + .3} r=".035" fill="#ebd08b" />
          <circle cx={a - .008} cy={y + .28} r=".02" fill="#fff0ba" />
        </g>)}
      </g>;
    case "chair":
      return <g>{cells.map(([c, r]) => {
        const n = variation(seed, c, r);
        const cx = c + .5, cy = r + .5;
        if (n < .35) {
          return <g key={`${c},${r}`} transform={`translate(${cx} ${cy})`}>
            <ellipse cx=".03" cy=".05" rx=".29" ry=".27" fill="#141c17" opacity=".45" />
            <circle r=".28" fill={WOOD} stroke="#3b2b1d" strokeWidth=".04" />
            <circle r=".18" fill="none" stroke="#be935b" strokeWidth=".025" opacity=".6" />
            <circle r=".09" fill="none" stroke="#523a28" strokeWidth=".02" opacity=".5" />
            {[0, 120, 240].map((deg) => {
              const rad = (deg * Math.PI) / 180;
              return <circle key={deg} cx={Math.cos(rad) * .19} cy={Math.sin(rad) * .19} r=".025" fill={BRASS} stroke="#3b2b1d" strokeWidth=".01" />;
            })}
          </g>;
        } else if (n < .7) {
          const rot = Math.floor(variation(seed, c, r, 1) * 4) * 90;
          return <g key={`${c},${r}`} transform={`translate(${cx} ${cy}) rotate(${rot})`}>
            <rect x="-.22" y="-.18" width=".44" height=".42" rx=".05" fill="#141c17" opacity=".4" transform="translate(.03 .04)" />
            <rect x="-.22" y="-.18" width=".44" height=".42" rx=".05" fill={WOOD} stroke="#3b2b1d" strokeWidth=".035" />
            <path d="M-.18 0h.36" stroke="#5c3f25" strokeWidth=".02" />
            <path d="M-.23 -.2q.23 -.07 .46 0" fill="none" stroke="#d5ab71" strokeWidth=".06" strokeLinecap="round" />
            <path d="M-.11 -.19v.06 M0 -.21v.06 M.11 -.19v.06" stroke="#3b2b1d" strokeWidth=".025" />
          </g>;
        } else {
          const rot = Math.floor(variation(seed, c, r, 2) * 4) * 90;
          const cushionColor = n > .85 ? "#69292c" : "#2a434c";
          return <g key={`${c},${r}`} transform={`translate(${cx} ${cy}) rotate(${rot})`}>
            <rect x="-.26" y="-.24" width=".52" height=".5" rx=".07" fill="#141c17" opacity=".45" transform="translate(.04 .05)" />
            <rect x="-.26" y="-.24" width=".52" height=".5" rx=".07" fill="#2d221a" stroke="#1d1611" strokeWidth=".03" />
            <rect x="-.18" y="-.16" width=".36" height=".34" rx=".05" fill={cushionColor} stroke="#a8895b" strokeWidth=".025" />
            <rect x="-.27" y="-.16" width=".08" height=".34" rx=".03" fill={WOOD} stroke="#382516" strokeWidth=".02" />
            <rect x=".19" y="-.16" width=".08" height=".34" rx=".03" fill={WOOD} stroke="#382516" strokeWidth=".02" />
            <rect x="-.26" y="-.26" width=".52" height=".1" rx=".04" fill={WOOD} stroke="#382516" strokeWidth=".02" />
          </g>;
        }
      })}</g>;
    case "desk": {
      const n = variation(seed, x, y);
      return <g>
        <WoodGrain footprint={f} seed={seed} />
        <rect {...frame} rx=".05" fill="none" stroke="#dcb781" strokeWidth=".06" />
        <rect x={frame.x + .05} y={frame.y + .05} width={frame.width - .1} height={frame.height - .1} rx=".03" fill="none" stroke="#352618" strokeWidth=".03" opacity=".7" />
        <rect x={cx - Math.min(.38, w * .35)} y={cy - Math.min(.22, h * .35)} width={Math.min(.76, w * .7)} height={Math.min(.44, h * .7)} rx=".03" fill="#262d29" stroke="#5a685e" strokeWidth=".025" />
        {n < .35 ? <g>
          <rect x={cx - .28} y={cy - .14} width=".3" height=".24" rx=".02" fill="#ded8b8" stroke="#94876b" strokeWidth=".02" />
          <path d={`M${cx - .24} ${cy - .08}h.2 M${cx - .24} ${cy - .02}h.2 M${cx - .24} ${cy + .04}h.14`} stroke="#695e47" strokeWidth=".016" />
          <circle cx={cx + .2} cy={cy - .06} r=".05" fill="#181a1b" stroke={BRASS} strokeWidth=".015" />
          <path d={`M${cx + .2} ${cy - .06}l.08 -.14`} stroke="#d4cbaf" strokeWidth=".025" strokeLinecap="round" />
          <rect x={cx + .14} y={cy + .06} width=".16" height=".12" rx=".02" fill="#75352c" stroke="#2b1410" strokeWidth=".015" />
        </g> : n < .7 ? <g>
          <rect x={cx - .3} y={cy - .16} width=".42" height=".3" rx=".02" fill="#e8dec3" stroke="#877551" strokeWidth=".02" />
          <circle cx={cx - .1} cy={cy - .02} r=".08" fill="none" stroke="#a68e63" strokeWidth=".018" strokeDasharray=".03 .03" />
          <path d={`M${cx - .1} ${cy - .08}v.12 M${cx - .16} ${cy - .02}h.12`} stroke="#8a744e" strokeWidth=".02" />
          <path d={`M${cx + .2} ${cy - .08}l.06 .2 M${cx + .2} ${cy - .08}l-.06 .2`} stroke={BRASS} strokeWidth=".025" strokeLinecap="round" />
          <circle cx={cx + .24} cy={cy + .08} r=".045" fill={BRASS} stroke="#3b2b1d" strokeWidth=".015" />
          <circle cx={cx + .24} cy={cy + .08} r=".02" fill="#ffe3a3" />
        </g> : <g>
          <rect x={cx - .24} y={cy - .14} width=".32" height=".26" rx=".02" fill="#523927" stroke="#b08d5b" strokeWidth=".02" />
          <path d={`M${cx - .08} ${cy - .14}v.26`} stroke="#8f2b2b" strokeWidth=".02" />
          {[[-.12, .1], [.18, -.06], [.22, .02], [.16, .08]].map(([dx, dy], i) => (
            <circle key={i} cx={cx + dx} cy={cy + dy} r=".032" fill={BRASS} stroke="#42341b" strokeWidth=".012" />
          ))}
        </g>}
      </g>;
    }
    case "wardrobe": {
      const n = variation(seed, x, y);
      const horizontal = w >= h;
      return <g>
        <WoodGrain footprint={f} seed={seed} />
        <rect {...frame} rx=".05" fill="none" stroke="#2a1f16" strokeWidth=".08" />
        <rect {...frame} rx=".05" fill="none" stroke="#d5ad77" strokeWidth=".04" />
        <path d={horizontal ? `M${cx} ${y + .14}V${y + h - .14}` : `M${x + .14} ${cy}H${x + w - .14}`} stroke="#3b291a" strokeWidth=".05" />
        {n < .4 ? <g>
          {[-.1, .1].map((offset) => horizontal ? (
            <g key={offset}>
              <rect x={cx + offset * w - .12} y={cy - .2} width=".24" height=".4" rx=".03" fill="#201710" opacity=".35" />
              <circle cx={cx + (offset > 0 ? .05 : -.05)} cy={cy} r=".03" fill={BRASS} stroke="#352414" strokeWidth=".015" />
            </g>
          ) : (
            <g key={offset}>
              <rect x={cx - .2} y={cy + offset * h - .12} width=".4" height=".24" rx=".03" fill="#201710" opacity=".35" />
              <circle cx={cx} cy={cy + (offset > 0 ? .05 : -.05)} r=".03" fill={BRASS} stroke="#352414" strokeWidth=".015" />
            </g>
          ))}
        </g> : n < .75 ? <g>
          <path d={horizontal ? `M${x + .16} ${y + h - .24}H${x + w - .16}` : `M${x + w - .24} ${y + .16}V${y + h - .16}`} stroke="#3b291a" strokeWidth=".04" />
          {[[-1, -1], [1, -1], [-1, 1], [1, 1]].map(([sx, sy], i) => (
            <circle key={i} cx={cx + sx * (w * .38)} cy={cy + sy * (h * .36)} r=".03" fill={BRASS} stroke="#352414" strokeWidth=".015" />
          ))}
        </g> : <g>
          {[-.22, .22].map((pos) => horizontal ? (
            <path key={pos} d={`M${cx + pos * w} ${y + .12}V${y + h - .12}`} stroke="#3b4042" strokeWidth=".07" />
          ) : (
            <path key={pos} d={`M${x + .12} ${cy + pos * h}H${x + w - .12}`} stroke="#3b4042" strokeWidth=".07" />
          ))}
          <rect x={cx - .07} y={cy - .07} width=".14" height=".14" rx=".02" fill="#2d3336" stroke="#8fa0a8" strokeWidth=".02" />
        </g>}
      </g>;
    }
    case "weapon_rack": {
      const n = variation(seed, x, y);
      const horizontal = w >= h;
      return <g>
        <WoodGrain footprint={f} seed={seed} />
        <rect {...frame} rx=".03" fill="none" stroke="#cfa773" strokeWidth=".05" />
        {horizontal ? (
          <g>
            <path d={`M${x + .16} ${y + .22}H${x + w - .16} M${x + .16} ${y + h - .22}H${x + w - .16}`} stroke="#352618" strokeWidth=".06" />
            {n < .4 ? (
              Array.from({ length: Math.max(3, Math.floor(w * 2)) }, (_, i) => {
                const px = x + .28 + (i * (w - .56)) / (Math.max(3, Math.floor(w * 2)) - 1);
                return <g key={i}>
                  <path d={`M${px} ${y + .14}V${y + h - .14}`} stroke="#b6bfc7" strokeWidth=".045" />
                  <path d={`M${px - .06} ${y + .24}H${px + .06}`} stroke={BRASS} strokeWidth=".03" />
                  <circle cx={px} cy={y + .14} r=".025" fill={BRASS} />
                </g>;
              })
            ) : n < .75 ? (
              Array.from({ length: Math.max(2, Math.floor(w * 1.5)) }, (_, i) => {
                const px = x + .3 + (i * (w - .6)) / (Math.max(2, Math.floor(w * 1.5)) - 1);
                return <g key={i}>
                  <path d={`M${px} ${y + .12}V${y + h - .12}`} stroke="#6e5033" strokeWidth=".05" />
                  <path d={`M${px - .04} ${y + .18}L${px} ${y + .1}L${px + .04} ${y + .18}Z`} fill="#d4dde6" stroke="#48535e" strokeWidth=".015" />
                </g>;
              })
            ) : (
              <g>
                <path d={`M${cx - .3} ${cy}H${cx + .3}`} stroke="#8a6946" strokeWidth=".06" />
                <circle cx={cx} cy={cy} r=".2" fill="#5c442c" stroke="#c49b66" strokeWidth=".035" />
                <circle cx={cx} cy={cy} r=".06" fill={BRASS} stroke="#2b2014" strokeWidth=".02" />
              </g>
            )}
          </g>
        ) : (
          <g>
            <path d={`M${x + .22} ${y + .16}V${y + h - .16} M${x + w - .22} ${y + .16}V${y + h - .16}`} stroke="#352618" strokeWidth=".06" />
            {Array.from({ length: Math.max(3, Math.floor(h * 2)) }, (_, i) => {
              const py = y + .28 + (i * (h - .56)) / (Math.max(3, Math.floor(h * 2)) - 1);
              return <g key={i}>
                <path d={`M${x + .14} ${py}H${x + w - .14}`} stroke="#b6bfc7" strokeWidth=".045" />
                <path d={`M${x + .24} ${py - .06}V${py + .06}`} stroke={BRASS} strokeWidth=".03" />
                <circle cx={x + .14} cy={py} r=".025" fill={BRASS} />
              </g>;
            })}
          </g>
        )}
      </g>;
    }
    case "workbench": {
      const n = variation(seed, x, y);
      return <g>
        <WoodGrain footprint={f} seed={seed} />
        <rect {...frame} rx=".04" fill="none" stroke="#d5aa72" strokeWidth=".07" />
        <rect x={x + .08} y={y + .08} width=".14" height=".2" rx=".02" fill="#4a5054" stroke="#25292c" strokeWidth=".025" />
        <path d={`M${x + .02} ${y + .18}H${x + .16}`} stroke="#8a9499" strokeWidth=".03" />
        {n < .4 ? <g>
          <rect x={cx - .2} y={cy - .1} width=".22" height=".12" rx=".02" fill="#583f28" stroke="#1d150e" strokeWidth=".02" />
          <path d={`M${cx - .09} ${cy - .1}l-.04 -.06`} stroke="#c2ccd1" strokeWidth=".03" />
          <path d={`M${cx + .1} ${cy - .06}q.08 -.08 .14 0t.08 .06 M${cx + .06} ${cy + .08}q.06 -.06 .12 0`} fill="none" stroke="#e2be85" strokeWidth=".02" />
          <path d={`M${cx - .15} ${cy + .12}l.38 .08`} stroke="#b8c4c9" strokeWidth=".03" strokeDasharray=".04 .02" />
        </g> : n < .75 ? <g>
          <circle cx={cx - .14} cy={cy} r=".09" fill="#717a75" stroke="#353b38" strokeWidth=".025" />
          <path d={`M${cx - .14} ${cy}l.08 -.08`} stroke="#4a524e" strokeWidth=".035" strokeLinecap="round" />
          <ellipse cx={cx + .16} cy={cy + .04} rx=".08" ry=".07" fill="#609e84" opacity=".7" stroke="#b4e3ce" strokeWidth=".02" />
          <path d={`M${cx + .16} ${cy - .03}v-.08`} stroke="#b4e3ce" strokeWidth=".03" />
          <path d={`M${cx} ${cy - .14}q.06 .08 .12 .02t.08 .1`} fill="none" stroke="#5a8250" strokeWidth=".03" />
        </g> : <g>
          <circle cx={cx - .12} cy={cy - .04} r=".08" fill="none" stroke={BRASS} strokeWidth=".035" strokeDasharray=".04 .03" />
          <circle cx={cx + .04} cy={cy + .04} r=".06" fill="none" stroke={BRASS} strokeWidth=".03" strokeDasharray=".03 .025" />
          <path d={`M${cx + .18} ${cy - .12}l-.08 .2`} stroke="#6b7478" strokeWidth=".035" />
          <rect x={cx + .16} y={cy - .14} width=".08" height=".05" rx=".01" fill="#424749" />
        </g>}
      </g>;
    }
    case "anvil":
      return <g>{cells.map(([c, r]) => {
        const n = variation(seed, c, r);
        const cx = c + .5, cy = r + .5;
        return <g key={`${c},${r}`} transform={`translate(${cx} ${cy})`}>
          <ellipse cx=".04" cy=".06" rx=".39" ry=".36" fill="#141c17" opacity=".5" />
          <circle r=".37" fill="#583f28" stroke="#2f2014" strokeWidth=".05" />
          <circle r=".34" fill="none" stroke="#7a5a3a" strokeWidth=".025" />
          <circle r=".36" fill="none" stroke="#4a5054" strokeWidth=".03" />
          <path d="M-.26 -.07L-.14 -.12H.16L.24 -.08L.26 0L.24 .08L.16 .12H-.14L-.26 .07Z" fill="#3a4044" stroke="#1d2022" strokeWidth=".03" />
          <rect x="-.12" y="-.09" width=".24" height=".18" rx=".02" fill="#757e85" stroke="#b0bac2" strokeWidth=".02" />
          <path d="M.12 -.07L.25 0L.12 .07Z" fill="#88939a" />
          <rect x="-.09" y="-.03" width=".04" height=".04" fill="#1d2022" />
          <circle cx=".05" cy="0" r=".018" fill="#1d2022" />
          {n < .4 ? (
            <g transform="translate(-.12 .18) rotate(25)">
              <rect x="-.03" y="-.12" width=".06" height=".24" rx=".015" fill={WOOD} stroke="#3b2b1d" strokeWidth=".015" />
              <rect x="-.06" y="-.14" width=".12" height=".07" rx=".02" fill="#50565a" stroke="#8fa0a8" strokeWidth=".015" />
            </g>
          ) : n < .75 ? (
            <g>
              <path d="M-.08 -.02H.12" stroke="#f25822" strokeWidth=".04" strokeLinecap="round" />
              <path d="M-.06 -.02H.1" stroke="#ffc04d" strokeWidth=".02" strokeLinecap="round" />
              <circle cx=".02" cy="-.08" r=".015" fill="#ffa834" />
            </g>
          ) : (
            <path d="M-.15 .18a.07 .07 0 1 1 .14 0" fill="none" stroke="#6b7378" strokeWidth=".03" strokeLinecap="round" />
          )}
        </g>;
      })}</g>;
    case "forge": {
      const n = variation(seed, x, y);
      return <g>
        <rect {...frame} rx=".08" fill="#383d3a" stroke="#1d211e" strokeWidth=".07" />
        <rect x={frame.x + .05} y={frame.y + .05} width={frame.width - .1} height={frame.height - .1} rx=".06" fill="none" stroke="#68706b" strokeWidth=".03" />
        <rect x={cx - Math.min(.36, w * .32)} y={cy - Math.min(.26, h * .32)} width={Math.min(.72, w * .64)} height={Math.min(.52, h * .64)} rx=".04" fill="#1b120c" stroke="#0d0906" strokeWidth=".03" />
        <ellipse cx={cx} cy={cy} rx={Math.min(.3, w * .26)} ry={Math.min(.2, h * .24)} fill="#cf4c17" opacity=".4" />
        <ellipse cx={cx} cy={cy} rx={Math.min(.22, w * .18)} ry={Math.min(.14, h * .16)} fill="#f07824" opacity=".6" />
        <ellipse cx={cx} cy={cy} rx={Math.min(.12, w * .1)} ry={Math.min(.08, h * .08)} fill="#ffd369" />
        {[-.14, 0, .14].map((offset) => (
          <path key={offset} d={`M${cx + offset} ${cy - .2}V${cy + .2}`} stroke="#222628" strokeWidth=".035" opacity=".7" />
        ))}
        {n < .4 ? (
          <g transform={`translate(${x + .2} ${cy})`}>
            <rect x="-.06" y="-.14" width=".12" height=".28" rx=".03" fill={WOOD} stroke="#3b2b1d" strokeWidth=".02" />
            <path d="M0 -.14v-.1" stroke="#4a5054" strokeWidth=".03" />
          </g>
        ) : n < .75 ? (
          <circle cx={cx} cy={cy} r=".1" fill="#2d3033" stroke="#e86523" strokeWidth=".025" />
        ) : (
          <rect x={x + w - .32} y={cy - .2} width=".2" height=".4" rx=".03" fill="#243f4d" stroke="#5a7d8f" strokeWidth=".025" />
        )}
      </g>;
    }
    case "cauldron":
      return <g>{cells.map(([c, r]) => {
        const n = variation(seed, c, r);
        const cx = c + .5, cy = r + .5;
        return <g key={`${c},${r}`} transform={`translate(${cx} ${cy})`}>
          <ellipse cx=".04" cy=".07" rx=".38" ry=".35" fill="#121815" opacity=".5" />
          <circle r=".36" fill="#25282a" stroke="#151718" strokeWidth=".06" />
          <circle r=".33" fill="none" stroke="#5a6066" strokeWidth=".03" />
          <path d="M-.36 -.06q-.1 .06 0 .12 M.36 -.06q.1 .06 0 .12" fill="none" stroke="#4b5156" strokeWidth=".04" />
          {n < .35 ? (
            <g>
              <circle r=".29" fill="#784421" />
              <ellipse cx="-.06" cy="-.06" rx=".08" ry=".06" fill="#d97d38" />
              <ellipse cx=".08" cy=".08" rx=".07" ry=".05" fill="#d9c884" />
              <circle cx=".04" cy="-.12" r=".04" fill="#a85828" />
              <path d="M-.18 .16L.22 -.24" stroke="#9e7547" strokeWidth=".045" strokeLinecap="round" />
            </g>
          ) : n < .75 ? (
            <g>
              <circle r=".29" fill="#2e8550" />
              <circle cx="-.06" cy="-.08" r=".07" fill="#7ceb97" opacity=".8" />
              <circle cx=".12" cy="-.02" r=".05" fill="#7ceb97" opacity=".8" />
              <circle cx="-.02" cy=".12" r=".06" fill="#a2ffd0" opacity=".9" />
              <path d="M-.1 -.05q.15 -.12 .2 0t-.12 .14" fill="none" stroke="#b6ffe0" strokeWidth=".025" opacity=".8" />
            </g>
          ) : (
            <g>
              <circle r=".29" fill="#1c2624" />
              <path d="M-.14 -.04q.1 .08 .28 -.02" fill="none" stroke="#415952" strokeWidth=".03" />
              <circle cx="-.04" cy=".06" r=".03" fill="#2f423d" />
            </g>
          )}
        </g>;
      })}</g>;
    case "chandelier":
      return <g>{cells.map(([c, r]) => {
        const n = variation(seed, c, r);
        const cx = c + .5, cy = r + .5;
        return <g key={`${c},${r}`} transform={`translate(${cx} ${cy})`}>
          <circle r=".45" fill="#efa84c" opacity=".12" />
          <circle r=".08" fill="#2e2b24" stroke={BRASS} strokeWidth=".025" />
          {n < .45 ? (
            <g>
              {[0, 60, 120, 180, 240, 300].map((deg) => {
                const rad = (deg * Math.PI) / 180;
                const px = Math.cos(rad) * .32, py = Math.sin(rad) * .32;
                return <g key={deg}>
                  <path d={`M0 0Q${px * .4} ${py * .7} ${px} ${py}`} fill="none" stroke={BRASS} strokeWidth=".03" />
                  <circle cx={px} cy={py} r=".05" fill="#3b321e" stroke={BRASS} strokeWidth=".015" />
                  <circle cx={px} cy={py} r=".025" fill="#ffb347" />
                  <circle cx={px} cy={py} r=".012" fill="#fff5cc" />
                </g>;
              })}
            </g>
          ) : n < .8 ? (
            <g>
              <circle r=".34" fill="none" stroke="#373c3f" strokeWidth=".045" />
              <path d="M-.34 0H.34 M0 -.34V.34" stroke="#583f28" strokeWidth=".03" />
              {[[-.24, 0], [.24, 0], [0, -.24], [0, .24]].map(([px, py], i) => (
                <g key={i}>
                  <rect x={px - .03} y={py - .03} width=".06" height=".06" fill="#ded9c8" stroke="#373c3f" strokeWidth=".015" />
                  <circle cx={px} cy={py} r=".025" fill="#ff9933" />
                  <circle cx={px} cy={py} r=".012" fill="#fff2b2" />
                </g>
              ))}
            </g>
          ) : (
            <g>
              <polygon points="0,-.34 .29,-.17 .29,.17 0,.34 -.29,.17 -.29,-.17" fill="none" stroke={BRASS} strokeWidth=".035" />
              <circle r=".18" fill="#ffe099" opacity=".25" />
              <circle r=".06" fill="#ffd15c" />
            </g>
          )}
        </g>;
      })}</g>;
    case "brazier":
      return <g>{cells.map(([c, r]) => {
        const n = variation(seed, c, r);
        const cx = c + .5, cy = r + .5;
        return <g key={`${c},${r}`} transform={`translate(${cx} ${cy})`}>
          <ellipse cx=".04" cy=".07" rx=".38" ry=".35" fill="#141c17" opacity=".5" />
          <circle r=".44" fill="#efa84c" opacity=".14" />
          {[30, 150, 270].map((deg) => {
            const rad = (deg * Math.PI) / 180;
            return <path key={deg} d={`M${Math.cos(rad) * .28} ${Math.sin(rad) * .28}L${Math.cos(rad) * .42} ${Math.sin(rad) * .42}`} stroke="#222527" strokeWidth=".06" strokeLinecap="round" />;
          })}
          <circle r=".34" fill="#323438" stroke="#18191b" strokeWidth=".05" />
          <circle r=".31" fill="none" stroke="#686f75" strokeWidth=".025" />
          {n < .4 ? (
            <g>
              <circle r=".26" fill="#b84518" />
              <ellipse cx="-.03" cy="-.02" rx=".18" ry=".15" fill="#f28e2b" />
              <ellipse cx="0" cy="-.04" rx=".1" ry=".08" fill="#ffe894" />
              <path d="M-.08 .08Q-.15 -.12 0 -.22Q.15 -.12 .08 .08Z" fill="#ff771c" />
            </g>
          ) : n < .75 ? (
            <g>
              <circle r=".26" fill="#2d1610" />
              {[[-.1, -.06], [.08, -.08], [-.04, .08], [.1, .06], [0, 0]].map(([px, py], i) => (
                <circle key={i} cx={px} cy={py} r=".06" fill={i % 2 ? "#e84e1b" : "#ff8f3d"} />
              ))}
              <path d="M-.12 .04q.14 -.18 .24 0" fill="none" stroke="#8c9196" strokeWidth=".03" opacity=".5" />
            </g>
          ) : (
            <g>
              <circle r=".26" fill="#122a33" />
              <ellipse cx="0" cy="0" rx=".18" ry=".15" fill="#2ca8ba" />
              <ellipse cx="0" cy="-.03" rx=".1" ry=".08" fill="#94f5ff" />
            </g>
          )}
        </g>;
      })}</g>;
    case "statue":
      return <g>{cells.map(([c, r]) => {
        const n = variation(seed, c, r);
        const cx = c + .5, cy = r + .5;
        return <g key={`${c},${r}`} transform={`translate(${cx} ${cy})`}>
          <ellipse cx=".05" cy=".07" rx=".36" ry=".33" fill="#141c17" opacity=".5" />
          <rect x="-.32" y="-.32" width=".64" height=".64" rx=".06" fill="#585e5b" stroke="#323835" strokeWidth=".04" />
          <rect x="-.25" y="-.25" width=".5" height=".5" rx=".04" fill="#717a75" stroke="#9da6a1" strokeWidth=".025" />
          {n < .35 ? (
            <g>
              <ellipse cx="0" cy=".02" rx=".2" ry=".12" fill="#88928d" stroke="#383d3b" strokeWidth=".02" />
              <circle cx="0" cy="-.06" r=".09" fill="#9ba5a0" stroke="#383d3b" strokeWidth=".02" />
              <path d="M0 -.13v.14" stroke="#383d3b" strokeWidth=".02" />
              <circle cx="-.15" cy=".05" r=".09" fill="#69736e" stroke="#cad4cf" strokeWidth=".025" />
              <path d="M.12 -.1v.24 M.07 -.04h.1" stroke="#cbd5d0" strokeWidth=".03" strokeLinecap="round" />
            </g>
          ) : n < .75 ? (
            <g>
              <path d="M-.18 .18C-.2 -.05 -.15 -.18 0 -.18C.15 -.18 .2 -.05 .18 .18Z" fill="#818b86" stroke="#3c4240" strokeWidth=".02" />
              <circle cx="0" cy="-.08" r=".085" fill="#6b7570" stroke="#3c4240" strokeWidth=".02" />
              <rect x="-.1" y=".04" width=".2" height=".12" rx=".02" fill="#d9d4c1" stroke="#4d4739" strokeWidth=".018" />
              <path d="M0 .04v.12" stroke="#4d4739" strokeWidth=".018" />
            </g>
          ) : (
            <g>
              <ellipse cx="0" cy="0" rx=".18" ry=".13" fill="#858f8a" stroke="#3c4240" strokeWidth=".02" />
              <path d="M-.08 -.12l.06 .1l-.04 .1" fill="none" stroke="#252a28" strokeWidth=".025" />
              <circle cx=".1" cy="-.06" r=".05" fill="#5b7a54" />
              <circle cx="-.1" cy=".08" r=".04" fill="#5b7a54" />
            </g>
          )}
        </g>;
      })}</g>;
    case "fountain": {
      const n = variation(seed, x, y);
      return <g>
        <ellipse cx={cx + .05} cy={cy + .08} rx={w * .44} ry={h * .42} fill="#141c17" opacity=".45" />
        <rect {...frame} rx={Math.min(w, h) * .4} fill="#5d6360" stroke="#2e3330" strokeWidth=".08" />
        <rect {...frame} rx={Math.min(w, h) * .4} fill="none" stroke="#9da6a1" strokeWidth=".04" />
        <rect x={frame.x + .14} y={frame.y + .14} width={frame.width - .28} height={frame.height - .28} rx={Math.min(w, h) * .35} fill="#264c5e" stroke="#5ca6ba" strokeWidth=".03" />
        <ellipse cx={cx} cy={cy} rx={w * .26} ry={h * .24} fill="none" stroke="#88d5e8" strokeWidth=".025" opacity=".6" />
        <ellipse cx={cx} cy={cy} rx={w * .18} ry={h * .16} fill="none" stroke="#b6ecf7" strokeWidth=".025" opacity=".7" />
        <circle cx={cx} cy={cy} r={Math.min(w, h) * .12} fill="#727c78" stroke="#323835" strokeWidth=".03" />
        <circle cx={cx} cy={cy} r={Math.min(w, h) * .05} fill="#b4f0fc" />
        {n < .35 ? (
          <g>
            {[45, 135, 225, 315].map((deg) => {
              const rad = (deg * Math.PI) / 180;
              return <circle key={deg} cx={cx + Math.cos(rad) * w * .2} cy={cy + Math.sin(rad) * h * .18} r=".03" fill="#ffffff" opacity=".8" />;
            })}
          </g>
        ) : n < .75 ? (
          <g>
            <ellipse cx={cx - w * .16} cy={cy - h * .12} rx=".08" ry=".06" fill="#386644" />
            <ellipse cx={cx + w * .18} cy={cy + h * .1} rx=".07" ry=".05" fill="#386644" />
            <circle cx={cx - w * .16} cy={cy - h * .12} r=".02" fill="#ffffff" />
          </g>
        ) : (
          <g>
            {[[-.12, -.08], [.14, -.06], [.08, .12], [-.1, .1]].map(([dx, dy], i) => (
              <circle key={i} cx={cx + dx * w} cy={cy + dy * h} r=".03" fill={BRASS} stroke="#4a3e21" strokeWidth=".01" />
            ))}
          </g>
        )}
      </g>;
    }
    case "well": {
      const n = variation(seed, x, y);
      const rad = Math.min(w, h) * .42;
      return <g>
        <ellipse cx={cx + .05} cy={cy + .08} rx={rad + .02} ry={rad} fill="#141c17" opacity=".5" />
        <circle cx={cx} cy={cy} r={rad} fill="#565d5a" stroke="#252a28" strokeWidth=".07" />
        <circle cx={cx} cy={cy} r={rad - .03} fill="none" stroke="#9ca7a2" strokeWidth=".03" />
        <circle cx={cx} cy={cy} r={rad * .7} fill="#142129" stroke="#0b1317" strokeWidth=".04" />
        <ellipse cx={cx} cy={cy + .04} rx={rad * .45} ry={rad * .3} fill="#243f4f" opacity=".6" />
        <rect x={cx - w * .46} y={cy - .07} width={w * .92} height=".14" rx=".03" fill={WOOD} stroke="#3b291a" strokeWidth=".03" />
        <rect x={cx - .12} y={cy - .06} width=".24" height=".12" rx=".02" fill="#c2aa7c" stroke="#52432a" strokeWidth=".02" />
        {n < .4 ? (
          <g>
            <circle cx={cx + rad * .65} cy={cy - .1} r=".09" fill={WOOD} stroke="#3b2b1d" strokeWidth=".025" />
            <path d={`M${cx + rad * .65 - .08} ${cy - .1}h.16`} stroke="#4a5054" strokeWidth=".02" />
          </g>
        ) : n < .75 ? (
          <g>
            <rect x={cx - w * .44} y={cy - .18} width={w * .88} height=".36" rx=".04" fill="#7a5538" stroke="#3b2515" strokeWidth=".03" opacity=".9" />
            <path d={`M${cx - w * .42} ${cy}H${cx + w * .42}`} stroke="#4a2e19" strokeWidth=".03" />
          </g>
        ) : (
          <g transform={`translate(${cx + w * .44} ${cy})`}>
            <circle r=".05" fill="#4a5054" stroke="#1d2022" strokeWidth=".02" />
            <path d="M0 0l.08 .08" stroke="#889296" strokeWidth=".03" strokeLinecap="round" />
          </g>
        )}
      </g>;
    }
    case "sarcophagus": {
      const n = variation(seed, x, y);
      const horizontal = w >= h;
      return <g>
        <rect {...frame} rx=".06" fill="#4d5350" stroke="#252927" strokeWidth=".07" />
        <rect x={frame.x + .05} y={frame.y + .05} width={frame.width - .1} height={frame.height - .1} rx=".04" fill="#69716d" stroke="#9ba49f" strokeWidth=".03" />
        {n < .4 ? (
          <g>
            {horizontal ? (
              <g>
                <circle cx={x + .35} cy={cy} r=".14" fill="#88928d" stroke="#3d4440" strokeWidth=".02" />
                <path d={`M${x + .26} ${cy}h.08 M${x + .48} ${cy - .1}L${cx + .2} ${cy + .06} M${x + .48} ${cy + .1}L${cx + .2} ${cy - .06}`} stroke="#3d4440" strokeWidth=".03" />
                <path d={`M${cx} ${cy}H${x + w - .3}`} stroke="#b0bac0" strokeWidth=".04" strokeLinecap="round" />
              </g>
            ) : (
              <g>
                <circle cx={cx} cy={y + .35} r=".14" fill="#88928d" stroke="#3d4440" strokeWidth=".02" />
                <path d={`M${cx} ${y + .26}v.08 M${cx - .1} ${y + .48}L${cx + .06} ${cy + .2} M${cx + .1} ${y + .48}L${cx - .06} ${cy + .2}`} stroke="#3d4440" strokeWidth=".03" />
                <path d={`M${cx} ${cy}V${y + h - .3}`} stroke="#b0bac0" strokeWidth=".04" strokeLinecap="round" />
              </g>
            )}
          </g>
        ) : n < .75 ? (
          <g>
            <path d={horizontal ? `M${x + .3} ${cy}H${x + w - .3}` : `M${cx} ${y + .3}V${y + h - .3}`} stroke="#38403c" strokeWidth=".035" />
            {[[-.25, -.08], [0, .08], [.25, -.08]].map(([dx, dy], i) => (
              <circle key={i} cx={cx + (horizontal ? dx * w : dy * w)} cy={cy + (horizontal ? dy * h : dx * h)} r=".04" fill="#2d3330" stroke="#7e8884" strokeWidth=".015" />
            ))}
          </g>
        ) : (
          <g>
            <rect x={frame.x + .08} y={frame.y + .08} width={frame.width - .16} height={Math.min(.25, frame.height * .4)} fill="#0f1412" />
            <path d={`M${x + .2} ${y + .15}l.1 .15`} stroke="#b0bac0" strokeWidth=".03" />
          </g>
        )}
      </g>;
    }
    case "tombstone":
      return <g>{cells.map(([c, r]) => {
        const n = variation(seed, c, r);
        const cx = c + .5, cy = r + .5;
        return <g key={`${c},${r}`} transform={`translate(${cx} ${cy})`}>
          <ellipse cx=".04" cy=".08" rx=".34" ry=".22" fill="#141c17" opacity=".45" />
          <ellipse cx="0" cy=".12" rx=".26" ry=".14" fill="#2d261e" opacity=".6" />
          {n < .35 ? (
            <g>
              <path d="M-.18 .12V-.06C-.18 -.18 .18 -.18 .18 -.06V.12Z" fill="#6e7570" stroke="#353b37" strokeWidth=".035" />
              <path d="M-.1 .02H.1 M-.08 -.06H.08" stroke="#353b37" strokeWidth=".02" />
            </g>
          ) : n < .75 ? (
            <g>
              <path d="M-.06 .16V-.2H.06V.16Z M-.18 -.1H.18V-.02H-.18Z" fill="#78807b" stroke="#353b37" strokeWidth=".03" />
              <circle cx="0" cy="-.06" r=".08" fill="none" stroke="#9aa39e" strokeWidth=".02" />
            </g>
          ) : (
            <g transform="rotate(-15)">
              <rect x="-.16" y="-.16" width=".32" height=".28" rx=".03" fill="#636a66" stroke="#303533" strokeWidth=".03" />
              <path d="M-.08 -.16l.06 .14l-.04 .1" fill="none" stroke="#252927" strokeWidth=".02" />
              <circle cx=".08" cy=".04" r=".04" fill="#5b7a54" />
            </g>
          )}
        </g>;
      })}</g>;
    case "cart": {
      const n = variation(seed, x, y);
      const horizontal = w >= h;
      return <g>
        {horizontal ? (
          <path d={`M${x + .1} ${cy}H${x - .12}`} stroke="#4a3520" strokeWidth=".06" strokeLinecap="round" />
        ) : (
          <path d={`M${cx} ${y + .1}V${y - .12}`} stroke="#4a3520" strokeWidth=".06" strokeLinecap="round" />
        )}
        <rect x={cx - Math.min(.4, w * .35)} y={cy - Math.min(.3, h * .35)} width={Math.min(.8, w * .7)} height={Math.min(.6, h * .7)} rx=".04" fill={WOOD} stroke="#352618" strokeWidth=".06" />
        <rect x={cx - Math.min(.36, w * .32)} y={cy - Math.min(.26, h * .32)} width={Math.min(.72, w * .64)} height={Math.min(.52, h * .64)} rx=".03" fill="none" stroke="#cfa773" strokeWidth=".03" />
        {horizontal ? (
          <g>
            <rect x={cx - .2} y={cy - Math.min(.36, h * .4)} width=".4" height=".08" rx=".02" fill="#2d3235" stroke="#121516" strokeWidth=".02" />
            <rect x={cx - .2} y={cy + Math.min(.28, h * .32)} width=".4" height=".08" rx=".02" fill="#2d3235" stroke="#121516" strokeWidth=".02" />
          </g>
        ) : (
          <g>
            <rect x={cx - Math.min(.36, w * .4)} y={cy - .2} width=".08" height=".4" rx=".02" fill="#2d3235" stroke="#121516" strokeWidth=".02" />
            <rect x={cx + Math.min(.28, w * .32)} y={cy - .2} width=".08" height=".4" rx=".02" fill="#2d3235" stroke="#121516" strokeWidth=".02" />
          </g>
        )}
        {n < .4 ? (
          <g>
            <rect x={cx - .2} y={cy - .15} width=".22" height=".22" rx=".02" fill="#755639" stroke="#352414" strokeWidth=".02" />
            <circle cx={cx + .14} cy={cy} r=".12" fill="#583f28" stroke="#2a1c0e" strokeWidth=".025" />
          </g>
        ) : n < .75 ? (
          <g>
            <rect x={cx - .28} y={cy - .2} width=".56" height=".4" rx=".06" fill="#9c947d" stroke="#524d3e" strokeWidth=".03" />
            <path d={`M${cx - .28} ${cy - .08}L${cx + .28} ${cy + .08} M${cx - .28} ${cy + .08}L${cx + .28} ${cy - .08}`} stroke="#3b372a" strokeWidth=".02" />
          </g>
        ) : (
          <g>
            <ellipse cx={cx} cy={cy} rx=".28" ry=".18" fill="#d9be6f" />
            <path d={`M${cx - .2} ${cy}q.15 -.08 .35 .04 M${cx - .15} ${cy + .06}q.2 .06 .3 -.02`} stroke="#ab9044" strokeWidth=".02" />
          </g>
        )}
      </g>;
    }
    case "cage":
      return <g>{cells.map(([c, r]) => {
        const n = variation(seed, c, r);
        const cx = c + .5, cy = r + .5;
        return <g key={`${c},${r}`} transform={`translate(${cx} ${cy})`}>
          <ellipse cx=".03" cy=".05" rx=".38" ry=".38" fill="#141c17" opacity=".45" />
          <rect x="-.34" y="-.34" width=".68" height=".68" rx=".06" fill="#1b2022" opacity=".7" stroke="#3a4044" strokeWidth=".06" />
          {[-.2, -.07, .07, .2].map((pos) => (
            <path key={pos} d={`M${pos} -.34V.34`} stroke="#6c757c" strokeWidth=".035" />
          ))}
          {[-.14, .14].map((pos) => (
            <path key={pos} d={`M-.34 ${pos}H.34`} stroke="#4a5054" strokeWidth=".03" />
          ))}
          {n < .35 ? (
            <path d="M.2 -.15l.12 .3" stroke="#8fa0a8" strokeWidth=".04" strokeLinecap="round" />
          ) : n < .75 ? (
            <g>
              <ellipse cx="0" cy=".12" rx=".18" ry=".1" fill="#7a6b47" opacity=".6" />
              <circle cx="-.08" cy="-.06" r=".04" fill="none" stroke="#8fa0a8" strokeWidth=".02" />
            </g>
          ) : (
            <g transform="translate(.08 .08)">
              <path d="M-.06 -.04l.12 .08 M-.04 .06l.08 -.12" stroke="#c7bda0" strokeWidth=".03" strokeLinecap="round" />
            </g>
          )}
        </g>;
      })}</g>;
    case "carpet": {
      const n = variation(seed, x, y);
      const horizontal = w >= h;
      return <g>
        <rect x={frame.x + .03} y={frame.y + .04} width={frame.width} height={frame.height} rx=".03" fill="#080e0b" opacity=".4" />
        {n < .35 ? (
          <g>
            <rect {...frame} rx=".03" fill="#852222" stroke="#c79d38" strokeWidth=".05" />
            <rect x={frame.x + .08} y={frame.y + .08} width={frame.width - .16} height={frame.height - .16} rx=".02" fill="#691616" stroke="#e0be67" strokeWidth=".025" />
            <polygon points={`${cx},${cy - Math.min(.25, h * .25)} ${cx + Math.min(.35, w * .35)},${cy} ${cx},${cy + Math.min(.25, h * .25)} ${cx - Math.min(.35, w * .35)},${cy}`} fill="#243640" stroke="#e0be67" strokeWidth=".025" />
            {horizontal ? (
              <g stroke="#d8cfa8" strokeWidth=".025" strokeDasharray=".03 .025">
                <path d={`M${frame.x} ${frame.y}V${frame.y + frame.height}`} />
                <path d={`M${frame.x + frame.width} ${frame.y}V${frame.y + frame.height}`} />
              </g>
            ) : (
              <g stroke="#d8cfa8" strokeWidth=".025" strokeDasharray=".03 .025">
                <path d={`M${frame.x} ${frame.y}H${frame.x + frame.width}`} />
                <path d={`M${frame.x} ${frame.y + frame.height}H${frame.x + frame.width}`} />
              </g>
            )}
          </g>
        ) : n < .75 ? (
          <g>
            <rect {...frame} rx=".03" fill="#213c59" stroke="#c2d4e6" strokeWidth=".05" />
            <rect x={frame.x + .07} y={frame.y + .07} width={frame.width - .14} height={frame.height - .14} rx=".02" fill="#172b40" stroke="#7da1c4" strokeWidth=".02" />
            <circle cx={cx} cy={cy} r={Math.min(w, h) * .2} fill="none" stroke="#c2d4e6" strokeWidth=".03" strokeDasharray=".04 .03" />
          </g>
        ) : (
          <g>
            <rect {...frame} rx=".04" fill="#525e3b" stroke="#a3b380" strokeWidth=".045" />
            <ellipse cx={cx} cy={cy} rx={w * .35} ry={h * .32} fill="#3b4528" stroke="#879964" strokeWidth=".03" />
          </g>
        )}
      </g>;
    }
    case "stump":
      return <g>{cells.map(([c, r]) => {
        const n = variation(seed, c, r);
        const cx = c + .5, cy = r + .5;
        return <g key={`${c},${r}`} transform={`translate(${cx} ${cy})`}>
          <ellipse cx=".04" cy=".06" rx=".39" ry=".37" fill="#12281e" opacity=".5" />
          <circle r=".37" fill="#4d3826" stroke="#251a11" strokeWidth=".05" />
          <circle r=".31" fill="#9e754a" stroke="#6b4c2b" strokeWidth=".025" />
          <circle r=".22" fill="none" stroke="#75502c" strokeWidth=".02" opacity=".7" />
          <circle r=".13" fill="none" stroke="#75502c" strokeWidth=".02" opacity=".7" />
          <path d="M0 0l.18 .12 M0 0l-.14 .16 M0 0l-.06 -.2" stroke="#3d2816" strokeWidth=".02" />
          {n < .35 ? (
            <circle r=".05" fill="#c79b6b" />
          ) : n < .75 ? (
            <g>
              <circle cx="0" cy=".02" r=".08" fill="#26180c" />
              <path d="M.32 -.12q.08 .06 0 .12" fill="#d99f59" stroke="#784818" strokeWidth=".015" />
            </g>
          ) : (
            <g transform="rotate(30)">
              <rect x="-.02" y="-.26" width=".04" height=".4" rx=".01" fill="#d6cfb8" stroke="#423420" strokeWidth=".015" />
              <path d="M-.02 -.04L-.12 .06L-.02 .12Z" fill="#b0bac2" stroke="#353c40" strokeWidth=".02" />
            </g>
          )}
        </g>;
      })}</g>;
    case "log": {
      const n = variation(seed, x, y);
      const horizontal = w >= h;
      return <g>
        {horizontal ? (
          <g>
            <ellipse cx={cx + .05} cy={cy + .08} rx={w * .44} ry=".26" fill="#12281e" opacity=".5" />
            <rect x={x + .15} y={cy - .2} width={w - .3} height=".4" rx=".08" fill="#543c26" stroke="#261a0f" strokeWidth=".05" />
            <path d={`M${x + .25} ${cy - .08}H${x + w - .25} M${x + .2} ${cy + .08}H${x + w - .2}`} stroke="#382515" strokeWidth=".03" />
            <ellipse cx={x + .16} cy={cy} rx=".06" ry=".18" fill="#997046" stroke="#261a0f" strokeWidth=".02" />
            <ellipse cx={x + w - .16} cy={cy} rx=".06" ry=".18" fill="#997046" stroke="#261a0f" strokeWidth=".02" />
            {n > .4 && n < .75 && (
              <g>
                <circle cx={cx - .2} cy={cy - .15} r=".08" fill="#486b42" />
                <circle cx={cx + .15} cy={cy - .16} r=".06" fill="#486b42" />
                <circle cx={cx} cy={cy - .19} r=".04" fill="#c98d36" />
              </g>
            )}
          </g>
        ) : (
          <g>
            <ellipse cx={cx + .05} cy={cy + .08} rx=".26" ry={h * .44} fill="#12281e" opacity=".5" />
            <rect x={cx - .2} y={y + .15} width=".4" height={h - .3} rx=".08" fill="#543c26" stroke="#261a0f" strokeWidth=".05" />
            <path d={`M${cx - .08} ${y + .25}V${y + h - .25} M${cx + .08} ${y + .2}V${y + h - .2}`} stroke="#382515" strokeWidth=".03" />
            <ellipse cx={cx} cy={y + .16} rx=".18" ry=".06" fill="#997046" stroke="#261a0f" strokeWidth=".02" />
            <ellipse cx={cx} cy={y + h - .16} rx=".18" ry=".06" fill="#997046" stroke="#261a0f" strokeWidth=".02" />
          </g>
        )}
      </g>;
    }
    case "mushrooms":
      return <g>{cells.map(([c, r]) => {
        const n = variation(seed, c, r);
        const cx = c + .5, cy = r + .5;
        return <g key={`${c},${r}`} transform={`translate(${cx} ${cy})`}>
          <ellipse cx=".02" cy=".05" rx=".38" ry=".32" fill="#141c17" opacity=".4" />
          {n < .35 ? (
            <g>
              {[[-.14, -.08, .16], [.12, -.04, .14], [-.02, .14, .18], [.15, .15, .11]].map(([mx, my, rad], i) => (
                <g key={i}>
                  <circle cx={mx} cy={my} r={rad} fill="#b52828" stroke="#4a0f0f" strokeWidth=".02" />
                  <circle cx={mx - rad * .3} cy={my - rad * .3} r={rad * .25} fill="#f0ece1" />
                  <circle cx={mx + rad * .2} cy={my - rad * .2} r={rad * .2} fill="#f0ece1" />
                  <circle cx={mx} cy={my + rad * .25} r={rad * .2} fill="#f0ece1" />
                </g>
              ))}
            </g>
          ) : n < .75 ? (
            <g>
              <circle r=".4" fill="#1fb5a2" opacity=".2" />
              {[[-.12, -.06, .15], [.1, -.08, .13], [0, .12, .17], [.16, .1, .1]].map(([mx, my, rad], i) => (
                <g key={i}>
                  <ellipse cx={mx} cy={my} rx={rad} ry={rad * .85} fill="#1fb5a2" stroke="#5effea" strokeWidth=".025" />
                  <circle cx={mx} cy={my} r={rad * .4} fill="#a8fff3" />
                </g>
              ))}
            </g>
          ) : (
            <g>
              {[[-.15, -.06, .15], [.12, -.08, .14], [-.02, .12, .16], [.14, .12, .12]].map(([mx, my, rad], i) => (
                <g key={i}>
                  <ellipse cx={mx} cy={my} rx={rad} ry={rad * .8} fill="#c98d36" stroke="#52350f" strokeWidth=".02" />
                  <circle cx={mx} cy={my} r={rad * .3} fill="#e5b060" />
                </g>
              ))}
            </g>
          )}
        </g>;
      })}</g>;
    case "sack":
      return <g>{cells.map(([c, r]) => {
        const n = variation(seed, c, r);
        const cx = c + .5, cy = r + .5;
        return <g key={`${c},${r}`} transform={`translate(${cx} ${cy})`}>
          <ellipse cx=".04" cy=".06" rx=".36" ry=".32" fill="#141c17" opacity=".45" />
          {n < .35 ? (
            <g>
              <ellipse cx="0" cy=".02" rx=".28" ry=".24" fill="#a88d67" stroke="#3b2e1e" strokeWidth=".03" />
              <path d="M-.15 .02q.15 -.06 .3 0" stroke="#755e3f" strokeWidth=".02" />
              <circle cx="-.08" cy="-.18" r=".05" fill="#8c7352" stroke="#3b2e1e" strokeWidth=".015" />
              <circle cx=".08" cy="-.18" r=".05" fill="#8c7352" stroke="#3b2e1e" strokeWidth=".015" />
              <rect x="-.06" y="-.16" width=".12" height=".05" rx=".015" fill="#ded0b6" stroke="#4d3b24" strokeWidth=".015" />
            </g>
          ) : n < .75 ? (
            <g>
              <ellipse cx="-.1" cy="-.06" rx=".2" ry=".16" fill="#9e8460" stroke="#3b2e1e" strokeWidth=".025" />
              <ellipse cx=".1" cy="-.04" rx=".2" ry=".16" fill="#a88d67" stroke="#3b2e1e" strokeWidth=".025" />
              <ellipse cx="0" cy=".12" rx=".22" ry=".17" fill="#bfa57e" stroke="#3b2e1e" strokeWidth=".025" />
              <circle cx="-.1" cy="-.18" r=".04" fill="#6e5739" />
              <circle cx=".12" cy="-.16" r=".04" fill="#6e5739" />
            </g>
          ) : (
            <g>
              <ellipse cx="-.06" cy="-.02" rx=".24" ry=".2" fill="#9e8460" stroke="#3b2e1e" strokeWidth=".025" />
              <ellipse cx=".15" cy=".06" rx=".14" ry=".1" fill="#e0c572" stroke="#6e5c2b" strokeWidth=".02" />
              <circle cx=".12" cy=".04" r=".02" fill="#fff0ba" />
              <circle cx=".18" cy=".08" r=".018" fill="#fff0ba" />
            </g>
          )}
        </g>;
      })}</g>;
    default: {
      const distance = ([c, r]: [number, number]) => (c + .5 - cx) ** 2 + (r + .5 - cy) ** 2;
      const [c, r] = [...cells].sort((a, b) => distance(a) - distance(b) || a[1] - b[1] || a[0] - b[0])[0];
      return <MapGlyph name={v.glyph} x={c + .15} y={r + .15} width={.7} height={.7} color={v.color} />;
    }
  }
}

export function MapFeature({ feature, idPrefix, onFeature, torchMounts }: {
  feature: SketchFeature; idPrefix: string; onFeature?: (id: string, name: string) => void;
  torchMounts?: (WallTorchMount | undefined)[];
}) {
  const visual = featureVisual(feature);
  const wood = ["table", "bench", "bed", "counter", "shelf", "barrel", "crate", "chest", "crane", "chair", "desk", "wardrobe", "weapon_rack", "workbench", "cart"].includes(visual.form);
  const natural = ["tree", "shrub", "reeds", "stump", "log", "mushrooms"].includes(visual.form);
  const loose = natural || ["barrel", "pillar", "rock", "rubble", "crystal", "bones", "net", "mooring", "torch", "glow", "lichen", "nest", "bench", "chair", "anvil", "cauldron", "chandelier", "brazier", "statue", "fountain", "well", "tombstone", "cart", "cage", "carpet", "sack"].includes(visual.form);
  const color = wood ? WOOD : natural ? "#294f38" : ["rock", "rubble", "pillar", "altar", "hearth", "anvil", "forge", "statue", "fountain", "well", "sarcophagus", "tombstone"].includes(visual.form) ? STONE : visual.form === "carpet" ? "#852222" : visual.color;
  const activate = feature.entity_id && onFeature ? () => onFeature(feature.entity_id!, feature.name) : undefined;
  const seed = feature.id ?? feature.entity_id ?? visual.form;
  return <g data-feature-id={feature.entity_id ?? feature.id} data-feature-solid={feature.solid ? "true" : undefined}
    role={activate ? "button" : undefined} tabIndex={activate ? 0 : undefined} aria-label={activate ? feature.name : undefined}
    onClick={activate} onKeyDown={activate ? (event) => {
      if (event.key === "Enter" || event.key === " ") { event.preventDefault(); activate(); }
    } : undefined}>
    {featureFootprints(feature.cells).map((footprint, index) => {
      const clipId = `${idPrefix}-${index}`;
      return <g key={index} data-feature-form={visual.form}>
        <defs><clipPath id={clipId}><path d={footprint.path} fillRule="evenodd" /></clipPath></defs>
        {!loose && <path d={footprint.path} fillRule="evenodd" fill="#080f0c" opacity=".42" transform="translate(.08 .11)" pointerEvents="none" />}
        <path d={footprint.path} fillRule="evenodd" fill={color} opacity={loose ? "0" : ".95"}
          stroke={loose ? "none" : "#202823"} strokeWidth=".06" strokeLinejoin="round"
          data-feature-body="true" data-footprint-area={footprint.cells.length} />
        <g clipPath={`url(#${clipId})`} pointerEvents="none"><Artwork footprint={footprint} visual={visual} seed={seed} mount={torchMounts?.[index]} /></g>
        {feature.solid && !loose && <path d={footprint.path} fillRule="evenodd" fill="none" stroke="#e2cf9f" opacity=".2" strokeWidth=".03" pointerEvents="none" />}
      </g>;
    })}
    <title>{feature.name}</title>
  </g>;
}
