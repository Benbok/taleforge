import { useQuery } from "@tanstack/react-query";
import { useEffect } from "react";
import { useParams } from "react-router-dom";
import Avatar from "../components/Avatar";
import ConnectionBanner from "../components/ConnectionBanner";
import Header from "../components/Header";
import { api } from "../lib/api";
import { actionOf, STATUS_TEXT, statusOf } from "../lib/cards";
import { plain } from "../lib/markup";
import { label } from "../lib/theme";
import type { CampaignCard, Theme } from "../lib/types";
import { useGameSocket } from "../lib/useGameSocket";
import { useGame } from "../stores/game";
import { useSession } from "../stores/session";

const STAGES: Record<string, string> = {
  listening: "Мастер слушает…",
  remembering: "Мастер вспоминает…",
  rolling: "Мастер бросает кубики…",
  describing: "Мастер описывает…",
};

/** Экран кампании. В этом обновлении — живое лобби: отряд с присутствием, вводная, «Ранее в кампании…» и
 *  последние сцены. Игровой экран переезжает сюда следующим PR, а пока игра открывается в прежнем клиенте. */
export default function CampaignPage() {
  const { id = "" } = useParams();
  useGameSocket(id);
  const { snapshot, seats, messages, masterStage } = useGame();
  const { theme, setTheme } = useSession();

  const campaignTheme = useQuery({ queryKey: ["theme", id], queryFn: () => api<Theme>(`/api/campaigns/${id}/theme`) });
  useEffect(() => {
    if (campaignTheme.data) setTheme(campaignTheme.data);
  }, [campaignTheme.data, setTheme]);
  useEffect(
    () => () => {
      // при уходе из кампании — снова базовая тема
      api<Theme>("/api/theme").then(useSession.getState().setTheme, () => undefined);
    },
    [],
  );

  const cards = useQuery({ queryKey: ["my-campaigns"], queryFn: () => api<CampaignCard[]>("/api/me/campaigns") });
  const card = cards.data?.find((c) => c.id === id);
  const scenes = messages.filter((m) => m.kind === "narration" && !m.whisper).slice(-3);
  const needsHero = !!card && actionOf(card).href.startsWith("/legacy");
  const heroBySeat = new Map(card?.party.map((m) => [m.seat_id, m.hero_name]) ?? []);

  return (
    <>
      <Header>
        <span className="hidden truncate text-muted sm:inline">{snapshot?.campaign.name ?? card?.name ?? ""}</span>
      </Header>
      <ConnectionBanner />
      <main className="mx-auto grid max-w-6xl gap-6 px-4 py-6 lg:grid-cols-[18rem_1fr]">
        <aside className="flex flex-col gap-4">
          <section className="card p-4">
            <h2 className="mb-3 text-base font-semibold">Отряд</h2>
            <ul className="flex flex-col gap-2">
              {seats
                .slice()
                .sort((a, b) => (a.role === "master" ? -1 : b.role === "master" ? 1 : a.position - b.position))
                .map((s) => (
                  <li key={s.id} className="flex items-center gap-3">
                    <Avatar
                      name={heroBySeat.get(s.id) ?? s.user_name}
                      role={s.role}
                      occupant={s.occupant_type}
                      presence={s.occupant_type === "human" ? s.presence ?? "offline" : null}
                    />
                    <span className="min-w-0">
                      <span className="block truncate">
                        {s.role === "master"
                          ? s.occupant_type === "agent"
                            ? "ИИ-мастер"
                            : `Мастер: ${s.user_name ?? "—"}`
                          : (heroBySeat.get(s.id) ?? (s.occupant_type === "empty" ? "Свободное место" : "Герой не готов"))}
                      </span>
                      {s.role === "player" && s.user_name && <span className="block text-xs text-muted">{s.user_name}</span>}
                    </span>
                  </li>
                ))}
            </ul>
          </section>
        </aside>
        <section className="flex flex-col gap-4">
          <div className="card flex flex-col gap-3 p-5">
            <div className="flex flex-wrap items-center justify-between gap-3">
              <h1 className="text-2xl font-semibold">{snapshot?.campaign.name ?? card?.name}</h1>
              {card && <span className="rounded-full border border-line px-2 py-0.5 text-xs text-muted">{STATUS_TEXT[statusOf(card)]}</span>}
            </div>
            {snapshot?.campaign.public_intro && (
              <p className="max-w-[70ch] font-narration text-lg leading-relaxed">{snapshot.campaign.public_intro}</p>
            )}
            {card?.recap && (
              <p className="max-w-[70ch] font-narration leading-relaxed">
                <span className="text-muted">Ранее в кампании… </span>
                {card.recap}
              </p>
            )}
            <div className="flex flex-wrap items-center gap-3">
              <a className="btn btn-primary" href={`/legacy?campaign=${id}`}>
                {needsHero ? "Собрать героя" : snapshot?.session ? "К игре" : "Открыть кампанию"}
              </a>
              <span className="text-xs text-muted">Новый игровой экран появится в следующем обновлении.</span>
            </div>
          </div>
          {scenes.length > 0 && (
            <div className="card flex flex-col gap-3 p-5">
              <h2 className="text-base text-muted">Последние сцены</h2>
              {scenes.map((m) => (
                <p key={m.id} className="max-w-[70ch] font-narration text-lg leading-relaxed">
                  {plain(m.content)}
                </p>
              ))}
            </div>
          )}
          {masterStage && STAGES[masterStage] && (
            <p className="text-muted" role="status">
              {label(theme, `master_status.${masterStage}`, STAGES[masterStage])}
            </p>
          )}
        </section>
      </main>
    </>
  );
}
