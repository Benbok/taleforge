import { useQueryClient } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import ActionButton from "../components/ActionButton";
import { hue, initials } from "../components/Avatar";
import { api } from "../lib/api";
import type { LibraryHero } from "../lib/builder";
export { default as WorldsSection } from "./WorldsCatalog";

import PortraitImage from "../components/PortraitImage";

export function HeroesLibrarySection({ heroes }: { heroes: LibraryHero[] }) {
  const qc = useQueryClient();

  return (
    <div className="flex flex-col gap-6">
      <div className="flex flex-wrap items-baseline justify-between gap-4 border-b border-line pb-4">
        <div>
          <h2 className="font-heading text-3xl font-semibold text-ink">
            Библиотека героев
          </h2>
          <p className="mt-1 text-sm text-muted font-ui">
            Персонажи профиля. Создаются заранее и могут отправляться копией в любые кампании.
          </p>
        </div>
        <Link to="/heroes/new" className="btn btn-primary px-4 py-2 text-sm font-semibold">
          + Собрать нового героя
        </Link>
      </div>

      {heroes.length === 0 ? (
        <div className="card p-12 text-center text-muted">
          <p className="text-lg">У вас пока нет созданных героев.</p>
          <p className="mt-1 text-sm">
            Опишите первого героя и обсудите его замысел с мастером.
          </p>
          <Link to="/heroes/new" className="btn btn-primary mt-4 min-h-11 inline-flex">
            Создать первого героя
          </Link>
        </div>
      ) : (
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {heroes.map((h) => (
            <div
              key={h.id}
              className="card flex flex-col justify-between gap-4 p-5 transition hover:border-accent"
            >
              <div className="flex items-start gap-3.5">
                <span
                  className="relative flex h-12 w-12 shrink-0 items-center justify-center overflow-hidden rounded-full border-2 border-accent text-base font-semibold"
                  style={{ background: `hsl(${hue(h.name)} 35% 32%)` }}
                >
                  {initials(h.name)}
                  {h.portrait_url && <span className='absolute inset-0'><PortraitImage key={h.portrait_url} url={h.portrait_url} name={h.name || 'Без имени'} /></span>}
                </span>
                <div className="flex min-w-0 flex-1 flex-col">
                  <Link
                    to={`/heroes/${h.id}`}
                    className="truncate font-heading text-xl font-semibold text-ink no-underline hover:text-copper transition"
                  >
                    {h.name || "Без имени"}
                  </Link>
                  <span className="text-xs text-muted font-ui">
                    {[`${h.level} уровень`]
                      .filter(Boolean)
                      .join(" · ") || "Черновик"}
                  </span>
                  {(h.errors?.length ?? 0) > 0 && (
                    <span className="mt-1 text-xs text-bad">
                      {h.errors?.length ?? 0} незаполненных параметров
                    </span>
                  )}
                </div>
              </div>

              <div className="flex items-center justify-between gap-2 border-t border-line-soft pt-3">
                <Link
                  to={`/heroes/${h.id}`}
                  className="btn h-9 px-3 text-xs font-medium"
                >
                  Редактировать
                </Link>
                <ActionButton
                  className="px-3 py-1 text-xs text-muted hover:text-bad"
                  title="Удалить героя из профиля"
                  confirm={`Удалить героя «${h.name || "без имени"}» из профиля?`}
                  run={async () => {
                    await api(`/api/me/characters/${h.id}`, { method: "DELETE" });
                    await qc.invalidateQueries({ queryKey: ["library"] });
                  }}
                  done="Герой удалён"
                >
                  Удалить
                </ActionButton>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
