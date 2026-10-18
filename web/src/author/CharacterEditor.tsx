import { useState } from "react";

type Person = Record<string, unknown> & { id: string; name: string };

const NPC_FIELDS: [string, string][] = [
  ["character", "Характер (2–3 черты)"],
  ["speech", "Манера речи и пример фразы"],
  ["knows", "Что знает"],
  ["ties", "Связи"],
  ["sways", "Что расположит и что оттолкнёт"],
];
const VILLAIN_FIELDS: [string, string][] = [
  ["character", "Характер (2–3 черты)"],
  ["speech", "Манера речи и пример фразы"],
  ["on_meeting", "Как ведёт себя при встрече с героями"],
  ["if_foiled", "Что сделает, если план сорвут"],
];

interface Props {
  antagonists: Person[];
  npcs: Person[];
  busy: boolean;
  onSave(ref: string, fields: Record<string, string>): void;
}

/** Характер основных персонажей. Мастер видит его, только когда персонаж рядом, поэтому заполнять стоит главных. */
export default function CharacterEditor({ antagonists, npcs, busy, onSave }: Props) {
  const [draft, setDraft] = useState<Record<string, Record<string, string>>>({});
  const people: [Person, [string, string][], string][] = [
    ...antagonists.map((p) => [p, VILLAIN_FIELDS, "антагонист"] as [Person, [string, string][], string]),
    ...npcs.map((p) => [p, NPC_FIELDS, "NPC"] as [Person, [string, string][], string]),
  ];
  if (!people.length) return null;
  return (
    <section id="plot-characters" aria-label="Характеры персонажей" className="flex scroll-mt-24 flex-col gap-3">
      <h3 className="font-heading text-base text-ink">Характеры персонажей</h3>
      <p className="max-w-prose text-sm text-muted">
        Необязательно, но с характером персонаж ведёт себя одинаково во всех играх. Мастер получает его, только когда персонаж рядом, — лишних трат нет.
      </p>
      {people.map(([person, fields, kind]) => {
        const changes = draft[person.id] ?? {};
        const filled = fields.filter(([key]) => String(person[key] ?? "").trim()).length;
        return (
          <details key={person.id} className="rounded-xl border border-line bg-surface p-3" data-person={person.id}>
            <summary className="flex min-h-11 cursor-pointer items-center gap-3">
              <span className="font-medium text-ink">{person.name}</span>
              <span className="text-xs text-muted">{kind}</span>
              <span className={`ml-auto text-xs ${filled ? "text-ok" : "text-warn"}`}>{filled ? `заполнено ${filled} из ${fields.length}` : "характер не задан"}</span>
            </summary>
            <div className="mt-2 flex flex-col gap-2">
              {fields.map(([key, label]) => (
                <label key={key} className="flex flex-col gap-1 text-sm">
                  <span className="text-muted">{label}</span>
                  <textarea
                    aria-label={`${label}: ${person.name}`}
                    className="min-h-11 rounded-lg border border-line bg-raised p-2"
                    value={changes[key] ?? String(person[key] ?? "")}
                    onChange={(e) => setDraft({ ...draft, [person.id]: { ...changes, [key]: e.target.value } })}
                  />
                </label>
              ))}
              <button
                className="btn btn-primary min-h-11 self-start px-3 text-sm"
                type="button"
                disabled={busy || !Object.keys(changes).length}
                onClick={() => {
                  onSave(person.id, changes);
                  setDraft({ ...draft, [person.id]: {} });
                }}
              >
                Сохранить характер
              </button>
            </div>
          </details>
        );
      })}
    </section>
  );
}
