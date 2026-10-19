import { useState } from "react";

const TITLE_LIMIT = 128;

interface Props {
  title: string;
  busy: boolean;
  onRename(title: string): Promise<unknown>;
}

/** Название проекта в шапке. Это метаданные: переименование не меняет ревизию и статус публикации. */
export default function ProjectTitle({ title, busy, onRename }: Props) {
  const [draft, setDraft] = useState<string | null>(null);
  const value = draft?.trim() ?? "";
  const save = () => {
    if (!value || value === title) return setDraft(null);
    // Поле закрываем только после успеха, чтобы при ошибке введённое не пропало.
    onRename(value).then(
      () => setDraft(null),
      () => undefined,
    );
  };

  if (draft === null) {
    return (
      <div className="flex items-center gap-2">
        <h1 className="font-heading text-2xl font-bold tracking-tight text-ink">{title}</h1>
        <button className="btn min-h-9 px-2.5 text-xs" type="button" onClick={() => setDraft(title)}>
          Переименовать
        </button>
      </div>
    );
  }
  return (
    <form
      className="flex flex-wrap items-center gap-2"
      onSubmit={(e) => {
        e.preventDefault();
        save();
      }}
    >
      <input
        aria-label="Название проекта"
        autoFocus
        className="min-h-10 w-72 max-w-full rounded-lg border border-line bg-raised px-2 font-heading text-xl text-ink"
        maxLength={TITLE_LIMIT}
        value={draft}
        onChange={(e) => setDraft(e.target.value)}
        onKeyDown={(e) => e.key === "Escape" && setDraft(null)}
      />
      <button className="btn btn-primary min-h-10 px-3 text-xs" type="submit" disabled={busy || !value}>
        Сохранить
      </button>
      <button className="btn min-h-10 px-3 text-xs" type="button" onClick={() => setDraft(null)}>
        Отмена
      </button>
    </form>
  );
}
