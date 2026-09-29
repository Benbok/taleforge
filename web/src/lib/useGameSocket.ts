import { useEffect } from "react";
import { getToken } from "./api";
import { GameSocket, socketUrl } from "./socket";
import type { Envelope } from "./types";
import { useGame } from "../stores/game";
import { toast } from "../stores/toasts";
import { resolveToolResult } from "../master/tools";

// после этих событий доступные действия могли измениться: спрашиваем сервер, какие кнопки показать
const REFRESH_ACTIONS = new Set(["turn.changed", "scene.updated", "character.updated", "state.snapshot", "message.state", "message.withdrawn"]);

export function sideEffects(e: Envelope, sock: Pick<GameSocket, "send">): void {
  if (resolveToolResult(e)) return;
  if (e.type === "error") {
    const p = e.payload as { code?: string; message?: string };
    if (p.code !== "unauthorized") toast.error(p.message ?? "сервер отклонил действие");
  }
  if (e.type === "knowledge.revealed") toast.info(`Вы узнали больше о: ${(e.payload as { name?: string }).name ?? "…"}`);
  if (REFRESH_ACTIONS.has(e.type) && e.type !== "state.snapshot") sock.send("actions.get");
  if (e.type === "message.new") {
    const m = e.payload as { seat_id?: string | null; state?: string | null };
    if (m.state === "pending" && m.seat_id && m.seat_id === useGame.getState().snapshot?.me.seat_id) sock.send("actions.get");
  }
}

/** Одно соединение на вкладку и кампанию: открывается при входе на экран кампании, закрывается при уходе. */
export function useGameSocket(campaignId: string): void {
  useEffect(() => {
    useGame.getState().reset();
    const sock: GameSocket = new GameSocket({
      url: socketUrl(),
      token: getToken,
      campaignId,
      onEvent: (e) => {
        useGame.getState().apply(e);
        sideEffects(e, sock);
      },
      onStatus: (s, detail) => useGame.getState().setConnection(s, detail),
    });
    useGame.getState().setSocket(sock);
    sock.start();
    return () => {
      sock.stop();
      useGame.getState().setSocket(null);
    };
  }, [campaignId]);
}
