import { jsx as _jsx, jsxs as _jsxs } from "react/jsx-runtime";
import ActionButton from "../components/ActionButton";
import { api } from "../lib/api";
import { toast } from "../stores/toasts";
import { useGame } from "../stores/game";
/** Управление сессией. Кнопки — только из списка сервера: до старта «Начать», во время — «Пауза» и «Завершить»,
 *  на паузе — «Продолжить». После нажатия сервер пришлёт новое состояние, и кнопки сменятся сами. */
export default function SessionControls({ campaignId }) {
    const actions = useGame((s) => s.actions);
    const status = useGame((s) => s.snapshot?.campaign.status);
    const has = (a) => actions.includes(a);
    const session = (action) => api(`/api/campaigns/${campaignId}/session/${action}`, { method: "POST" });
    async function invite() {
        const inv = await api(`/api/campaigns/${campaignId}/invites`, { body: {} });
        try {
            await navigator.clipboard.writeText(inv.url);
            toast.ok("Ссылка-приглашение скопирована. Она действует 3 дня.");
        }
        catch {
            toast.info(`Ссылка-приглашение: ${inv.url}`);
        }
    }
    return (_jsxs("div", { className: "flex flex-wrap items-center gap-2", children: [has("session.start") && (_jsx(ActionButton, { primary: true, run: () => session("start"), done: status === "paused" ? "Сессия продолжается" : "Сессия началась", children: status === "paused" ? "Продолжить сессию" : "Начать сессию" })), has("session.pause") && (_jsx(ActionButton, { run: () => session("pause"), done: "\u0421\u0435\u0441\u0441\u0438\u044F \u043D\u0430 \u043F\u0430\u0443\u0437\u0435: \u043C\u0430\u0441\u0442\u0435\u0440 \u043F\u043E\u0434\u0432\u0435\u0434\u0451\u0442 \u0438\u0442\u043E\u0433", children: "\u041F\u0430\u0443\u0437\u0430" })), has("invite.create") && (_jsx(ActionButton, { run: invite, children: "\u041F\u0440\u0438\u0433\u043B\u0430\u0441\u0438\u0442\u044C" })), has("campaign.end") && (_jsx(ActionButton, { danger: true, run: () => session("end"), done: "\u041A\u0430\u043C\u043F\u0430\u043D\u0438\u044F \u0437\u0430\u0432\u0435\u0440\u0448\u0435\u043D\u0430", confirm: "\u0417\u0430\u0432\u0435\u0440\u0448\u0438\u0442\u044C \u043A\u0430\u043C\u043F\u0430\u043D\u0438\u044E \u043D\u0430\u0441\u043E\u0432\u0441\u0435\u043C? \u041C\u0430\u0441\u0442\u0435\u0440 \u043D\u0430\u043F\u0438\u0448\u0435\u0442 \u044D\u043F\u0438\u043B\u043E\u0433, \u0438\u0433\u0440\u0430\u0442\u044C \u0434\u0430\u043B\u044C\u0448\u0435 \u0431\u0443\u0434\u0435\u0442 \u043D\u0435\u043B\u044C\u0437\u044F.", children: "\u0417\u0430\u0432\u0435\u0440\u0448\u0438\u0442\u044C" }))] }));
}
