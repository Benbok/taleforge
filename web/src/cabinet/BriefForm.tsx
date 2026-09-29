import { Field, Segmented } from "../components/Form";
import type { Brief, BriefOptions } from "../lib/campaign";

/** Анкета кампании: чего ждут игроки. Всё необязательно — чего не выбрали, решит мастер. */
export default function BriefForm({
  brief,
  opts,
  onChange,
}: {
  brief: Brief;
  opts: BriefOptions;
  onChange: (b: Brief) => void;
}) {
  const set = (patch: Partial<Brief>) => onChange({ ...brief, ...patch });
  const emotions = brief.emotions ?? [];
  const entries = (m: Record<string, string>) => Object.entries(m) as [string, string][];

  return (
    <div className="flex flex-col gap-5">
      <div className="grid gap-4 sm:grid-cols-2">
        <Field label="Длительность приключения" hint={!brief.length ? "Не выбрано: решит архитектор сюжета." : undefined}>
          <Segmented
            label="Длительность"
            value={brief.length ?? ""}
            options={entries(opts.length)}
            onChange={(v) => set({ length: v === brief.length ? undefined : v })}
          />
        </Field>

        <Field label="Масштаб угрозы" hint={!brief.threat ? "Не выбрано: решит архитектор сюжета." : undefined}>
          <Segmented
            label="Масштаб угрозы"
            value={brief.threat ?? ""}
            options={entries(opts.threat)}
            onChange={(v) => set({ threat: v === brief.threat ? undefined : v })}
          />
        </Field>
      </div>

      <fieldset className="flex flex-col gap-3 rounded-[10px] border border-line bg-raised/40 p-4">
        <legend className="font-mono text-xs font-semibold text-accent uppercase tracking-wider px-1">
          Столпы приключения (акценты геймплея)
        </legend>
        <div className="flex flex-col gap-3 pt-1">
          {entries(opts.pillars).map(([k, name]) => (
            <div key={k} className="flex flex-wrap items-center justify-between gap-2 border-b border-line/40 pb-2 last:border-b-0 last:pb-0">
              <span className="text-sm font-medium text-ink">{name}</span>
              <Segmented
                label={name}
                value={brief.pillars?.[k] ?? "mid"}
                options={entries(opts.amounts)}
                onChange={(v) => set({ pillars: { ...(brief.pillars ?? {}), [k]: v } })}
              />
            </div>
          ))}
        </div>
      </fieldset>

      <fieldset className="flex flex-col gap-2 rounded-[10px] border border-line bg-raised/40 p-4">
        <legend className="font-mono text-xs font-semibold text-accent uppercase tracking-wider px-1">
          Желаемая атмосфера и эмоции ({emotions.length} из {opts.max_emotions})
        </legend>
        <div className="flex flex-wrap gap-2 pt-1">
          {entries(opts.emotions).map(([k, name]) => {
            const on = emotions.includes(k);
            const full = !on && emotions.length >= opts.max_emotions;
            return (
              <button
                key={k}
                type="button"
                aria-pressed={on}
                disabled={full}
                title={full ? `Не более ${opts.max_emotions}: снимите выбор с другого тега` : undefined}
                className={`rounded-full border px-3 py-1 font-mono text-xs transition ${
                  on
                    ? "border-accent bg-accent/20 text-accent font-semibold shadow-sm"
                    : "border-line bg-raised/80 text-muted hover:border-line hover:text-ink"
                } disabled:cursor-not-allowed disabled:opacity-40`}
                onClick={() => set({ emotions: on ? emotions.filter((e) => e !== k) : [...emotions, k] })}
              >
                {on ? "✓ " : ""}
                {name}
              </button>
            );
          })}
        </div>
      </fieldset>

      <Field
        label="Особые пожелания к сюжету"
        hint="Необязательно: например «морское плавание на дирижабле», «тайный культ часовщиков», «предатель среди союзников»."
      >
        <textarea
          className="field min-h-20 text-sm"
          maxLength={1000}
          placeholder="Опишите ключевые образы или идеи, которые мастер должен вплести в историю..."
          value={brief.wishes ?? ""}
          onChange={(e) => set({ wishes: e.target.value })}
        />
      </Field>
    </div>
  );
}
