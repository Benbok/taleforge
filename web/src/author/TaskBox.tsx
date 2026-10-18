import { useState } from "react";
import { ApiError } from "../lib/api";
import type { StageTask } from "../lib/api.gen";

export function taskText(task: StageTask): string {
  return [
    "## Инструкция",
    task.system,
    "",
    "## Входные данные",
    task.user,
    "",
    "## Формат ответа",
    "Ответь одним JSON-объектом строго по этой JSON Schema, без пояснений:",
    JSON.stringify(task.schema, null, 2),
  ].join("\n");
}

interface Props {
  load(): Promise<StageTask>;
}

/** Задание для внешней модели: то же, что получила бы встроенная, — скопировать и вставить в браузерный чат. */
export default function TaskBox({ load }: Props) {
  const [text, setText] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);
  const open = async () => {
    try {
      setText(taskText(await load()));
      setError(null);
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "задание не загрузилось");
    }
  };
  const copy = async () => {
    if (!text) return;
    try {
      await navigator.clipboard.writeText(text);
      setCopied(true);
    } catch {
      setCopied(false);
    }
  };
  if (text === null)
    return (
      <div className="flex flex-col gap-1">
        <button className="btn min-h-11 self-start px-3 text-sm" type="button" onClick={() => void open()}>Задание для внешней модели</button>
        {error && <p className="text-sm text-bad" role="alert">{error}</p>}
      </div>
    );
  return (
    <div className="flex flex-col gap-2 rounded-xl border border-line bg-surface p-3">
      <p className="text-sm text-muted">Скопируйте это в любую модель, затем вставьте её ответ в поле ниже.</p>
      <textarea aria-label="Задание для внешней модели" className="min-h-32 rounded-lg border border-line bg-raised p-2 font-mono text-xs" readOnly value={text} />
      <div className="flex gap-2">
        <button className="btn btn-primary min-h-11 px-3 text-sm" type="button" onClick={() => void copy()}>{copied ? "Скопировано" : "Скопировать задание"}</button>
        <button className="btn min-h-11 px-3 text-sm" type="button" onClick={() => setText(null)}>Свернуть</button>
      </div>
    </div>
  );
}
