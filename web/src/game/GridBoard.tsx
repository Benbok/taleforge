import type { MouseEvent } from "react";

// Клетки и значки на них: схема «Вокруг» и (этап 3 готовых приключений) карта модуля рисуются одними деталями.
// Координаты здесь — в пикселях SVG; раскладку по клеткам делает вызывающий.

/** Сетка из cols×rows клеток размером size с левым верхним углом в (x, y). */
export function GridLines({ x, y, cols, rows, size }: { x: number; y: number; cols: number; rows: number; size: number }) {
  return (
    <g aria-hidden="true">
      {Array.from({ length: cols + 1 }, (_, i) => (
        <line
          key={`c${i}`}
          x1={x + i * size}
          x2={x + i * size}
          y1={y}
          y2={y + rows * size}
          stroke="var(--color-line, #2a2b31)"
          strokeWidth={0.6}
        />
      ))}
      {Array.from({ length: rows + 1 }, (_, i) => (
        <line
          key={`r${i}`}
          x1={x}
          x2={x + cols * size}
          y1={y + i * size}
          y2={y + i * size}
          stroke="var(--color-line, #2a2b31)"
          strokeWidth={0.6}
        />
      ))}
    </g>
  );
}

function short(s: string, n: number): string {
  return s.length > n ? `${s.slice(0, n - 1)}…` : s;
}

/** Подпись помещается, если слева, справа и под значком клетки свободны: иначе имя видно по наведению. */
export function roomForLabel(occupied: Set<string>, col: number, row: number): boolean {
  return [
    [col - 1, row],
    [col + 1, row],
    [col, row + 1],
    [col - 1, row + 1],
    [col + 1, row + 1],
  ].every(([c, r]) => !occupied.has(`${c},${r}`));
}

/** Значок в клетке: кружок с символом, подпись под ним, пометки высоты и укрытия справа сверху. */
export function Token({
  cx,
  cy,
  size,
  color,
  icon,
  label,
  badge,
  faded,
  ring,
  dashed,
  onClick,
  ariaLabel,
}: {
  cx: number;
  cy: number;
  size: number;
  color: string;
  icon: string;
  label?: string;
  badge?: string;
  faded?: boolean;
  ring?: boolean;
  dashed?: boolean;
  onClick?: (e: MouseEvent<Element>) => void;
  ariaLabel: string;
}) {
  const r = size * 0.42;
  return (
    <g className="cursor-pointer" onClick={onClick} role="button" aria-label={ariaLabel}>
      <title>{ariaLabel}</title>
      <circle
        cx={cx}
        cy={cy}
        r={r}
        fill={dashed ? "var(--color-surface, #222)" : color}
        fillOpacity={faded ? 0.35 : 1}
        stroke={ring ? "var(--color-ink, #ddd)" : dashed ? color : "none"}
        strokeWidth={ring ? 1.5 : 1.2}
        strokeDasharray={dashed ? "2 2" : undefined}
      />
      <text x={cx} y={cy + r * 0.45} textAnchor="middle" fontSize={r * 1.2} fill={dashed ? color : "var(--color-bg, #111)"}>
        {icon}
      </text>
      {label && (
        <text x={cx} y={cy + r + 8} textAnchor="middle" fontSize={7.5} fill="var(--color-ink, #ddd)">
          {short(label, 12)}
        </text>
      )}
      {badge && (
        <text x={cx + r} y={cy - r + 2} fontSize={7.5} fill="var(--color-warn, #d9a441)">
          {badge}
        </text>
      )}
    </g>
  );
}
