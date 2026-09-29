import { useQuery } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import ConnectionBanner from "../components/ConnectionBanner";
import Header from "../components/Header";
import ChatFeed from "../game/ChatFeed";
import { useTurnAlerts } from "../game/combat";
import CombatStrip from "../game/CombatStrip";
import Composer from "../game/Composer";
import { useDraft } from "../game/draft";
import EntityPopover from "../game/EntityPopover";
import ExplainPopover from "../game/ExplainPopover";
import FallenScene from "../game/FallenScene";
import { myHero } from "../game/hero";
import HeroHud from "../game/HeroHud";
import HeroWindow from "../game/HeroWindow";
import { PartyPanel, ScenePanel } from "../game/Panels";
import PauseOverlay from "../game/PauseOverlay";
import ReactionPanel from "../game/ReactionPanel";
import SessionControls from "../game/SessionControls";
import { api } from "../lib/api";
import { actionOf, STATUS_TEXT, statusOf } from "../lib/cards";
import type { CampaignCard, HeroSheet, Theme } from "../lib/types";
import { useGameSocket } from "../lib/useGameSocket";
import { useGame } from "../stores/game";
import { useSession } from "../stores/session";

type Tab = "chat" | "party" | "scene";
const TABS: [Tab, string][] = [
  ["chat", "Чат"],
  ["party", "Отряд"],
  ["scene", "Сцена"],
];

function About({ card }: { card: CampaignCard | undefined }) {
  const intro = useGame((s) => s.snapshot?.campaign.public_intro);
  if (!intro && !card?.recap) return null;
  return (
    <section className="card flex flex-col gap-2 p-4" aria-label="О кампании">
      <h2 className="text-base font-semibold">О кампании</h2>
      {intro && <p className="font-narration leading-relaxed">{intro}</p>}
      {card?.recap && (
        <p className="font-narration leading-relaxed">
          <span className="text-muted">Ранее в кампании… </span>
          {card.recap}
        </p>
      )}
    </section>
  );
}

/** Игровой экран. Компьютер: отряд слева, чат по центру, сцена справа. Планшет: чат и одна колонка сбоку.
 *  Телефон: чат во весь экран, отряд и сцена — вкладками снизу. */
export default function GamePage() {
  const { id = "" } = useParams();
  useGameSocket(id);
  useTurnAlerts();
  const snapshot = useGame((s) => s.snapshot);
  const setTheme = useSession((s) => s.setTheme);
  const [tab, setTab] = useState<Tab>("chat");
  const heroes = useGame((s) => s.heroes);
  const heroId = myHero(heroes, snapshot?.me.seat_id)?.id ?? null;

  // полный лист своего героя: при входе — REST, дальше сервер присылает character.sheet после каждого изменения
  useEffect(() => {
    if (!heroId) {
      useGame.getState().setSheet(null);
      return;
    }
    api<HeroSheet>(`/api/campaigns/${id}/characters/${heroId}`).then(
      (h) => useGame.getState().setSheet(h),
      () => useGame.getState().setSheet(null),
    );
  }, [id, heroId]);

  useEffect(() => useDraft.getState().load(id), [id]);

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
  const heroCta = card && actionOf(card).href.endsWith("/hero") && actionOf(card).primary ? actionOf(card) : null;
  const status = card ? STATUS_TEXT[statusOf(card)] : null;
  const live = !!snapshot?.session;

  const side = (
    <>
      <ScenePanel />
      <About card={card} />
    </>
  );

  return (
    <div className="flex h-dvh flex-col">
      <Header>
        <span className="min-w-0 truncate font-heading text-base">{snapshot?.campaign.name ?? card?.name ?? ""}</span>
        <span
          className={`hidden shrink-0 rounded-full border px-2 py-0.5 text-xs sm:inline ${live ? "border-ok text-ok" : "border-line text-muted"}`}
        >
          {live ? "Идёт сессия" : snapshot?.campaign.status === "ended" ? "Завершена" : snapshot?.campaign.status === "paused" ? "Пауза" : status}
        </span>
        <div className="ml-auto hidden md:block">
          <SessionControls campaignId={id} />
        </div>
      </Header>
      <ConnectionBanner />
      {heroCta && (
        <div className="flex flex-wrap items-center justify-center gap-3 border-b border-line bg-raised px-4 py-2">
          <span>{heroCta.label === "Новый герой" ? "Ваш герой пал." : "У вас ещё нет готового героя."}</span>
          <Link className="btn btn-primary px-3 py-1" to={heroCta.href}>
            {heroCta.label}
          </Link>
        </div>
      )}
      <div className="mx-auto grid min-h-0 w-full max-w-[96rem] flex-1 md:grid-cols-[1fr_18rem] md:gap-4 md:px-4 md:py-4 lg:grid-cols-[16rem_1fr_18rem]">
        <aside className="hidden min-h-0 flex-col gap-4 overflow-y-auto lg:flex">
          <PartyPanel />
        </aside>
        <main className={`relative min-h-0 flex-col overflow-hidden md:flex md:rounded-lg md:border md:border-line md:bg-surface ${tab === "chat" ? "flex" : "hidden"}`}>
          <CombatStrip />
          <ChatFeed campaignId={id} />
          <ReactionPanel />
          <HeroHud />
          <Composer />
          <PauseOverlay controls={<SessionControls campaignId={id} />} />
        </main>
        <aside
          className={`min-h-0 flex-col gap-4 overflow-y-auto p-4 md:flex md:p-0 ${tab === "chat" ? "hidden" : "flex"}`}
        >
          <div className={`flex flex-col gap-4 lg:hidden ${tab === "scene" ? "hidden md:flex" : ""}`}>
            <div className="md:hidden">
              <SessionControls campaignId={id} />
            </div>
            <PartyPanel />
          </div>
          <div className={`flex flex-col gap-4 ${tab === "party" ? "hidden md:flex" : ""}`}>{side}</div>
        </aside>
      </div>
      <nav className="grid grid-cols-3 border-t border-line bg-surface md:hidden" aria-label="Разделы">
        {TABS.map(([t, name]) => (
          <button
            key={t}
            className={`py-3 text-sm ${tab === t ? "font-semibold text-accent" : "text-muted"}`}
            aria-current={tab === t ? "page" : undefined}
            onClick={() => setTab(t)}
          >
            {name}
          </button>
        ))}
      </nav>
      <EntityPopover />
      <ExplainPopover />
      <HeroWindow />
      <FallenScene builderHref={`/c/${id}/hero`} />
    </div>
  );
}
