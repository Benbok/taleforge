import { useEffect, useState, type MouseEvent } from "react";
import { useAuthedImage } from "../lib/authedImage";
import { Token } from "./GridBoard";
import { useInspector } from "./inspector";
import { roomLabel, type MapBook } from "./map";

const W = 1000; // ширина рисунка в единицах SVG; высота — по пропорциям картинки

/** Прямоугольники клеток комнаты в единицах рисунка. */
export function roomRects(book: MapBook, cells: number[][], width: number, height: number) {
  const g = book.grid;
  if (!g) return [];
  const cw = ((g.right - g.left) / g.cols) * width;
  const ch = ((g.bottom - g.top) / g.rows) * height;
  return cells.map(([c0, r0, c1, r1]) => ({
    x: g.left * width + c0 * cw,
    y: g.top * height + r0 * ch,
    w: (c1 - c0 + 1) * cw,
    h: (r1 - r0 + 1) * ch,
  }));
}

/** Размер значка: клетка сетки книги или, без сетки, 3% ширины. */
export function tokenSize(book: MapBook, width: number): number {
  const g = book.grid;
  return g ? ((g.right - g.left) / g.cols) * width : width * 0.03;
}

/** Карта места из книги: комната отряда подсвечена, посещённые обведены, герои стоят на свободных клетках. */
export default function BookMap({ book, where }: { book: MapBook; where?: string | null }) {
  const src = useAuthedImage(`/api/modules/${book.module_id}/maps/${book.map_id}`);
  const [ratio, setRatio] = useState<number | null>(null);
  const open = useInspector((s) => s.open);

  useEffect(() => {
    if (!src) return;
    const img = new Image();
    img.onload = () => setRatio(img.naturalHeight / Math.max(1, img.naturalWidth));
    img.src = src;
  }, [src]);

  if (!src || !ratio) return <p className="text-center font-mono text-xs text-muted">Загружаю карту из книги…</p>;
  const H = W * ratio;
  const size = tokenSize(book, W);
  const here = book.rooms.find((r) => r.status === "here");

  return (
    <div className="flex flex-col gap-2">
      <p className="font-heading text-sm font-semibold text-ink">
        <span className="text-accent">⌖</span> {where ?? (here ? `${roomLabel(here)} · ${book.name}` : book.name)}
      </p>
      <svg viewBox={`0 0 ${W} ${H}`} className="w-full select-none rounded-md" role="img" aria-label={`Карта: ${book.name}`}>
        <image href={src} x={0} y={0} width={W} height={H} />
        {here?.cells &&
          roomRects(book, here.cells, W, H).map((r, i) => (
            <rect key={i} x={r.x} y={r.y} width={r.w} height={r.h} fill="var(--tf-accent)" fillOpacity={0.16} stroke="var(--tf-accent)" strokeWidth={2} />
          ))}
        {book.rooms.map((r) => (
          <circle
            key={r.number}
            cx={r.x * W}
            cy={r.y * H}
            r={size * 0.8}
            fill="none"
            stroke={r.status === "here" ? "var(--tf-accent)" : "var(--tf-patina, #5f9e8f)"}
            strokeWidth={r.status === "here" ? 4 : 2.5}
            strokeDasharray={r.status === "known" ? "6 4" : undefined}
          >
            <title>{`Комната ${r.number}${r.name ? ` «${r.name}»` : ""}`}</title>
          </circle>
        ))}
        {/* подписи комнат: номер, у знакомых — название; обводка фоном, чтобы читалось поверх рисунка */}
        {book.rooms.map((r) => (
          <text
            key={`label-${r.number}`}
            x={r.x * W}
            y={r.y * H + size * 0.8 + 18}
            textAnchor="middle"
            fontSize={18}
            fontWeight={r.status === "here" ? 700 : 500}
            fill={r.status === "here" ? "var(--tf-accent)" : "var(--color-ink, #ddd)"}
            stroke="var(--color-surface, #17181c)"
            strokeWidth={5}
            paintOrder="stroke"
            aria-hidden="true"
          >
            {roomLabel(r)}
          </text>
        ))}
        {book.tokens.map((t) => (
          <Token
            key={t.id}
            cx={t.x * W}
            cy={t.y * H}
            size={size}
            color={t.type === "creature" ? "var(--tf-ember, #c0563a)" : t.type === "npc" ? "var(--tf-patina, #5f9e8f)" : t.type === "item" ? "var(--color-copper, #b07a4a)" : "var(--tf-accent)"}
            icon={t.type === "creature" ? "⚔" : t.type === "npc" ? "●" : t.type === "item" ? "◆" : t.type === "landmark" ? "◈" : "★"}
            ring={t.mine}
            faded={t.down}
            onClick={(e: MouseEvent<Element>) => open(t.id, t.name, e.currentTarget as unknown as HTMLElement)}
            ariaLabel={`${t.name}, комната ${t.room}`}
          />
        ))}
      </svg>
      <p className="font-mono text-xs text-muted">
        {here ? `Отряд в комнате ${here.number}${here.name ? ` «${here.name}»` : ""}.` : "Отряд у этого места."} Обведены комнаты, где
        вы уже были.
      </p>
    </div>
  );
}
