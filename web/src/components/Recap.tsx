import { useLayoutEffect, useRef, useState } from "react";

/** «Ранее в кампании…»: длинный пересказ свёрнут до нескольких строк, кнопка раскрывает его целиком.
 *  Кнопка появляется, только когда текст правда не поместился. */
export default function Recap({ text, className = "", clamp = "line-clamp-3" }: { text: string; className?: string; clamp?: string }) {
  const ref = useRef<HTMLParagraphElement | null>(null);
  const [open, setOpen] = useState(false);
  const [overflows, setOverflows] = useState(false);

  useLayoutEffect(() => {
    const el = ref.current;
    if (!el || open) return;
    const check = () => setOverflows(el.scrollHeight > el.clientHeight + 1);
    check();
    const ro = typeof ResizeObserver !== "undefined" ? new ResizeObserver(check) : null;
    ro?.observe(el);
    return () => ro?.disconnect();
  }, [text, open]);

  return (
    <div className="flex flex-col items-start gap-1">
      <p ref={ref} className={`${className} ${open ? "" : clamp}`}>
        «{text.replace(/^«|»$/g, "")}»
      </p>
      {(overflows || open) && (
        <button
          type="button"
          className="font-mono text-xs text-accent hover:text-accent-hi"
          aria-expanded={open}
          onClick={(e) => {
            e.preventDefault();
            e.stopPropagation();
            setOpen((v) => !v);
          }}
        >
          {open ? "Свернуть" : "Читать полностью"}
        </button>
      )}
    </div>
  );
}
