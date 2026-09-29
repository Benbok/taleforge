import { Field, Segmented } from "../components/Form";
import type { Brief, BriefOptions } from "../lib/campaign";

/** Анкета кампании: чего ждут игроки. Всё необязательно — чего не выбрали, решит мастер. */
export default function BriefForm({ brief, opts, onChange }: { brief: Brief; opts: BriefOptions; onChange: (b: Brief) => void }) {
  const set = (patch: Partial<Brief>) => onChange({ ...brief, ...patch });
  const emotions = brief.emotions ?? [];
  const entries = (m: Record<string, string>) => Object.entries(m) as [string, string][];
  return (
    <div className="flex flex-col gap-4">
      <Field label="Длительность" hint={!brief.length ? "Не выбрано: решит мастер." : undefined}>
        <Segmented label="Длительность" value={brief.length ?? ""} options={entries(opts.length)} onChange={(v) => set({ length: v === brief.length ? undefined : v })} />
      </Field>
      <Field label="Масштаб угрозы" hint={!brief.threat ? "Не выбрано: решит мастер." : undefined}>
        <Segmented label="Масштаб угрозы" value={brief.threat ?? ""} options={entries(opts.threat)} onChange={(v) => set({ threat: v === brief.threat ? undefined : v })} />
      </Field>
      <fieldset className="flex flex-col gap-2">
        <legend className="mb-1 text-sm">Чего больше</legend>
        {entries(opts.pillars).map(([k, name]) => (
          <div key={k} className="flex flex-wrap items-center justify-between gap-2">
            <span className="text-sm">{name}</span>
            <Segmented
              label={name}
              value={brief.pillars?.[k] ?? "mid"}
              options={entries(opts.amounts)}
              onChange={(v) => set({ pillars: { ...(brief.pillars ?? {}), [k]: v } })}
            />
          </div>
        ))}
      </fieldset>
      <fieldset>
        <legend className="mb-1 text-sm">
          Какие эмоции <span className="text-muted">({emotions.length} из {opts.max_emotions})</span>
        </legend>
        <div className="flex flex-wrap gap-1.5">
          {entries(opts.emotions).map(([k, name]) => {
            const on = emotions.includes(k);
            const full = !on && emotions.length >= opts.max_emotions;
            return (
              <button
                key={k}
                type="button"
                aria-pressed={on}
                disabled={full}
                title={full ? `Не больше ${opts.max_emotions}: снимите другую` : undefined}
                className={`rounded-full border px-3 py-1 text-sm ${on ? "border-accent bg-raised text-ink" : "border-line text-muted"} disabled:opacity-50`}
                onClick={() => set({ emotions: on ? emotions.filter((e) => e !== k) : [...emotions, k] })}
              >
                {on ? "✓ " : ""}
                {name}
              </button>
            );
          })}
        </div>
      </fieldset>
      <Field label="Пожелания" hint="Необязательно: «морское путешествие», «злодей — кто-то из своих».">
        <textarea className="field min-h-16" maxLength={1000} value={brief.wishes ?? ""} onChange={(e) => set({ wishes: e.target.value })} />
      </Field>
    </div>
  );
}
