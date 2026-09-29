export interface PopoverStyle {
  left: number;
  top?: number;
  bottom?: number;
  maxHeight: number;
}

/**
 * Вычисляет координаты и предельную высоту всплывающей карточки относительно опорной точки (anchor),
 * гарантируя, что карточка ни при каких условиях не выйдет за границы видимого экрана.
 */
export function computePopoverPosition(
  anchor: { top: number; bottom: number; left: number; right?: number },
  options: {
    cardWidth?: number;
    padding?: number;
    windowWidth?: number;
    windowHeight?: number;
  } = {}
): PopoverStyle {
  const cardWidth = options.cardWidth ?? 340;
  const padding = options.padding ?? 12;
  const winW = options.windowWidth ?? (typeof window !== "undefined" ? window.innerWidth : 1024);
  const winH = options.windowHeight ?? (typeof window !== "undefined" ? window.innerHeight : 768);

  // Горизонтальное выравнивание с ограничением по ширине экрана
  const maxLeft = Math.max(padding, winW - cardWidth - padding);
  const left = Math.min(Math.max(padding, anchor.left), maxLeft);

  // Доступное пространство сверху и снизу
  const spaceBelow = winH - anchor.bottom - padding;
  const spaceAbove = anchor.top - padding;

  // Предпочитаем позицию снизу, если там хватает места (>= 240px) или места снизу больше, чем сверху
  if (spaceBelow >= 240 || spaceBelow >= spaceAbove) {
    const maxHeight = Math.max(140, Math.min(spaceBelow - 8, winH - padding * 2));
    return {
      left,
      top: anchor.bottom + 8,
      maxHeight,
    };
  } else {
    const maxHeight = Math.max(140, Math.min(spaceAbove - 8, winH - padding * 2));
    return {
      left,
      bottom: winH - anchor.top + 8,
      maxHeight,
    };
  }
}
