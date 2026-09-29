import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { useGame } from "../stores/game";

const SEEN = "tf-fallen-seen";

function seen(): string[] {
  try {
    return JSON.parse(localStorage.getItem(SEEN) ?? "[]");
  } catch {
    return [];
  }
}

/** Гибель своего героя — спокойная сцена, а не красная ошибка: имя, прощание и что можно делать дальше.
 *  Показывается один раз на героя. */
export default function FallenScene({ builderHref }: { builderHref: string | null }) {
  const sheet = useGame((s) => s.sheet);
  const [open, setOpen] = useState(false);
  const dead = !!sheet?.resources.dead;
  const id = sheet?.id;

  useEffect(() => {
    if (dead && id && !seen().includes(id)) setOpen(true);
  }, [dead, id]);

  if (!open || !sheet) return null;

  function close() {
    try {
      localStorage.setItem(SEEN, JSON.stringify([...seen(), sheet!.id].slice(-50)));
    } catch {
      // без хранилища сцена просто покажется ещё раз
    }
    setOpen(false);
  }

  return (
    <div className="fixed inset-0 z-40 flex items-center justify-center bg-black/70 p-4" role="dialog" aria-label="Герой пал">
      <div className="tf-pop flex w-full max-w-md flex-col items-center gap-4 rounded-lg border border-line bg-surface p-6 text-center">
        <span className="text-3xl text-muted" aria-hidden>
          ✦
        </span>
        <h2 className="font-heading text-2xl">{sheet.name} пал</h2>
        <p className="font-narration leading-relaxed text-muted">
          История героя закончилась здесь. Отряд пойдёт дальше и будет его помнить. Вы можете остаться за столом и смотреть или
          привести нового героя.
        </p>
        <div className="flex flex-wrap justify-center gap-2">
          {builderHref && (
            <Link className="btn btn-primary" to={builderHref} onClick={close}>
              Новый герой
            </Link>
          )}
          <button className="btn" onClick={close}>
            Остаться и смотреть
          </button>
        </div>
      </div>
    </div>
  );
}
