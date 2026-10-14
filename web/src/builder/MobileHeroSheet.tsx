import { useEffect, useRef, useState, type ReactNode } from "react";
import { createPortal } from "react-dom";

export default function MobileHeroSheet({ summary, children }: { summary: ReactNode; children: ReactNode }) {
  const [open, setOpen] = useState(false);
  const trigger = useRef<HTMLButtonElement>(null);
  const dialog = useRef<HTMLDialogElement>(null);

  useEffect(() => {
    if (!open) return;
    const element = dialog.current;
    element?.showModal();
    const overflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    const onResize = () => { if (window.innerWidth >= 1024) setOpen(false); };
    window.addEventListener("resize", onResize);
    return () => {
      element?.close();
      document.body.style.overflow = overflow;
      window.removeEventListener("resize", onResize);
      trigger.current?.focus({ preventScroll: true });
    };
  }, [open]);

  return <>
    <button ref={trigger} type="button" aria-haspopup="dialog" aria-expanded={open}
      onClick={() => setOpen(true)}
      className="fixed inset-x-0 bottom-0 z-30 flex min-h-14 flex-wrap items-center justify-between gap-2 border-t border-line bg-surface px-4 pt-3 pb-[max(.75rem,env(safe-area-inset-bottom))] text-sm text-ink lg:hidden shadow-xl">
      {summary}<span className="font-semibold text-accent">Лист героя ↑</span>
    </button>
    {open && createPortal(
      <dialog ref={dialog} aria-label="Сводка героя" onCancel={() => setOpen(false)} onClose={() => setOpen(false)}
        onClick={(event) => { if (event.target === event.currentTarget) setOpen(false); }}
        className="tf-hero-sheet-dialog fixed inset-x-0 bottom-0 top-auto m-0 max-h-[85dvh] w-full max-w-none overflow-y-auto rounded-t-2xl border border-line bg-surface p-0 text-ink shadow-2xl">
        <div className="sticky top-0 z-10 flex items-center justify-between border-b border-line bg-surface px-4 py-3">
          <h2 className="font-heading text-xl font-bold">Сводка героя</h2>
          <button autoFocus type="button" className="btn min-h-11" onClick={() => setOpen(false)}>Закрыть</button>
        </div>
        <div className="p-3 pb-[max(.75rem,env(safe-area-inset-bottom))]">{children}</div>
      </dialog>, document.body,
    )}
  </>;
}
