import { useQuery } from "@tanstack/react-query";
import { useEffect } from "react";
import { useParams } from "react-router-dom";
import ConnectionBanner from "../components/ConnectionBanner";
import UniversalAdventure from "../game/UniversalAdventure";
import type { ExplorationState } from "../game/ExplorationPanel";
import { useDraft } from "../game/draft";
import EntityPopover from "../game/EntityPopover";
import { myHero } from "../game/hero";
import MapWindow from "../game/MapWindow";
import { api } from "../lib/api";
import type { CampaignCard, HeroSheet, Theme } from "../lib/types";
import { useGameSocket } from "../lib/useGameSocket";
import { useGame } from "../stores/game";
import { useSession } from "../stores/session";

export default function GamePage() {
  const { id = "" } = useParams();
  useGameSocket(id);
  const snapshot = useGame((s) => s.snapshot);
  const exploration = useGame((s) => (s.sheet as unknown as { exploration?: ExplorationState } | null)?.exploration);
  const setTheme = useSession((s) => s.setTheme);
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
  }, [id, heroId, snapshot]);

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
  const master = snapshot?.me.role === "master";
  const manage = !!card?.is_owner || master;

  if (!snapshot) return <ConnectionBanner />;
  if (snapshot.campaign.ruleset_id !== "universal") return <p role="alert">Эта кампания использует неподдерживаемые правила.</p>;
  return <><UniversalAdventure campaignId={id} exploration={exploration} canManage={manage} /><MapWindow orientationOnly /><EntityPopover /></>;
}
