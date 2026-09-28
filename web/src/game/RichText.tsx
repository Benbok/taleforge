import { parseMarkup } from "../lib/markup";
import { useGame } from "../stores/game";
import { TYPE_COLOR, TYPE_ICON } from "./entities";
import { useInspector } from "./inspector";

/** Текст мастера с разметкой [[id|текст]]: слово подчёркнуто цветом типа, по нажатию — карточка знаний. */
export default function RichText({ text }: { text: string }) {
  const types = useGame((s) => s.types);
  const open = useInspector((s) => s.open);
  return (
    <>
      {parseMarkup(text).map((p, i) =>
        "id" in p ? (
          <button
            key={i}
            type="button"
            onClick={(e) => open(p.id, p.text, e.currentTarget)}
            className="cursor-pointer underline decoration-2 underline-offset-4 hover:bg-raised"
            style={{ textDecorationColor: types[p.id] ? TYPE_COLOR[types[p.id]] : "var(--tf-muted)" }}
            title="Что я знаю об этом?"
          >
            {p.text}
            {types[p.id] && (
              <sup className="ml-0.5 text-[0.65em] no-underline opacity-70" aria-hidden>
                {TYPE_ICON[types[p.id]]}
              </sup>
            )}
          </button>
        ) : (
          <span key={i}>{p.text}</span>
        ),
      )}
    </>
  );
}
