import type { KeyboardEvent, MouseEvent } from "react";
import { MapGlyph } from "./MapGlyph";
import type { MapVisualPreset, TokenShape } from "./mapPresets";

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

/** Одна геометрия фишки для обеих карт. Варианты выбирает реестр, не сам компонент. */
function TokenDisc({ cx, cy, r, shape, fill, stroke, dashed, ring }: {
  cx: number;
  cy: number;
  r: number;
  shape: TokenShape;
  fill: string;
  stroke: string;
  dashed: boolean;
  ring: boolean;
}) {
  const common = {
    fill,
    stroke,
    strokeWidth: ring ? 1.7 : 1.15,
    strokeDasharray: dashed ? "2.5 2" : undefined,
  };
  if (shape === "hex") {
    const points = Array.from({ length: 6 }, (_, i) => {
      const theta = (Math.PI * i) / 3 - Math.PI / 2;
      return `${cx + Math.cos(theta) * r},${cy + Math.sin(theta) * r}`;
    }).join(" ");
    return <polygon points={points} {...common} />;
  }
  if (shape === "diamond") {
    return <rect x={cx - r * 0.74} y={cy - r * 0.74} width={r * 1.48} height={r * 1.48}
      rx={r * 0.12} transform={`rotate(45 ${cx} ${cy})`} {...common} />;
  }
  if (shape === "square") {
    return <rect x={cx - r * 0.88} y={cy - r * 0.88} width={r * 1.76} height={r * 1.76}
      rx={r * 0.28} {...common} />;
  }
  return <circle cx={cx} cy={cy} r={r} {...common} />;
}

/** Токен: форма = тип, пиктограмма = вид, цвет = семантический акцент.
 * Визуал не выбирается по имени и не меняет данные игры. */
export function Token({
  cx,
  cy,
  size,
  visual,
  label,
  badge,
  faded = false,
  ring = false,
  dashed = false,
  selected = false,
  onClick,
  ariaLabel,
}: {
  cx: number;
  cy: number;
  size: number;
  visual: MapVisualPreset;
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
  const activate = (e: KeyboardEvent<SVGGElement>) => {
    if (onClick && (e.key === "Enter" || e.key === " ")) {
      e.preventDefault();
      onClick(e as unknown as MouseEvent<Element>);
    }
  };
  return (
    <g
      className={onClick ? "group cursor-pointer outline-none" : "group"}
      onClick={onClick}
      onKeyDown={activate}
      role={onClick ? "button" : undefined}
      aria-label={ariaLabel}
      tabIndex={onClick ? 0 : undefined}
      data-map-glyph={visual.glyph}
    >
      <title>{ariaLabel}</title>

      {(selected || ring) && (
        <circle cx={cx} cy={cy} r={r + (selected ? 3.5 : 2.3)}
          fill="none" stroke={selected ? "var(--tf-accent)" : visual.color}
          strokeWidth={selected ? 1.5 : 1}
          strokeDasharray={selected ? "2.5 2" : undefined}
          className="pointer-events-none"
        />
      )}
      <g className="transition-transform duration-150 group-hover:scale-105 group-focus:scale-105"
        style={{ transformOrigin: `${cx}px ${cy}px` }}
        opacity={faded ? 0.45 : 1}>
        <TokenDisc cx={cx} cy={cy} r={r} shape={visual.shape}
          fill="var(--tf-surface, #17181c)" stroke={visual.color} dashed={dashed} ring={ring} />
        <circle cx={cx} cy={cy} r={r * 0.65} fill={visual.color} fillOpacity={dashed ? 0.06 : 0.14}
          className="pointer-events-none" />
        <MapGlyph name={visual.glyph}
          x={cx - r * 0.77} y={cy - r * 0.77}
          width={r * 1.54} height={r * 1.54}
          color={visual.color}
          className="pointer-events-none" />
      </g>

      {label && (
        <text x={cx} y={cy + r + 7} textAnchor="middle" fontSize={7} fontWeight={600}
          fill="var(--color-ink, #ddd)" paintOrder="stroke"
          stroke="var(--color-surface, #17181c)" strokeWidth={2.5}
          strokeLinejoin="round" className="pointer-events-none select-none">
          {label}
        </text>
      )}
      {badge && (
        <text x={cx + r} y={cy - r + 2} fontSize={7.5}
          fill="var(--color-warn, #d9a441)" paintOrder="stroke"
          stroke="var(--color-surface, #17181c)" strokeWidth={2}
          strokeLinejoin="round" className="pointer-events-none select-none">
          {badge}
        </text>
      )}

      <g className="pointer-events-none opacity-0 transition-opacity duration-150 group-hover:opacity-100 group-focus:opacity-100"
        aria-hidden="true">
        <rect x={cx - Math.min(ariaLabel.length * 2.8 + 6, 60)} y={cy - r - 13}
          width={Math.min(ariaLabel.length * 5.6 + 12, 120)} height={11} rx={3}
          fill="var(--color-surface, #17181c)" stroke={visual.color} strokeWidth={0.8} />
        <text x={cx} y={cy - r - 5} textAnchor="middle" fontSize={6.5} fontWeight={600}
          fill="var(--color-ink, #eee)">
          {short(ariaLabel, 22)}
        </text>
      </g>
    </g>
  );
}
