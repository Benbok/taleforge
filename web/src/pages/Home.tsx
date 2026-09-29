import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import ActionButton from "../components/ActionButton";
import CampaignCardView from "../components/CampaignCardView";
import Header from "../components/Header";
import { api } from "../lib/api";
import type { LibraryHero } from "../lib/builder";
import { actionOf, GROUP_TITLES, groupCards } from "../lib/cards";
import type { CampaignCard } from "../lib/types";
import { useSession } from "../stores/session";

export default function Home() {
  const user = useSession((s) => s.user)!;
  const isAdmin = user.platform_role !== "player";
  const cards = useQuery({
    queryKey: ["my-campaigns"],
    queryFn: () => api<CampaignCard[]>("/api/me/campaigns"),
    refetchInterval: 30000,
  });
  const list = cards.data ?? [];
  const next = list.find((c) => c.session_live && actionOf(c).label === "Продолжить");

  return (
    <>
      <Header>
        {isAdmin && (
          <Link className="btn btn-primary px-3 py-1" to="/new">
            Новая кампания
          </Link>
        )}
      </Header>
      <main className="mx-auto flex max-w-6xl flex-col gap-8 px-4 py-6">
        {next && (
          <section className="card flex flex-wrap items-center justify-between gap-3 border-accent p-4">
            <div>
              <p className="text-muted">Идёт сессия</p>
              <p className="text-xl font-semibold">{next.name}</p>
            </div>
            <Link to={`/c/${next.id}`} className="btn btn-primary">
              Продолжить
            </Link>
          </section>
        )}
        {cards.isLoading && <p className="text-muted">Загружаем кампании…</p>}
        {cards.isError && <p className="text-bad">Не удалось загрузить кампании: {(cards.error as Error).message}</p>}
        {cards.isSuccess && list.length === 0 && (
          <section className="card p-6 text-center">
            <p className="text-lg">Пока нет ни одной кампании.</p>
            <p className="text-muted">
              {isAdmin ? "Создайте первую кнопкой «Новая кампания»." : "Попросите у владельца кампании ссылку-приглашение."}
            </p>
          </section>
        )}
        {groupCards(list).map(([group, items]) => (
          <section key={group} className="flex flex-col gap-3">
            <h2 className="text-lg text-muted">{GROUP_TITLES[group]}</h2>
            <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
              {items.map((c) => (
                <CampaignCardView key={c.id} c={c} />
              ))}
            </div>
          </section>
        ))}
        <MyHeroes />
      </main>
    </>
  );
}

/** Герои профиля: собираются заранее и берутся копией в любую кампанию. */
function MyHeroes() {
  const qc = useQueryClient();
  const heroes = useQuery({ queryKey: ["library"], queryFn: () => api<LibraryHero[]>("/api/me/characters") });
  return (
    <section className="flex flex-col gap-3" aria-label="Мои герои">
      <div className="flex items-center justify-between gap-3">
        <h2 className="text-lg text-muted">Мои герои</h2>
        <Link to="/heroes/new" className="btn px-3 py-1">
          Новый герой
        </Link>
      </div>
      {heroes.isError && <p className="text-bad">Не удалось загрузить героев: {(heroes.error as Error).message}</p>}
      {heroes.isSuccess && heroes.data.length === 0 && (
        <p className="text-sm text-muted">Соберите героя заранее, и его копию можно будет взять в любую кампанию.</p>
      )}
      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
        {(heroes.data ?? []).map((h) => (
          <div key={h.id} className="card flex items-start justify-between gap-3 p-4">
            <Link to={`/heroes/${h.id}`} className="min-w-0 text-ink no-underline hover:underline">
              <span className="block truncate font-semibold">{h.name || "Без имени"}</span>
              <span className="block text-xs text-muted">
                {[h.origin_name, h.class_name, h.errors.length ? "не закончен" : null].filter(Boolean).join(" · ") || "черновик"}
              </span>
            </Link>
            <ActionButton
              className="px-2 py-0.5 text-xs"
              title="Удалить героя из профиля"
              confirm={`Удалить «${h.name || "без имени"}» из профиля? Его копии в кампаниях останутся.`}
              run={async () => {
                await api(`/api/me/characters/${h.id}`, { method: "DELETE" });
                await qc.invalidateQueries({ queryKey: ["library"] });
              }}
              done="Герой удалён из профиля"
            >
              Удалить
            </ActionButton>
          </div>
        ))}
      </div>
    </section>
  );
}
