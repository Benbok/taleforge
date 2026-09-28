import { jsx as _jsx, jsxs as _jsxs, Fragment as _Fragment } from "react/jsx-runtime";
import { parseMarkup } from "../lib/markup";
import { useGame } from "../stores/game";
import { TYPE_COLOR, TYPE_ICON } from "./entities";
import { useInspector } from "./inspector";
/** Текст мастера с разметкой [[id|текст]]: слово подчёркнуто цветом типа, по нажатию — карточка знаний. */
export default function RichText({ text }) {
    const types = useGame((s) => s.types);
    const open = useInspector((s) => s.open);
    return (_jsx(_Fragment, { children: parseMarkup(text).map((p, i) => "id" in p ? (_jsxs("button", { type: "button", onClick: (e) => open(p.id, p.text, e.currentTarget), className: "cursor-pointer underline decoration-2 underline-offset-4 hover:bg-raised", style: { textDecorationColor: types[p.id] ? TYPE_COLOR[types[p.id]] : "var(--tf-muted)" }, title: "\u0427\u0442\u043E \u044F \u0437\u043D\u0430\u044E \u043E\u0431 \u044D\u0442\u043E\u043C?", children: [p.text, types[p.id] && (_jsx("sup", { className: "ml-0.5 text-[0.65em] no-underline opacity-70", "aria-hidden": true, children: TYPE_ICON[types[p.id]] }))] }, i)) : (_jsx("span", { children: p.text }, i))) }));
}
