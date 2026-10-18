/** Texture stays beneath the tactical grid and never changes occupied cells. */
export function SketchMaterials({ idPrefix, material, rough = false }: { idPrefix: string; material: string; rough?: boolean }) {
  return <>
    <pattern id={`${idPrefix}-pattern-${material}`} width="4" height="4" patternUnits="userSpaceOnUse">
      <rect width="4" height="4" fill={`var(--tf-map-${material}, var(--tf-map-floor, #3b3b3b))`} />
      {material === "wood" ? <g>
        <path d="M0 .5h4 M0 1.5h4 M0 2.5h4 M0 3.5h4 M1 .5v1 M3 1.5v1 M1.7 2.5v1 M3.4 3.5v1 M3.4 0v.5"
          stroke="#16120f" strokeWidth=".04" opacity=".55" />
        <path d="M.2 .65h2.1 M1.3 1.65h2.4 M.3 2.65h1 M2 3.65h1.7" stroke="#d4b080" strokeWidth=".025" opacity=".22" />
        <path d="M.4 .9q.6-.12 1.5 0 M1.5 2.9q.6-.1 1.2 0" stroke="#bba27e" strokeWidth=".025" opacity=".15" fill="none" />
      </g> : material === "stone" && rough ? <g fill="none" strokeWidth=".025">
        <path d="M.2 .9l.6-.15.6.25.35-.45 M.8 .75l.1-.55 M1.4 1l-.15.45.3.35 M2.7 2.7l.2-.45.65.15.3-.1 M2.9 2.25l-.3-.35 M.3 3.1l.25.1.3-.15"
          stroke="#a4ada0" opacity=".14" />
        <path d="M2.2 .6l.3.14 M.6 2.2h.2 M2 3.6h.3 M3.2 1.6l.15.1" stroke="#101a1a" opacity=".28" strokeWidth=".07" />
      </g> : material === "stone" ? <g fill="none">
        <path d="M0 0H4V2H0Z M0 2H4V4H0 M2 0v2 M1 2v2 M3 2v2" stroke="#090d11" strokeWidth=".05" opacity=".3" />
        <path d="M.12 .12h1.7 M2.12 .12h1.7 M1.12 2.12h1.7 M.5 1.2l.12.13.2-.05 M2.6 3.2l.16-.18.24.04"
          stroke="#bcc4bd" strokeWidth=".025" opacity=".16" />
      </g> : material === "water" ? <g fill="none" strokeWidth=".035">
        <path d="M-.5 .8q.5-.24 1 0t1 0t1 0t1 0t1 0 M-.2 2.6q.5-.2 1 0t1 0t1 0t1 0"
          stroke="var(--tf-map-water-mark, #78b4c855)" />
        <path d="M.3 1.2q.35-.14.7 0 M2.1 3q.35-.14.7 0" stroke="#a1d3d7" opacity=".23" />
        <path d="M0 2q1-.24 2 0t2 0" stroke="#10232e" opacity=".25" strokeWidth=".12" />
      </g> : material === "grass" ? <g fill="none" stroke="#8ba36b" strokeWidth=".025" opacity=".3">
        <path d="M.3 .8l.1-.2.08.2 M2.4 1.7l.07-.26.13.2 M1.5 3.5l.1-.23.09.18 M3.4 3.2l.05-.2.1.13" />
        <path d="M.4 2.4h.14 M2.8 .4h.18 M3 2.4h.12" strokeWidth=".05" />
      </g> : <g fill="none" stroke="#b3a184" strokeWidth=".025" opacity=".23">
        <path d="M.4 .7l.16-.08.14.1 M2.4 1.6l.12.08 M1.4 3.2l.16-.13.17.06 M3.2 3.2h.2" />
        <circle cx="1.4" cy="1.6" r=".04" /><circle cx="3.3" cy=".5" r=".035" />
      </g>}
    </pattern>
    <pattern id={`${idPrefix}-tactical-grid`} width="1" height="1" patternUnits="userSpaceOnUse">
      <path d="M1 0H0V1" fill="none" stroke="var(--tf-map-mark, #ffffff18)" strokeWidth=".022" />
    </pattern>
    <pattern id={`${idPrefix}-bridge-planks`} width="1" height="1" patternUnits="userSpaceOnUse">
      <rect width="1" height="1" fill="var(--tf-map-bridge, #8a623c)" />
      <path d="M0 .08h1 M0 .5h1 M0 .92h1" stroke="#d6bb8b" strokeWidth=".035" opacity=".45" />
      <path d="M0 0h1 M0 1h1" stroke="#302a23" strokeWidth=".05" />
    </pattern>
  </>;
}
