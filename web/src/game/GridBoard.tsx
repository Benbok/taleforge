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

export function cleanShort(label: string, maxLen: number): string {
  if (label.length <= maxLen) return label;
  const firstWord = label.split(" ")[0];
  if (firstWord.length <= maxLen && firstWord.length >= 3) return firstWord;
  return `${label.slice(0, Math.max(3, maxLen - 1))}…`;
}

/** Подпись помещается, если под значком свободно.
 *  Возвращает подходящую длину подписи: при близких соседях подпись укорачивается,
 *  чтобы надписи двух соседних значков не слипались. */
export function fitLabel(
  label: string | undefined,
  occupied: Set<string>,
  col: number,
  row: number,
  isHero = false,
): string | undefined {
  if (!label) return undefined;
  // Если клетка прямо под значком занята — места под подпись нет
  if (occupied.has(`${col},${row + 1}`)) return undefined;

  // Проверяем соседей на расстоянии 1 и 2 клеток по горизонтали
  const hasNeighbor1 = occupied.has(`${col - 1},${row}`) || occupied.has(`${col + 1},${row}`);
  const hasNeighbor2 = occupied.has(`${col - 2},${row}`) || occupied.has(`${col + 2},${row}`);

  if (hasNeighbor1) {
    // Вплотную стоит другой значок: показываем имя только у героя и очень кратко
    return isHero ? cleanShort(label, 6) : undefined;
  }

  if (hasNeighbor2) {
    // Сосед через одну клетку: сокращаем до 8 символов, чтобы надписи не слипались
    return cleanShort(label, 8);
  }

  // Свободно вокруг
  return cleanShort(label, 14);
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
  selected,
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
  selected?: boolean;
  onClick?: (e: MouseEvent<Element>) => void;
  ariaLabel: string;
}) {
  const r = size * 0.42;
  return (
    <g
      className="group cursor-pointer"
      onClick={onClick}
      role="button"
      aria-label={ariaLabel}
      tabIndex={0}
    >
      <title>{ariaLabel}</title>

      {/* Кольцо выбора активной цели */}
      {selected && (
        <g aria-hidden="true">
          <circle
            cx={cx}
            cy={cy}
            r={r + 3.5}
            fill="none"
            stroke="var(--tf-accent, #c98a4b)"
            strokeWidth={1.2}
            strokeDasharray="3 2"
          />
          <circle
            cx={cx}
            cy={cy}
            r={r + 2}
            fill="none"
            stroke="var(--tf-accent, #c98a4b)"
            strokeWidth={0.8}
            strokeOpacity={0.6}
          />
        </g>
      )}

      {/* Основной диск токена */}
      <circle
        cx={cx}
        cy={cy}
        r={r}
        fill={dashed ? "var(--color-surface, #222)" : color}
        fillOpacity={faded ? 0.35 : 1}
        stroke={ring ? "var(--color-ink, #ddd)" : dashed ? color : "rgba(0,0,0,0.4)"}
        strokeWidth={ring ? 1.5 : 1}
        strokeDasharray={dashed ? "2 2" : undefined}
        className="transition-transform duration-150 group-hover:scale-105"
        style={{ transformOrigin: `${cx}px ${cy}px` }}
      />

      {/* Внутренний ободок фишки */}
      {!dashed && (
        <circle
          cx={cx}
          cy={cy}
          r={Math.max(1, r - 1.4)}
          fill="none"
          stroke="rgba(255, 255, 255, 0.22)"
          strokeWidth={0.5}
          className="pointer-events-none"
        />
      )}

      {/* Иконка внутри токена */}
      <text
        x={cx}
        y={cy + r * 0.45}
        textAnchor="middle"
        fontSize={r * 1.15}
        fill={dashed ? color : "var(--color-bg, #111)"}
        fontWeight="bold"
        className="pointer-events-none select-none"
      >
        {icon}
      </text>

      {/* Подпись токена на сетке с защитным ореолом */}
      {label && (
        <text
          x={cx}
          y={cy + r + 7}
          textAnchor="middle"
          fontSize={7}
          fontWeight={500}
          fill="var(--color-ink, #ddd)"
          paintOrder="stroke"
          stroke="var(--color-surface, #17181c)"
          strokeWidth={2.5}
          strokeLinejoin="round"
          className="pointer-events-none select-none"
        >
          {label}
        </text>
      )}

      {/* Бейдж высоты/укрытия */}
      {badge && (
        <text
          x={cx + r}
          y={cy - r + 2}
          fontSize={7.5}
          fill="var(--color-warn, #d9a441)"
          paintOrder="stroke"
          stroke="var(--color-surface, #17181c)"
          strokeWidth={2}
          strokeLinejoin="round"
          className="pointer-events-none select-none"
        >
          {badge}
        </text>
      )}

      {/* Всплывающий тултип при наведении */}
      <g
        className="pointer-events-none opacity-0 transition-opacity duration-150 group-hover:opacity-100"
        aria-hidden="true"
      >
        <rect
          x={cx - Math.min(ariaLabel.length * 2.8 + 6, 60)}
          y={cy - r - 13}
          width={Math.min(ariaLabel.length * 5.6 + 12, 120)}
          height={11}
          rx={3}
          fill="var(--color-surface, #17181c)"
          stroke="var(--tf-accent, #c98a4b)"
          strokeWidth={0.8}
          filter="drop-shadow(0 2px 4px rgba(0,0,0,0.3))"
        />
        <text
          x={cx}
          y={cy - r - 5}
          textAnchor="middle"
          fontSize={6.5}
          fontWeight={600}
          fill="var(--color-ink, #eee)"
        >
          {short(ariaLabel, 22)}
        </text>
      </g>
    </g>
  );
}
