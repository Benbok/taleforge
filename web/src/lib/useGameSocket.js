import { useEffect } from "react";
import { getToken } from "./api";
import { GameSocket, socketUrl } from "./socket";
import { useGame } from "../stores/game";
import { toast } from "../stores/toasts";
// после этих событий доступные действия могли измениться: спрашиваем сервер, какие кнопки показать
const REFRESH_ACTIONS = new Set(["turn.changed", "scene.updated", "character.updated", "state.snapshot", "message.state", "message.withdrawn"]);
export function sideEffects(e, sock) {
    if (e.type === "error") {
        const p = e.payload;
        if (p.code !== "unauthorized")
            toast.error(p.message ?? "сервер отклонил действие");
    }
    if (e.type === "knowledge.revealed")
        toast.info(`Вы узнали больше о: ${e.payload.name ?? "…"}`);
    if (REFRESH_ACTIONS.has(e.type) && e.type !== "state.snapshot")
        sock.send("actions.get");
    if (e.type === "message.new") {
        const m = e.payload;
        if (m.state === "pending" && m.seat_id && m.seat_id === useGame.getState().snapshot?.me.seat_id)
            sock.send("actions.get");
    }
}
/** Одно соединение на вкладку и кампанию: открывается при входе на экран кампании, закрывается при уходе. */
export function useGameSocket(campaignId) {
    useEffect(() => {
        useGame.getState().reset();
        const sock = new GameSocket({
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
