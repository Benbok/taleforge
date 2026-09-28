export const GROUP_TITLES = {
    live: "Идут сейчас",
    playing: "Играю",
    leading: "Веду",
    created: "Создал",
    archive: "Архив",
};
export function groupOf(c) {
    if (c.status === "ended")
        return "archive";
    if (c.session_live)
        return "live";
    if (c.my_role === "player")
        return "playing";
    if (c.my_role === "master")
        return "leading";
    return "created";
}
export function groupCards(cards) {
    const order = ["live", "playing", "leading", "created", "archive"];
    return order
        .map((g) => [g, cards.filter((c) => groupOf(c) === g)])
        .filter(([, list]) => list.length > 0);
}
export const STATUS_TEXT = {
    live: "Идёт сессия",
    paused: "Пауза",
    waiting: "Ждёт игроков",
    lobby: "Сбор отряда",
    ended: "Завершена",
};
export function statusOf(c) {
    if (c.session_live)
        return "live";
    if (c.status === "ended")
        return "ended";
    if (c.status === "paused")
        return "paused";
    if (c.waiting_players > 0)
        return "waiting";
    return "lobby";
}
/** Главное действие по ситуации. Сборка героя пока живёт в прежнем клиенте. */
export function actionOf(c) {
    const room = `/c/${c.id}`;
    if (c.status === "ended")
        return { label: "Открыть", href: room, primary: false };
    const builder = `/legacy?campaign=${c.id}`;
    if (c.my_role === "player" && (!c.hero || c.hero.status === "draft" || c.hero.status === "rejected"))
        return { label: "Собрать героя", href: builder, primary: true };
    if (c.my_role === "player" && c.hero?.status === "dead")
        return { label: "Новый герой", href: builder, primary: true };
    if (c.my_role === "player" && c.hero?.status === "submitted")
        return { label: "Персонаж на проверке", href: room, primary: false };
    if (c.session_live)
        return { label: "Продолжить", href: room, primary: true };
    if (c.is_owner && !c.my_role)
        return { label: "Управлять", href: room, primary: false };
    return { label: "Открыть", href: room, primary: false };
}
const DATE = new Intl.DateTimeFormat("ru-RU", { day: "numeric", month: "long" });
export function when(iso) {
    return iso ? DATE.format(new Date(iso)) : null;
}
