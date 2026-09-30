import { useQueryClient } from "@tanstack/react-query";
import { useId, useState } from "react";
import ActionButton from "../components/ActionButton";
import CustomSelect from "../components/CustomSelect";
import { toast } from "../stores/toasts";
import ResultView from "./ResultView";
import {
  buildArgs,
  callTool,
  FIELD_RU,
  initialValues,
  isLongText,
  labelOf,
  problems,
  TOOL_RU,
  type ToolField,
  type ToolResult,
  type ToolSpec,
  type Values,
} from "./tools";

/** Форма одного инструмента: поля со списками допустимых значений, кнопка вызова, итог под формой.
 *  Отказ сервера показывается с причиной; форма остаётся заполненной, чтобы поправить и повторить. */
export default function ToolForm({
  campaignId,
  tool,
  labels,
  prefill,
  onClose,
}: {
  campaignId: string;
  tool: ToolSpec;
  labels: Record<string, string>;
  prefill?: Values;
  onClose?: () => void;
}) {
  const qc = useQueryClient();
  const [values, setValues] = useState<Values>(() => initialValues(tool, prefill));
  const [result, setResult] = useState<ToolResult | null>(null);
  const bad = problems(tool, values);
  const set = (name: string, v: Values[string]) => setValues((x) => ({ ...x, [name]: v }));

  async function run() {
    if (bad.length) throw new Error(bad.join("; "));
    const r = await callTool(tool.name, buildArgs(tool, values));
    setResult(r);
    if (!r.ok) throw new Error(r.error ?? "сервер отклонил вызов");
    if (tool.mutating) {
      toast.ok(`${TOOL_RU[tool.name] ?? tool.name}: готово`);
      // списки значений (сущности, предметы, узлы сюжета) могли измениться
      await qc.invalidateQueries({ queryKey: ["master-panel", campaignId] });
    }
  }

  return (
    <form className="flex flex-col gap-3" onSubmit={(e) => e.preventDefault()} aria-label={TOOL_RU[tool.name] ?? tool.name}>
      <div className="flex items-start justify-between gap-2">
        <div>
          <h3 className="font-semibold">{TOOL_RU[tool.name] ?? tool.name}</h3>
          <p className="text-xs text-muted">{tool.description}</p>
        </div>
        {onClose && (
          <button type="button" className="btn px-2 py-0.5 text-xs" onClick={onClose} aria-label="Закрыть форму">
            ✕
          </button>
        )}
      </div>
      {tool.fields.map((f) => (
        <FieldInput key={f.name} f={f} labels={labels} value={values[f.name]} onChange={(v) => set(f.name, v)} />
      ))}
      <div className="flex flex-wrap items-start gap-2">
        <ActionButton primary run={run}>
          {tool.mutating ? "Выполнить" : "Показать"}
        </ActionButton>
        {bad.length > 0 && <span className="text-xs text-warn">{bad.join("; ")}</span>}
      </div>
      {result?.ok && <ResultView tool={tool.name} result={result} labels={labels} />}
    </form>
  );
}

function FieldInput({
  f,
  labels,
  value,
  onChange,
}: {
  f: ToolField;
  labels: Record<string, string>;
  value: Values[string];
  onChange: (v: Values[string]) => void;
}) {
  const id = useId();
  const title = FIELD_RU[f.name] ?? f.name;
  // у полей со списком подсказка схемы (перечень id для модели) человеку не нужна: выбор и так из списка
  const hint = f.description && !f.options ? <span className="block text-xs text-muted">{f.description}</span> : null;
  const head = (
    <span className="text-sm">
      {title}
      {f.required && f.type !== "boolean" && <span className="text-warn"> *</span>}
    </span>
  );

  if (f.many) {
    const picked = Array.isArray(value) ? value : [];
    const options = f.options ?? [];
    return (
      <fieldset className="flex flex-col gap-1">
        <legend className="mb-1">{head}</legend>
        {options.length === 0 ? (
          <span className="text-xs text-muted">Выбрать не из кого: в сцене нет подходящих.</span>
        ) : (
          <span className="flex flex-wrap gap-x-4 gap-y-1">
            {options.map((o) => (
              <label key={o} className="flex items-center gap-1.5 text-sm">
                <input
                  type="checkbox"
                  checked={picked.includes(o)}
                  onChange={(e) => onChange(e.target.checked ? [...picked, o] : picked.filter((x) => x !== o))}
                />
                {labelOf(labels, o)}
              </label>
            ))}
          </span>
        )}
        {hint}
      </fieldset>
    );
  }

  if (f.type === "boolean") {
    if (f.nullable)
      return (
        <label className="flex flex-col gap-1">
          {head}
          <CustomSelect
            value={value == null ? "" : String(value)}
            options={[
              { value: "", label: "не менять" },
              { value: "true", label: "да" },
              { value: "false", label: "нет" },
            ]}
            onChange={onChange}
          />
          {hint}
        </label>
      );
    return (
      <label className="flex items-center gap-2 text-sm">
        <input type="checkbox" checked={value === true} onChange={(e) => onChange(e.target.checked)} />
        {title}
        {f.description && <span className="text-xs text-muted">· {f.description}</span>}
      </label>
    );
  }

  const str = typeof value === "string" ? value : "";
  if (f.options) {
    // короткий список — выпадающий, длинный — поле с подсказками и поиском по названию
    if (f.options.length <= 15)
      return (
        <label className="flex flex-col gap-1">
          {head}
        <CustomSelect
          value={str}
          options={[
            { value: "", label: f.required ? "— выберите —" : "— не задано —" },
            ...f.options.map((o) => ({ value: o, label: labelOf(labels, o) })),
          ]}
          onChange={onChange}
        />
          {f.options.length === 0 && <span className="text-xs text-muted">Сейчас выбрать не из чего.</span>}
          {hint}
        </label>
      );
    return (
      <label className="flex flex-col gap-1">
        {head}
        <input className="field" list={id} value={str} placeholder="начните вводить название" onChange={(e) => onChange(e.target.value)} />
        <datalist id={id}>
          {f.options.map((o) => (
            <option key={o} value={o}>
              {labelOf(labels, o)}
            </option>
          ))}
        </datalist>
        {str && labels[str] && <span className="text-xs text-ok">{labels[str]}</span>}
        {str && !labels[str] && !f.options.includes(str) && <span className="text-xs text-warn">Такого нет в списке: сервер откажет.</span>}
        {hint}
      </label>
    );
  }

  if (f.type === "integer")
    return (
      <label className="flex flex-col gap-1">
        {head}
        <input
          className="field w-32"
          type="number"
          min={f.min ?? undefined}
          max={f.max ?? undefined}
          value={str}
          onChange={(e) => onChange(e.target.value)}
        />
        {hint}
      </label>
    );

  return (
    <label className="flex flex-col gap-1">
      {head}
      {isLongText(f) ? (
        <textarea className="field min-h-16" maxLength={f.max_length ?? undefined} value={str} onChange={(e) => onChange(e.target.value)} />
      ) : (
        <input className="field" maxLength={f.max_length ?? undefined} value={str} onChange={(e) => onChange(e.target.value)} />
      )}
      {hint}
    </label>
  );
}
