import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import CampaignCardView from "../components/CampaignCardView";
import Header from "../components/Header";
import { api } from "../lib/api";
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
          <a className="btn btn-primary px-3 py-1" href="/legacy" title="Создание кампании пока в прежнем клиенте">
            Новая кампания
          </a>
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
      </main>
    </>
  );
}
