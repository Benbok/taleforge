import CustomSelect, { type SelectOption } from "../components/CustomSelect";
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

  const selectOptions: SelectOption<PersonaPick>[] = [
    {
      value: "" as PersonaPick,
      label: "Без персоны: классический мастер",
      sublabel: "Сбалансированная подача, нейтральный строгий тон по канонам правил",
      badge: "КАНОН",
      badgeTone: "muted",
    },
    ...mine.map(
      (p): SelectOption<PersonaPick> => ({
        value: `my:${p.id}` as PersonaPick,
        label: p.name,
        sublabel: p.style ? p.style.slice(0, 70) + (p.style.length > 70 ? "…" : "") : "Ваша настроенная персона",
        badge: "МОЯ",
        badgeTone: "accent",
      }),
    ),
    ...opts.presets.map(
      (p): SelectOption<PersonaPick> => ({
        value: `pre:${p.id}` as PersonaPick,
        label: p.name,
        sublabel: p.style ? p.style.slice(0, 70) + (p.style.length > 70 ? "…" : "") : "Встроенный архетип",
        badge: "ПРЕСЕТ",
        badgeTone: "patina",
      }),
    ),
  ];

  return (
    <div className="flex flex-col gap-2">
      <CustomSelect<PersonaPick>
        value={value}
        options={selectOptions}
        onChange={onChange}
        ariaLabel="Характер ИИ-мастера"
      />
      {style && (
        <div className="rounded-[8px] border border-line bg-raised/70 p-3 font-serif italic text-xs text-ink-2 leading-relaxed">
          «{style}»
        </div>
      )}
    </div>
  );
}
