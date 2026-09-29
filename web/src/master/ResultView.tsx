import { labelOf, type ToolResult } from "./tools";

const KEY_RU: Record<string, string> = {
  character: "Персонаж",
  entity: "Сущность",
  spawned: "Выставлены",
  template: "Шаблон",
  hp: "Хиты",
  ac: "КД",
  location: "Место",
  name: "Название",
  mode: "Режим",
  round: "Раунд",
  initiative: "Инициатива",
  time: "Время",
  expired: "Истекли",
  levels: "Уровни",
  sent_to: "Кому",
  cancelled: "Отказ",
  success: "Успех",
  status: "Статус",
  learned: "Узнали",
  subject: "О ком",
  fact: "Факт",
  level: "Уровень знаний",
  moved: "Перемещены",
  total: "Итог",
  outcome: "Исход",
  damage: "Урон",
  who: "Кто",
  stat: "Навык",
  kind: "Вид",
  dc: "Сложность",
  margin: "Запас",
  hidden: "Скрытый бросок",
  item: "Предмет",
  qty: "Количество",
  inventory_id: "В инвентаре",
  target: "Цель",
  attacker: "Атакующий",
  hit: "Попадание",
  crit: "Критическое",
  results: "Итоги",
  scene_location: "Сцена",
  current: "Текущая",
  location_id: "Место",
  adjusted_xp: "Опыт встречи",
};

function show(v: unknown, labels: Record<string, string>): string {
  if (v == null) return "—";
  if (typeof v === "string") return labelOf(labels, v);
  if (typeof v === "boolean") return v ? "да" : "нет";
  if (Array.isArray(v)) return v.map((x) => show(x, labels)).join(", ") || "—";
  if (typeof v === "object") {
    const o = v as Record<string, unknown>;
    return typeof o.name === "string" ? o.name : JSON.stringify(v);
  }
  return String(v);
}

/** Итог вызова под формой: сцена и лист — текстом, остальное — парами «что — значение». */
export default function ResultView({ tool, result, labels }: { tool: string; result: ToolResult; labels: Record<string, string> }) {
  const r = result.result ?? {};
  return (
    <div className="rounded-md border border-line bg-raised p-3 text-sm" role="status">
      {tool === "get_scene" && typeof r.scene === "string" ? (
        <pre className="whitespace-pre-wrap font-mono text-xs leading-relaxed">{r.scene}</pre>
      ) : (
        <dl className="grid grid-cols-[auto_1fr] gap-x-3 gap-y-0.5">
          {Object.entries(r).map(([k, v]) => (
            <div key={k} className="contents">
              <dt className="text-muted">{KEY_RU[k] ?? k}</dt>
              <dd className="break-words">{show(v, labels)}</dd>
            </div>
          ))}
          {Object.keys(r).length === 0 && <dd className="col-span-2 text-ok">Готово</dd>}
        </dl>
      )}
      {!!result.plot_clock?.length && <p className="mt-2 text-warn">Часы угрозы: {result.plot_clock.join("; ")}</p>}
    </div>
  );
}
