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
  const [loading, setLoading] = useState(false);

  const open = async () => {
    setLoading(true);
    try {
      setText(taskText(await load()));
      setError(null);
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "задание не загрузилось");
    } finally {
      setLoading(false);
    }
  };

  const copy = async () => {
    if (!text) return;
    try {
      await navigator.clipboard.writeText(text);
      setCopied(true);
      setTimeout(() => setCopied(false), 3000);
    } catch {
      setCopied(false);
    }
  };

  if (text === null)
    return (
      <div className="flex flex-col gap-1.5">
        <button
          className="btn min-h-11 self-start px-4 text-sm font-medium transition-colors hover:border-accent"
          type="button"
          disabled={loading}
          onClick={() => void open()}
        >
          {loading ? "Загрузка задания…" : "Задание для внешней модели"}
        </button>
        {error && <p className="text-sm text-bad" role="alert">{error}</p>}
      </div>
    );

  return (
    <div className="flex flex-col gap-3 rounded-2xl border border-line bg-surface p-4 shadow-sm">
      <div className="flex items-center justify-between">
        <span className="font-heading text-sm font-semibold text-ink">Задание для внешней LLM</span>
        <span className="text-xs text-muted">ChatGPT • Claude • DeepSeek • Gemini</span>
      </div>
      <p className="text-xs text-muted leading-relaxed">
        Скопируйте этот текст в диалог с любой моделью. Она подготовит валидный JSON, который затем можно вставить в поле ниже.
      </p>
      <textarea
        aria-label="Задание для внешней модели"
        className="min-h-36 rounded-xl border border-line bg-raised p-3 font-mono text-xs text-ink transition-colors focus:border-accent focus:outline-none"
        readOnly
        value={text}
      />
      <div className="flex flex-wrap items-center gap-2">
        <button
          className="btn btn-primary min-h-11 px-4 text-sm font-medium"
          type="button"
          onClick={() => void copy()}
        >
          {copied ? "✓ Скопировано в буфер" : "Скопировать задание"}
        </button>
        <button
          className="btn min-h-11 px-3 text-sm"
          type="button"
          onClick={() => setText(null)}
        >
          Свернуть
        </button>
      </div>
    </div>
  );
}
