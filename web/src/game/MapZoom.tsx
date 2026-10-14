import { useEffect, useLayoutEffect, useRef, useState, type MouseEvent, type PointerEvent } from "react";

const MIN = 1;
const MAX = 4;
const STEP = 1.25;
const DRAG_PX = 4; // меньше — это нажатие на клетку, а не сдвиг карты

const clamp = (z: number) => Math.min(MAX, Math.max(MIN, Math.round(z * 100) / 100));

/** Масштаб схемы в прокручиваемой рамке: кнопки, Ctrl + колесо (и щипок на тачпаде) у курсора, сдвиг мышью.
 * Точка под курсором (или центр рамки для кнопок) после масштабирования остаётся на месте. */
export function useMapZoom() {
  const node = useRef<HTMLDivElement | null>(null);
  const [el, setEl] = useState<HTMLDivElement | null>(null); // рамка может появиться позже: карта книги сначала грузится
  const box = (n: HTMLDivElement | null) => {
    node.current = n;
    setEl(n);
  };
  const [zoom, setZoom] = useState(MIN);
  const current = useRef(zoom);
  current.current = zoom;
  const anchor = useRef<{ ox: number; oy: number; fx: number; fy: number } | null>(null);
  const drag = useRef<{ x: number; y: number; left: number; top: number; moved: boolean } | null>(null);

  function zoomTo(next: number, at?: { x: number; y: number }) {
    const z = clamp(next);
    const el = node.current;
    if (z === current.current) return;
    if (el) {
      const r = el.getBoundingClientRect();
      const ox = at ? at.x - r.left : el.clientWidth / 2;
      const oy = at ? at.y - r.top : el.clientHeight / 2;
      anchor.current = { ox, oy, fx: (el.scrollLeft + ox) / el.scrollWidth, fy: (el.scrollTop + oy) / el.scrollHeight };
    }
    setZoom(z);
  }

  useLayoutEffect(() => {
    const el = node.current;
    const a = anchor.current;
    if (!el || !a) return;
    anchor.current = null;
    el.scrollLeft = a.fx * el.scrollWidth - a.ox;
    el.scrollTop = a.fy * el.scrollHeight - a.oy;
  }, [zoom]);

  // колесо без Ctrl прокручивает как обычно; слушатель не пассивный, иначе браузер масштабирует страницу
  useEffect(() => {
    if (!el) return;
    const onWheel = (e: WheelEvent) => {
      if (!e.ctrlKey && !e.metaKey) return;
      e.preventDefault();
      zoomTo(current.current * Math.exp(-e.deltaY * 0.01), { x: e.clientX, y: e.clientY });
    };
    el.addEventListener("wheel", onWheel, { passive: false });
    return () => el.removeEventListener("wheel", onWheel);
  }, [el]);

  const pan = {
    onPointerDown(e: PointerEvent<HTMLDivElement>) {
      const el = node.current;
      drag.current = null;
      if (!el || e.pointerType !== "mouse" || e.button !== 0 || current.current <= MIN) return;
      drag.current = { x: e.clientX, y: e.clientY, left: el.scrollLeft, top: el.scrollTop, moved: false };
    },
    onPointerMove(e: PointerEvent<HTMLDivElement>) {
      const d = drag.current;
      const el = node.current;
      if (!d || !el || !(e.buttons & 1)) return;
      const dx = e.clientX - d.x;
      const dy = e.clientY - d.y;
      if (!d.moved && Math.hypot(dx, dy) < DRAG_PX) return;
      d.moved = true;
      el.scrollLeft = d.left - dx;
      el.scrollTop = d.top - dy;
    },
    // отпущенный после сдвига щелчок не должен вести героя в клетку или открывать предмет
    onClickCapture(e: MouseEvent<HTMLDivElement>) {
      if (drag.current?.moved) {
        e.stopPropagation();
        e.preventDefault();
      }
      drag.current = null;
    },
  };

  return { zoom, box, pan, zoomIn: () => zoomTo(current.current * STEP), zoomOut: () => zoomTo(current.current / STEP), reset: () => zoomTo(MIN) };
}

/** Кнопки масштаба над схемой. */
export function ZoomBar({ z }: { z: ReturnType<typeof useMapZoom> }) {
  const btn = "min-h-11 min-w-11 sm:min-h-9 sm:min-w-9 rounded-lg border border-line bg-surface px-2 text-ink hover:border-accent disabled:opacity-50";
  return (
    <div className="flex flex-wrap items-center gap-2 text-sm text-muted" role="group" aria-label="Масштаб карты">
      <button type="button" className={btn} onClick={z.zoomOut} disabled={z.zoom <= MIN} aria-label="Уменьшить">
        −
      </button>
      <span className="w-10 text-center" aria-live="polite">
        {Math.round(z.zoom * 100)}%
      </span>
      <button type="button" className={btn} onClick={z.zoomIn} disabled={z.zoom >= MAX} aria-label="Увеличить">
        +
      </button>
      <button type="button" className={btn} onClick={z.reset} disabled={z.zoom === MIN}>
        Сброс
      </button>
      <span className="ml-1 hidden sm:inline">Ctrl + колесо — масштаб, мышью — сдвиг</span>
    </div>
  );
}
