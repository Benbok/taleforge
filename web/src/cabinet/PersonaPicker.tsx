import type { CampaignOptions, Persona, PersonaPick } from "../lib/campaign";

/** Характер ИИ-мастера: свои персоны из профиля, встроенные или без персоны. Под выбором — как мастер его поймёт. */
export default function PersonaPicker({
  value,
  onChange,
  opts,
  mine,
}: {
  value: PersonaPick;
  onChange: (v: PersonaPick) => void;
  opts: CampaignOptions;
  mine: Persona[];
}) {
  const style = value.startsWith("my:")
    ? mine.find((p) => p.id === value.slice(3))?.style
    : value.startsWith("pre:")
      ? opts.presets.find((p) => p.id === value.slice(4))?.style
      : null;
  return (
    <div className="flex flex-col gap-1.5">
      <select className="field" aria-label="Характер мастера" value={value} onChange={(e) => onChange(e.target.value as PersonaPick)}>
        <option value="">Без персоны: мастер по умолчанию</option>
        {mine.length > 0 && (
          <optgroup label="Мои персоны">
            {mine.map((p) => (
              <option key={p.id} value={`my:${p.id}`}>
                {p.name}
              </option>
            ))}
          </optgroup>
        )}
        <optgroup label="Встроенные">
          {opts.presets.map((p) => (
            <option key={p.id} value={`pre:${p.id}`}>
              {p.name}
            </option>
          ))}
        </optgroup>
      </select>
      {style && <p className="whitespace-pre-line text-xs text-muted">{style}</p>}
    </div>
  );
}
