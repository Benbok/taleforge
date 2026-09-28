// Открытая карточка сущности. Запрос уходит сокетом (entity.inspect), ответ приходит событием entity.card.
import { create } from "zustand";
import { useGame } from "../stores/game";
export const useInspector = create((set) => ({
    id: null,
    label: "",
    anchor: null,
    open(id, label, el) {
        const game = useGame.getState();
        const cached = game.cards[id];
        if (!cached || cached.error) {
            if (cached)
                useGame.setState((st) => ({ cards: Object.fromEntries(Object.entries(st.cards).filter(([k]) => k !== id)) }));
            const sent = game.socket?.send("entity.inspect", { entity_id: id });
            if (!sent) {
                game.apply({
                    type: "entity.card",
                    campaign_id: null,
                    seq: null,
                    payload: { id, error: "нет связи с сервером: карточка откроется, когда соединение вернётся" },
                });
            }
        }
        set({ id, label, anchor: el?.getBoundingClientRect() ?? null });
    },
    close() {
        set({ id: null, anchor: null });
    },
}));
