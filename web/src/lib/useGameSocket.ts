import { useEffect, useRef } from "react";
import { getToken } from "./api";
import { GameSocket, socketUrl } from "./socket";
import { useGame } from "../stores/game";

/** Одно соединение на вкладку и кампанию: открывается при входе на экран кампании, закрывается при уходе. */
export function useGameSocket(campaignId: string): GameSocket | null {
  const ref = useRef<GameSocket | null>(null);
  useEffect(() => {
    const game = useGame.getState();
    game.reset();
    const sock = new GameSocket({
      url: socketUrl(),
      token: getToken,
      campaignId,
      onEvent: (e) => useGame.getState().apply(e),
      onStatus: (s, detail) => useGame.getState().setConnection(s, detail),
    });
    ref.current = sock;
    sock.start();
    return () => {
      sock.stop();
      ref.current = null;
    };
  }, [campaignId]);
  return ref.current;
}
