import { useState } from "react";
import { ApiError } from "../lib/api";
import type { StageTask } from "../lib/api.gen";
import { authoring, newRequestKey } from "../lib/authoring";

const PLOT_TEXT: [string, string][] = [
  ["title", "Название"],
  ["tagline", "Слоган"],
  ["public_intro", "Завязка для игроков"],
  ["conflict", "Конфликт"],
  ["stakes", "Ставки"],
];
const LORE_KEYS = [
  "overview", "era_and_magic", "regions", "history", "factions", "figures", "current_situation", "mysteries", "tone", "taboos",
];

interface Props {
  projectId: string;
  revision: number;
  plot: Record<string, unknown>;
  busy: boolean;
  onChanged(message: string): void;
  onPlotText(fields: Record<string, string>): void;
  onLore(fields: Record<string, unknown>): void;
}

function taskText(task: StageTask): string {
  return [
    "## Инструкция", task.system, "", "## Входные данные", task.user, "",
    "## Формат ответа", "Ответь одним JSON-объектом строго по этой JSON Schema, без пояснений:",
    JSON.stringify(task.schema, null, 2),
  ].join("\n");
}

/** Ручной путь без трат: задание для любой внешней модели, вставка её ответа и правка текстов от руки. */
export default function ManualPanel({ projectId, revision, plot, busy, onChanged, onPlotText, onLore }: Props) {
  const [task, setTask] = useState<{ stage: string; text: string; how: string } | null>(null);
  const [loreJson, setLoreJson] = useState("");
  const [plotJson, setPlotJson] = useState("");
  const [errors, setErrors] = useState<string[]>([]);
  const [texts, setTexts] = useState<Record<string, string>>({});
  const [pending, setPending] = useState(false);

  const loadTask = async (stage: "lore" | "plot") => {
    setErrors([]);
    try {
      const t = await authoring.task(projectId, stage);
      setTask({ stage, text: taskText(t), how: t.how });
    } catch (e) {
      setErrors([e instanceof ApiError ? e.message : "задание не загрузилось"]);
    }
  };
  const parse = (text: string): Record<string, unknown> | null => {
    try {
      const body = text.trim().replace(/^```(?:json)?/, "").replace(/```$/, "").trim();
      const data = JSON.parse(body);
      return data && typeof data === "object" && !Array.isArray(data) ? data : null;
    } catch {
      return null;
    }
  };
  const importLore = () => {
    const data = parse(loreJson);
    if (!data) return setErrors(["это не JSON-объект"]);
    const fields = Object.fromEntries(Object.entries(data).filter(([k]) => LORE_KEYS.includes(k)));
    if (!Object.keys(fields).length) return setErrors(["в JSON нет ни одного раздела лора"]);
    setErrors([]);
    onLore(fields);
    setLoreJson("");
  };
  const importPlot = async () => {
    const data = parse(plotJson);
    if (!data) return setErrors(["это не JSON-объект"]);
    setPending(true);
    try {
      const r = await authoring.importPlot(projectId, { plan: data, expected_revision: revision, request_key: newRequestKey() });
      setErrors([]);
      setPlotJson("");
      onChanged(r.cleared_entities ? `Каркас импортирован; прежние места и карты (${r.cleared_entities}) удалены.` : "Каркас импортирован и проверен.");
    } catch (e) {
      const data = e instanceof ApiError ? (e.data as { errors?: string[] } | undefined) : undefined;
      setErrors(data?.errors ?? [e instanceof ApiError ? e.message : "импорт не удался"]);
    } finally {
      setPending(false);
    }
  };
  const changedTexts = Object.fromEntries(Object.entries(texts).filter(([k, v]) => v !== (plot[k] ?? "")));

  return (
    <section aria-label="Ручное заполнение" className="flex flex-col gap-4 rounded-lg border border-line p-3">
      <h2 className="font-heading text-lg text-ink">Заполнить вручную или во внешней модели</h2>
      <p className="text-sm text-muted">Без трат: скопируйте задание в любую модель в браузере и вставьте её ответ сюда. Ответ проходит ту же проверку сервера, что и генерация.</p>
      <div className="flex flex-wrap gap-2">
        <button className="btn min-h-11 px-3 text-sm" type="button" onClick={() => loadTask("lore")}>Задание для лора</button>
        <button className="btn min-h-11 px-3 text-sm" type="button" onClick={() => loadTask("plot")}>Задание для сюжета</button>
      </div>
      {task && (
        <div className="flex flex-col gap-2">
          <textarea aria-label={`Задание: ${task.stage}`} className="min-h-40 rounded-lg border border-line bg-raised p-2 font-mono text-xs" readOnly value={task.text} />
          <div className="flex items-center gap-2">
            <button className="btn min-h-11 px-3 text-sm" type="button" onClick={() => void navigator.clipboard?.writeText(task.text)}>Скопировать</button>
            <span className="text-sm text-muted">{task.how}</span>
          </div>
        </div>
      )}
      <label className="flex flex-col gap-1 text-sm">
        <span className="text-muted">Импорт лора (JSON)</span>
        <textarea aria-label="Импорт лора" className="min-h-24 rounded-lg border border-line bg-raised p-2 font-mono text-xs" value={loreJson} onChange={(e) => setLoreJson(e.target.value)} />
        <button className="btn min-h-11 self-start px-3 text-sm" type="button" disabled={busy || !loreJson.trim()} onClick={importLore}>Импортировать лор</button>
      </label>
      <label className="flex flex-col gap-1 text-sm">
        <span className="text-muted">Импорт каркаса сюжета (JSON)</span>
        <textarea aria-label="Импорт каркаса" className="min-h-24 rounded-lg border border-line bg-raised p-2 font-mono text-xs" value={plotJson} onChange={(e) => setPlotJson(e.target.value)} />
        <button className="btn min-h-11 self-start px-3 text-sm" type="button" disabled={busy || pending || !plotJson.trim()} onClick={() => void importPlot()}>Импортировать каркас</button>
      </label>
      {errors.length > 0 && (
        <ul className="rounded-lg border border-warn/40 bg-warn/10 p-3 text-sm" role="alert" aria-label="Ошибки импорта">
          {errors.map((e, i) => <li key={i}>{e}</li>)}
        </ul>
      )}
      <fieldset className="flex flex-col gap-2">
        <legend className="text-sm text-muted">Тексты сюжета</legend>
        {PLOT_TEXT.map(([key, label]) => (
          <label key={key} className="flex flex-col gap-1 text-sm">
            <span className="text-muted">{label}</span>
            <textarea className="min-h-11 rounded-lg border border-line bg-raised p-2" value={texts[key] ?? String(plot[key] ?? "")} onChange={(e) => setTexts({ ...texts, [key]: e.target.value })} />
          </label>
        ))}
        <button
          className="btn min-h-11 self-start px-3 text-sm"
          type="button"
          disabled={busy || !Object.keys(changedTexts).length}
          onClick={() => {
            onPlotText(changedTexts);
            setTexts({});
          }}
        >
          Сохранить тексты
        </button>
      </fieldset>
    </section>
  );
}
