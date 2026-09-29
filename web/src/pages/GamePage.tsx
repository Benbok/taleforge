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
import MasterPanel from "../master/MasterPanel";
import { PartyPanel, ScenePanel } from "../game/Panels";
import PauseOverlay from "../game/PauseOverlay";
import ReactionPanel from "../game/ReactionPanel";
import VotePanel from "../game/VotePanel";
import SessionControls from "../game/SessionControls";
import SoundControl from "../game/SoundControl";
import { api } from "../lib/api";
import { actionOf, STATUS_TEXT, statusOf } from "../lib/cards";
import type { CampaignCard, HeroSheet, Theme } from "../lib/types";
import { useGameSocket } from "../lib/useGameSocket";
import { useGame } from "../stores/game";
import { useSession } from "../stores/session";

type Tab = "chat" | "party" | "scene";
const TABS: [Tab, string][] = [
  ["chat", "ЧАТ"],
  ["party", "ОТРЯД"],
  ["scene", "СЦЕНА"],
];

function About({ card }: { card: CampaignCard | undefined }) {
  const intro = useGame((s) => s.snapshot?.campaign.public_intro);
  if (!intro && !card?.recap) return null;
  return (
    <section className="card flex flex-col gap-2 p-4 border border-line bg-surface" aria-label="О кампании">
      <h2 className="font-heading text-base font-bold text-ink">О кампании</h2>
      {intro && <p className="font-narration text-sm leading-relaxed text-ink-2">{intro}</p>}
      {card?.recap && (
        <p className="font-narration text-sm leading-relaxed text-muted border-t border-line pt-2">
          <span className="font-mono text-xs uppercase tracking-wider text-accent block mb-0.5">
            Ранее в кампании…
          </span>
          {card.recap}
        </p>
      )}
    </section>
  );
}

/** Игровой экран. Компьютер: отряд слева, чат по центру, сцена справа. */
export default function GamePage() {
  const { id = "" } = useParams();
  useGameSocket(id);
  useTurnAlerts();
  const snapshot = useGame((s) => s.snapshot);
  const setTheme = useSession((s) => s.setTheme);
  const [tab, setTab] = useState<Tab>("chat");
  const heroes = useGame((s) => s.heroes);
  const heroId = myHero(heroes, snapshot?.me.seat_id)?.id ?? null;

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
      api<Theme>("/api/theme").then(useSession.getState().setTheme, () => undefined);
    },
    [],
  );

  const cards = useQuery({ queryKey: ["my-campaigns"], queryFn: () => api<CampaignCard[]>("/api/me/campaigns") });
  const card = cards.data?.find((c) => c.id === id);
  const heroCta = card && actionOf(card).href.endsWith("/hero") && actionOf(card).primary ? actionOf(card) : null;
  const status = card ? STATUS_TEXT[statusOf(card)] : null;
  const live = !!snapshot?.session;
  const master = snapshot?.me.role === "master";
  const manage = !!card?.is_owner || master;

  const side = (
    <>
      {master && <MasterPanel campaignId={id} />}
      <ScenePanel />
      {!master && <About card={card} />}
    </>
  );

  return (
    <div className="flex h-dvh flex-col bg-bg">
      <Header>
        <Link
          className="btn btn-outline-copper h-8 px-2.5 text-xs font-mono tracking-wider flex items-center gap-1 shrink-0"
          to="/"
          aria-label="К столам"
        >
          <span>←</span>
          <span className="hidden sm:inline">К СТОЛАМ</span>
        </Link>

        <span className="min-w-0 truncate font-heading text-lg font-bold text-ink ml-1">
          {snapshot?.campaign.name ?? card?.name ?? ""}
        </span>

        <span
          className={`hidden shrink-0 rounded-full border px-2.5 py-0.5 font-mono text-[11px] sm:inline-flex items-center gap-1.5 ${
            live
              ? "border-patina/50 bg-patina/10 text-patina-hi font-semibold"
              : "border-line bg-raised text-muted"
          }`}
        >
          {live && <span className="h-1.5 w-1.5 rounded-full bg-patina animate-pulse" />}
          <span>
            {live
              ? "ИДЁТ СЕССИЯ"
              : snapshot?.campaign.status === "ended"
                ? "ЗАВЕРШЕНА"
                : snapshot?.campaign.status === "paused"
                  ? "ПАУЗА"
                  : status}
          </span>
        </span>

        <div className="ml-auto flex items-center gap-2 md:hidden">
          <SoundControl />
        </div>
        <div className="ml-auto hidden items-center gap-2 md:flex">
          <SoundControl />
          <SessionControls campaignId={id} />
          {manage && (
            <Link className="btn btn-outline-copper h-8 px-3 text-xs font-mono tracking-wider" to={`/c/${id}/manage`}>
              КАБИНЕТ
            </Link>
          )}
        </div>
      </Header>

      <ConnectionBanner />

      {heroCta && (
        <div className="flex flex-wrap items-center justify-center gap-3 border-b border-accent/40 bg-accent/10 px-4 py-2 font-mono text-xs text-ink shadow-sm">
          <span>{heroCta.label === "Новый герой" ? "Ваш герой пал в бою." : "У вас ещё нет готового героя для этого стола."}</span>
          <Link className="btn btn-primary px-3 py-1 font-mono text-xs tracking-wider" to={heroCta.href}>
            {heroCta.label.toUpperCase()} →
          </Link>
        </div>
      )}

      <div
        className={`mx-auto grid min-h-0 w-full max-w-[96rem] flex-1 md:gap-4 md:px-4 md:py-4 ${
          master
            ? "md:grid-cols-[1fr_24rem] lg:grid-cols-[16rem_1fr_28rem]"
            : "md:grid-cols-[1fr_18rem] lg:grid-cols-[16rem_1fr_18rem]"
        }`}
      >
        <aside className="hidden min-h-0 flex-col gap-4 overflow-y-auto lg:flex">
          <PartyPanel />
        </aside>

        <main
          className={`relative min-h-0 flex-col overflow-hidden md:flex md:rounded-[12px] md:border md:border-line md:bg-surface shadow-md ${
            tab === "chat" ? "flex" : "hidden"
          }`}
        >
          <CombatStrip />
          <ChatFeed campaignId={id} />
          <VotePanel />
          <ReactionPanel />
          <HeroHud />
          <Composer />
          <PauseOverlay campaignId={id} controls={<SessionControls campaignId={id} />} />
        </main>

        <aside
          className={`min-h-0 flex-col gap-4 overflow-y-auto p-4 md:flex md:p-0 ${
            tab === "chat" ? "hidden" : "flex"
          }`}
        >
          <div className={`flex flex-col gap-4 lg:hidden ${tab === "scene" ? "hidden md:flex" : ""}`}>
            <div className="flex flex-wrap items-center gap-2 md:hidden">
              <SessionControls campaignId={id} />
              {manage && (
                <Link className="btn btn-outline-copper text-xs font-mono" to={`/c/${id}/manage`}>
                  Кабинет
                </Link>
              )}
            </div>
            <PartyPanel />
          </div>
          <div className={`flex flex-col gap-4 ${tab === "party" ? "hidden md:flex" : ""}`}>{side}</div>
        </aside>
      </div>

      {/* Mobile Navigation Tabs */}
      <nav
        className="grid grid-cols-3 border-t border-line bg-surface md:hidden font-mono text-xs"
        aria-label="Разделы игрового экрана"
      >
        {TABS.map(([t, name]) => (
          <button
            key={t}
            className={`py-3 text-center transition ${
              tab === t
                ? "border-t-2 border-accent bg-raised/50 font-bold text-accent"
                : "border-t-2 border-transparent text-muted hover:text-ink"
            }`}
            aria-current={tab === t ? "page" : undefined}
            onClick={() => setTab(t)}
          >
            {master && t === "scene" ? "МАСТЕР" : name}
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
