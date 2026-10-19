import { useQuery } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import ConnectionBanner from "../components/ConnectionBanner";
import Header from "../components/Header";
import ChatFeed from "../game/ChatFeed";
import LocationHeader from "../game/LocationHeader";
import { sceneLighting } from "../game/scenePresentation";
import { loadReadingMode, saveReadingMode } from "../game/scenePreferences";
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
import MapWindow, { MapButton } from "../game/MapWindow";
import MasterPanel from "../master/MasterPanel";
import { PartyPanel, ScenePanel } from "../game/Panels";
import PauseOverlay from "../game/PauseOverlay";
import ReactionPanel from "../game/ReactionPanel";
import RestVotePanel from "../game/RestVotePanel";
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
  const scene = useGame((s) => s.scene);
  const setTheme = useSession((s) => s.setTheme);
  const [tab, setTab] = useState<Tab>("chat");
  const [reading, setReading] = useState(loadReadingMode);
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
  const mode = useSession((s) => s.mode);
  const lighting = sceneLighting(scene?.presentation, mode, scene?.mode === "combat");
  const manage = !!card?.is_owner || master;

  const side = (
    <>
      {master && <MasterPanel campaignId={id} />}
      <ScenePanel onReturnToStory={() => setTab("chat")} />
      {!master && <About card={card} />}
    </>
  );

  return (
    <div className={`tf-game-atmosphere flex h-dvh flex-col bg-bg ${reading ? `tf-reading-mode tf-reading-${tab}` : ""}`} style={lighting}>
      <Header>
        <Link
          className="btn btn-outline-copper h-8 px-2.5 text-xs font-mono tracking-wider flex items-center gap-1 shrink-0"
          to="/"
          aria-label="К столам"
        >
          <span>←</span>
          <span className="hidden sm:inline">К СТОЛАМ</span>
        </Link>
      </Header>

      {/* Полоса стола кампании: полное название, статус и сгруппированные действия стола */}
      <div className="border-b border-line bg-surface/85 px-3 py-2 sm:px-6 md:px-8 flex flex-wrap items-center justify-between gap-3 shrink-0 backdrop-blur-xs">
        <div className="flex items-center gap-2.5 min-w-0">
          <span className="hidden font-mono text-[10px] uppercase tracking-wider text-accent sm:inline font-semibold">
            Кампания
          </span>
          <h1 className="font-heading text-base sm:text-lg font-bold text-ink leading-tight">
            {snapshot?.campaign.name ?? card?.name ?? ""}
          </h1>
          <span
            className={`shrink-0 rounded-full border px-2.5 py-0.5 font-mono text-[11px] items-center gap-1.5 inline-flex ${
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
        </div>

        {/* Мобильные компактные кнопки (карта + звук) */}
        <div className="ml-auto flex items-center gap-1.5 rounded-[10px] border border-line bg-raised/70 p-1 md:hidden shrink-0">
          <MapButton />
          <SoundControl />
        </div>

        {/* Десктопные группы кнопок управления */}
        <div className="ml-auto hidden items-center gap-2.5 md:flex shrink-0">
          {/* Инструменты стола */}
          <div
            className="flex items-center gap-1.5 rounded-[10px] border border-line bg-raised/70 p-1 shrink-0"
            role="group"
            aria-label="Инструменты стола"
          >
            <button
              type="button"
              className={`btn h-8 px-2.5 text-xs transition-colors shrink-0 ${reading ? "btn-primary" : "btn-outline-copper"}`}
              aria-pressed={reading}
              title={reading ? "Вернуть боковые панели" : "Скрыть боковые панели для чтения"}
              onClick={() => {
                const next = !reading;
                setReading(next);
                saveReadingMode(next);
                setTab("chat");
              }}
            >
              {reading ? "Вернуть панели" : "Режим чтения"}
            </button>
            <MapButton />
            <SoundControl />
          </div>

          {/* Управление сессией */}
          <SessionControls campaignId={id} compact />

          {/* Кабинет кампании */}
          {manage && (
            <div
              className="flex items-center gap-1.5 rounded-[10px] border border-line bg-raised/70 p-1 shrink-0"
              role="group"
              aria-label="Управление кампанией"
            >
              <Link
                className="btn btn-outline-copper h-8 px-3 text-xs font-mono tracking-wider shrink-0"
                to={`/c/${id}/manage`}
                title="Кабинет кампании: сюжет, участники, правила и мир"
              >
                КАБИНЕТ
              </Link>
            </div>
          )}
        </div>
      </div>

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
        className={`tf-game-layout mx-auto grid min-h-0 w-full max-w-[115rem] flex-1 gap-3 md:gap-4 px-3 md:px-6 py-3 md:py-4 ${
          master
            ? "md:grid-cols-[1fr_20rem] lg:grid-cols-[15rem_1fr_21rem]"
            : "md:grid-cols-[1fr_16rem] lg:grid-cols-[15rem_1fr_16rem]"
        }`}
      >
        <aside className="tf-party-sidebar hidden min-h-0 flex-col gap-4 overflow-y-auto lg:flex">
          <PartyPanel />
        </aside>

        <main
          className={`tf-story-panel relative min-h-0 flex-col overflow-hidden md:flex md:rounded-[12px] md:border md:border-line md:bg-surface shadow-md ${
            tab === "chat" ? "flex" : "hidden"
          }`}
        >
          <LocationHeader scene={scene} />
          <CombatStrip />
          <ChatFeed campaignId={id} />
          <VotePanel />
          <RestVotePanel />
          <ReactionPanel />
          <HeroHud />
          <Composer />
          <PauseOverlay campaignId={id} controls={<SessionControls campaignId={id} />} />
        </main>

        <aside
          className={`tf-scene-sidebar min-h-0 flex-col gap-4 overflow-y-auto p-4 md:flex md:p-0 ${
            tab === "chat" ? "hidden" : "flex"
          }`}
        >
          <div className={`tf-sidebar-party flex flex-col gap-4 lg:hidden ${tab === "scene" ? "hidden md:flex" : ""}`}>
            <div className="flex flex-wrap items-center gap-2 md:hidden">
              <SessionControls campaignId={id} className="flex-wrap" />
              {manage && (
                <Link className="btn btn-outline-copper text-xs font-mono" to={`/c/${id}/manage`}>
                  Кабинет
                </Link>
              )}
            </div>
            <PartyPanel />
          </div>
          <div className={`tf-sidebar-scene flex flex-col gap-4 ${tab === "party" ? "hidden md:flex" : ""}`}>{side}</div>
        </aside>
      </div>

      {/* Mobile Navigation Tabs */}
      <nav
        className="tf-game-tabs grid grid-cols-3 border-t border-line bg-surface md:hidden font-mono text-xs"
        aria-label="Разделы игрового экрана"
      >
        {TABS.map(([t, name]) => (
          <button
            key={t}
            className={`py-3 text-center transition-colors duration-150 ease-out ${
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
      <MapWindow />
      <FallenScene builderHref={`/c/${id}/hero`} />
    </div>
  );
}
