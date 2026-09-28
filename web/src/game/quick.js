import { useGame } from "../stores/game";
let n = 0;
/** Отправляет быстрое действие. Возвращает причину, если отправить нельзя, иначе null. */
export function sendQuick(text, actions) {
    const g = useGame.getState();
    if (!g.actions.includes("chat.play"))
        return g.blocked["chat.play"] ?? "Сейчас действовать нельзя.";
    if (g.connection !== "open" || !g.socket)
        return "Нет связи с сервером.";
    const clientId = `q${Date.now().toString(36)}${(n++).toString(36)}`;
    if (!g.socket.send("message.send", { kind: "action", text, client_id: clientId, quick: { actions } }))
        return "Нет связи с сервером.";
    g.addPending({ clientId, text, whisper: false, at: Date.now() });
    return null;
}
export function attackText(target, a) {
    return a.key === "unarmed" ? `Бью без оружия: ${target}` : `Атакую: ${target} (${a.name.toLowerCase()})`;
}
export function attack(targetId, targetName, a) {
    return sendQuick(attackText(targetName, a), [
        { verb: "attack", target_id: targetId, instrument_id: a.inventory_id ?? null },
    ]);
}
