import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import ActionButton from "./ActionButton";
import { api } from "../lib/api";
import { toast } from "../stores/toasts";

// Характер, который живёт (этап 9б): анкета — свободный текст и поля-подсказки, ядро — поля, которые летопись
// не трогает. «Помочь» дописывает пустые поля, «Проверить» показывает три пробные сцены, летопись — как характер
// изменился за игру; каждую запись можно поправить или откатить.

export interface PersonaSheet {
  text: string;
  fields: Record<string, string>;
  core: string[];
}

interface PersonaNote {
  id: string;
  text: string;
  cause: string;
  source: "session" | "event" | "owner";
  edited: boolean;
  reverted: boolean;
  created_at: string | null;
}

interface PersonaData {
  persona: PersonaSheet;
  schema: {
    fields: { id: string; label: string; hint: string }[];
    core: string[];
  };
  notes: PersonaNote[];
  can_edit: boolean;
}

interface Scene {
  scene: string;
  situation: string;
  reply: string;
}

const SOURCE: Record<PersonaNote["source"], string> = {
  session: "после сессии",
  event: "после события",
  owner: "вручную",
};
const DATE = new Intl.DateTimeFormat("ru-RU", {
  day: "numeric",
  month: "short",
  hour: "2-digit",
  minute: "2-digit",
});

/** base — адрес анкеты (`…/characters/{id}/persona` или `…/master-character`), query — например `?as_seat=…`. */
export default function PersonaEditor({
  base,
  query = "",
  master = false,
}: {
  base: string;
  query?: string;
  master?: boolean;
}) {
  const qc = useQueryClient();
  const key = ["persona", base, query];
  const data = useQuery({
    queryKey: key,
    queryFn: () => api<PersonaData>(base + query),
  });
  const [draft, setDraft] = useState<PersonaSheet | null>(null);
  const [scenes, setScenes] = useState<Scene[] | null>(null);
  useEffect(() => {
    if (data.data && draft === null) setDraft(data.data.persona);
  }, [data.data, draft]);

  if (data.isError)
    return (
      <p className="text-sm text-bad">
        Анкета не загрузилась: {(data.error as Error).message}
      </p>
    );
  if (!data.data || !draft)
    return <p className="font-mono text-xs text-muted">Загружаем характер…</p>;
  const d = data.data;
  const edit = d.can_edit;
  const url = (path: string) => base + path + query;
  const set = (patch: Partial<PersonaSheet>) =>
    setDraft({ ...draft, ...patch });
  const setField = (id: string, v: string) =>
    set({ fields: { ...draft.fields, [id]: v } });
  const toggleCore = (id: string) =>
    set({
      core: draft.core.includes(id)
        ? draft.core.filter((x) => x !== id)
        : [...draft.core, id],
    });
  const who = master ? "мастер" : "герой";

  return (
    <div className="flex flex-col gap-4">
      <label className="flex flex-col gap-1">
        <span className="font-mono text-xs uppercase tracking-wider text-muted">
          {master ? "Какой он мастер" : "Кто он"} — своими словами
        </span>
        <textarea
          className="field min-h-24 text-sm"
          maxLength={4000}
          readOnly={!edit}
          placeholder={
            master
              ? "Как мастер ведёт игру, что любит, как говорит с отрядом…"
              : "Кто он, как смотрит на мир, что им движет. Чем подробнее и страннее, тем живее."
          }
          value={draft.text}
          onChange={(e) => set({ text: e.target.value })}
        />
      </label>

      <div className="grid gap-3 sm:grid-cols-2">
        {d.schema.fields.map((f) => (
          <label key={f.id} className="flex flex-col gap-1">
            <span className="flex items-center justify-between gap-2">
              <span className="text-sm font-semibold text-ink">{f.label}</span>
              <span
                className="flex items-center gap-1 font-mono text-[11px] text-muted"
                title="Летопись не меняет неизменные черты"
              >
                <input
                  type="checkbox"
                  disabled={!edit}
                  checked={draft.core.includes(f.id)}
                  onChange={() => toggleCore(f.id)}
                  aria-label={`${f.label}: неизменно`}
                />
                неизменно
              </span>
            </span>
            <textarea
              className="field min-h-16 text-sm"
              maxLength={1000}
              readOnly={!edit}
              placeholder={f.hint}
              value={draft.fields[f.id] ?? ""}
              onChange={(e) => setField(f.id, e.target.value)}
            />
          </label>
        ))}
      </div>

      {edit && (
        <div className="flex flex-wrap gap-2">
          <ActionButton
            primary
            className="font-mono text-xs tracking-wider"
            run={async () => {
              const out = await api<PersonaData>(url(""), {
                method: "PUT",
                body: draft,
              });
              qc.setQueryData(key, out);
              setDraft(out.persona);
            }}
            done={
              master
                ? "Характер мастера сохранён: со следующего хода"
                : "Характер сохранён"
            }
          >
            Сохранить характер
          </ActionButton>
          <ActionButton
            className="font-mono text-xs"
            title="Модель допишет пустые поля; заполненное не тронет"
            run={async () => {
              const out = await api<{ persona: PersonaSheet }>(url("/help"), {
                body: { persona: draft },
              });
              const added = Object.keys(out.persona.fields).filter(
                (k) => !draft.fields[k]?.trim(),
              ).length;
              setDraft(out.persona);
              toast.ok(
                added
                  ? `Дописал полей: ${added}. Проверьте и сохраните`
                  : "Пустых полей не осталось",
              );
            }}
          >
            Помочь
          </ActionButton>
          {!master && (
            <ActionButton
              className="font-mono text-xs"
              title="Черта, идеал, привязанность и слабость из таблиц мира — в пустые места анкеты"
              run={async () => {
                const out = await api<{
                  persona: PersonaSheet;
                  taken: { label: string }[];
                }>(url("/tables"), {
                  body: { persona: draft },
                });
                setDraft(out.persona);
                toast.ok(
                  out.taken.length
                    ? `Взял из таблиц: ${out.taken.map((x) => x.label.toLowerCase()).join(", ")}. Проверьте и сохраните`
                    : "Места для таблиц уже заполнены: очистите поле, чтобы взять другое",
                );
              }}
            >
              Из таблиц мира
            </ActionButton>
          )}
          <ActionButton
            className="font-mono text-xs"
            title="Три короткие пробные сцены по текущей анкете, даже несохранённой"
            run={async () =>
              setScenes(
                (
                  await api<{ scenes: Scene[] }>(url("/test"), {
                    body: { persona: draft },
                  })
                ).scenes,
              )
            }
            done="Сцены готовы"
          >
            Проверить
          </ActionButton>
        </div>
      )}

      {scenes && (
        <section className="flex flex-col gap-2" aria-label="Пробные сцены">
          <h3 className="font-heading text-base font-bold text-ink">
            Как {who} себя поведёт
          </h3>
          {scenes.map((s) => (
            <article
              key={s.scene}
              className="rounded-md border border-line bg-raised p-3"
            >
              <p className="font-mono text-[11px] uppercase tracking-wider text-accent">
                {s.scene}
              </p>
              <p className="text-xs text-muted">{s.situation}</p>
              <p className="mt-1 whitespace-pre-line font-narration">
                {s.reply}
              </p>
            </article>
          ))}
          <p className="text-xs text-muted">
            Не то? Поправьте анкету и нажмите «Проверить» ещё раз.
          </p>
        </section>
      )}

      <Chronicle
        notes={d.notes}
        edit={edit}
        url={url}
        onData={(out) => qc.setQueryData(key, out)}
        who={who}
      />
    </div>
  );
}

function Chronicle({
  notes,
  edit,
  url,
  onData,
  who,
}: {
  notes: PersonaNote[];
  edit: boolean;
  url: (path: string) => string;
  onData: (d: PersonaData) => void;
  who: string;
}) {
  const [editing, setEditing] = useState<string | null>(null);
  const [text, setText] = useState("");
  const patch = (id: string, body: Record<string, unknown>) =>
    api<PersonaData>(url(`/notes/${id}`), { method: "PATCH", body }).then(
      onData,
    );
  return (
    <section className="flex flex-col gap-2" aria-label="Летопись характера">
      <h3 className="font-heading text-base font-bold text-ink">
        Летопись характера
      </h3>
      {notes.length === 0 ? (
        <p className="text-xs text-muted">
          Пока пусто. После сессии и после сильных событий (гибель героя, конец
          боя, предательство, спасение) здесь появится, как {who} изменился и
          почему. Неизменные черты летопись не трогает.
        </p>
      ) : (
        <ul className="flex flex-col gap-2">
          {notes.map((n) => (
            <li
              key={n.id}
              className={`rounded-md border border-line p-2.5 ${n.reverted ? "opacity-60" : ""}`}
            >
              {editing === n.id ? (
                <div className="flex flex-col gap-2">
                  <textarea
                    className="field min-h-14 text-sm"
                    maxLength={500}
                    value={text}
                    onChange={(e) => setText(e.target.value)}
                  />
                  <div className="flex gap-2">
                    <ActionButton
                      primary
                      className="px-2.5 py-1 font-mono text-xs"
                      run={async () => {
                        if (!text.trim())
                          throw new Error("Запись не может быть пустой");
                        await patch(n.id, { text });
                        setEditing(null);
                      }}
                      done="Запись поправлена"
                    >
                      Сохранить
                    </ActionButton>
                    <button
                      className="btn px-2.5 py-1 font-mono text-xs"
                      onClick={() => setEditing(null)}
                    >
                      Отмена
                    </button>
                  </div>
                </div>
              ) : (
                <>
                  <p className={`text-sm ${n.reverted ? "line-through" : ""}`}>
                    {n.text}
                  </p>
                  <p className="font-mono text-[11px] text-muted">
                    {n.cause && `${n.cause} · `}
                    {SOURCE[n.source]}
                    {n.created_at &&
                      ` · ${DATE.format(new Date(n.created_at))}`}
                    {n.edited && " · поправлено"}
                    {n.reverted && " · откачено"}
                  </p>
                  {edit && (
                    <div className="mt-1 flex gap-2">
                      {!n.reverted && (
                        <button
                          className="btn px-2 py-0.5 font-mono text-[11px]"
                          onClick={() => {
                            setText(n.text);
                            setEditing(n.id);
                          }}
                        >
                          Поправить
                        </button>
                      )}
                      <ActionButton
                        className="px-2 py-0.5 font-mono text-[11px]"
                        run={() => patch(n.id, { reverted: !n.reverted })}
                        done={
                          n.reverted
                            ? "Запись снова действует"
                            : "Запись откачена: модель её больше не учитывает"
                        }
                      >
                        {n.reverted ? "Вернуть" : "Откатить"}
                      </ActionButton>
                    </div>
                  )}
                </>
              )}
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
