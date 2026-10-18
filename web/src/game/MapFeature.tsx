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
  const wood = ["table", "bench", "bed", "counter", "shelf", "barrel", "crate", "chest", "crane"].includes(visual.form);
  const natural = ["tree", "shrub", "reeds"].includes(visual.form);
  const loose = natural || ["barrel", "pillar", "rock", "rubble", "crystal", "bones", "net", "mooring", "torch", "glow", "lichen", "nest", "bench"].includes(visual.form);
  const color = wood ? WOOD : natural ? "#294f38" : ["rock", "rubble", "pillar", "altar", "hearth"].includes(visual.form) ? STONE : visual.color;
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
