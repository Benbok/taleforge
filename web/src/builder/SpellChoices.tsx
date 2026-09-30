import { useMemo } from "react";
import { ABILITY_RU } from "../game/hero";
import { byLevel, LEVEL_RU, MODE_HINT, spellMeta, type ClassSpells, type SpellCard } from "../lib/spells";
import { toast } from "../stores/toasts";
import { ChoiceCard } from "./ChoiceDetails";
import SpellDetails from "./SpellDetails";

export interface SpellPick {
  cantrips: string[];
  spells: string[];
  prepared: string[];
}

/** Сколько выбрать. Число подготовленных зависит от характеристики — его считает живой лист (need). */
export interface SpellNeed {
  cantrips: number;
  spells: number;
  prepared: number | null;
}

/**
 * Выбор заклинаний в конструкторе: заговоры, известные (или книга волшебника) и подготовленные на день.
 * Описание — при наведении мышью или кнопкой «i»; на телефоне — лист снизу с кнопкой «Выбрать».
 */
export default function SpellChoices({
  cs,
  need,
  value,
  onChange,
}: {
  cs: ClassSpells;
  need: SpellNeed;
  value: SpellPick;
  onChange: (v: SpellPick) => void;
}) {
  const cantrips = cs.spells.filter((s) => s.level === 0);
  const leveled = cs.spells.filter((s) => s.level > 0);
  const book = useMemo(() => leveled.filter((s) => value.spells.includes(s.id)), [leveled, value.spells]);

  function flip(key: keyof SpellPick, id: string, max: number | null, label: string) {
    const list = value[key];
    if (list.includes(id)) {
      const next = { ...value, [key]: list.filter((x) => x !== id) };
      // убрали из книги — убираем и из подготовленных: готовят только записанное
      if (key === "spells" && cs.mode === "spellbook") next.prepared = next.prepared.filter((x) => x !== id);
      onChange(next);
      return;
    }
    if (max == null) {
      toast.info("Сначала разложите характеристики: число подготовленных зависит от них.");
      return;
    }
    if (list.length >= max) {
      toast.info(`${label}: уже выбрано ${max} из ${max}. Уберите одно, чтобы взять другое.`);
      return;
    }
    onChange({ ...value, [key]: [...list, id] });
  }

  return (
    <div className="flex flex-col gap-5">
      <div className="rounded-[10px] border border-line bg-raised/40 p-3.5 text-xs leading-relaxed text-ink/85">
        <p>
          Заклинательная характеристика — <b>{ABILITY_RU[cs.ability] ?? cs.ability}</b>. {MODE_HINT[cs.mode]}
        </p>
        {cs.prepared_rule && <p className="mt-1 text-muted">Подготовленных: {cs.prepared_rule}.</p>}
        {cs.source && <p className="mt-1 font-serif italic text-muted">{cs.source}</p>}
        <p className="mt-1 text-muted">{slotsLine(cs)}</p>
      </div>

      {need.cantrips > 0 && (
        <Group
          title={`Заговоры: ${value.cantrips.length} из ${need.cantrips}`}
          hint="Творятся без ячеек сколько угодно раз."
          list={cantrips}
          picked={value.cantrips}
          onFlip={(id) => flip("cantrips", id, need.cantrips, "Заговоры")}
        />
      )}

      {cs.mode !== "prepared" && need.spells > 0 && (
        <Group
          title={`${cs.mode === "spellbook" ? "Книга заклинаний" : "Известные заклинания"}: ${value.spells.length} из ${need.spells}`}
          hint={
            cs.mode === "spellbook"
              ? "Что записано в книгу. Готовить на день можно только записанное."
              : "Эти заклинания герой знает всегда. Новые — с уровнем."
          }
          list={leveled}
          picked={value.spells}
          onFlip={(id) => flip("spells", id, need.spells, cs.mode === "spellbook" ? "Книга" : "Заклинания")}
        />
      )}

      {cs.mode !== "known" && (
        <Group
          title={
            need.prepared == null
              ? "Подготовленные на день"
              : `Подготовленные на день: ${value.prepared.length} из ${need.prepared}`
          }
          hint={
            cs.mode === "spellbook"
              ? book.length
                ? "Из записанных в книгу. Сменить можно после продолжительного отдыха."
                : "Сначала запишите заклинания в книгу."
              : "Из всего списка класса. Сменить можно после продолжительного отдыха."
          }
          list={cs.mode === "spellbook" ? book : leveled}
          picked={value.prepared}
          onFlip={(id) => flip("prepared", id, need.prepared, "Подготовленные")}
        />
      )}
    </div>
  );
}

function slotsLine(cs: ClassSpells): string {
  if (cs.pact_slots) return `Ячейки договора: ${cs.pact_slots} × ${cs.pact_level}-й круг, возвращаются после короткого отдыха.`;
  const slots = cs.slots.map((n, i) => (n ? `${i + 1}-й круг × ${n}` : "")).filter(Boolean);
  return slots.length
    ? `Ячейки на старте: ${slots.join(", ")}. Возвращаются после продолжительного отдыха.`
    : "Ячеек на старте нет: заклинания откроются с уровнем.";
}

function Group({
  title,
  hint,
  list,
  picked,
  onFlip,
}: {
  title: string;
  hint: string;
  list: SpellCard[];
  picked: string[];
  onFlip: (id: string) => void;
}) {
  return (
    <fieldset className="flex flex-col gap-2">
      <legend className="mb-1 font-mono text-xs font-semibold uppercase tracking-wider text-accent">{title}</legend>
      <p className="-mt-1 mb-1 text-xs text-muted">{hint}</p>
      {list.length === 0 ? (
        <p className="text-xs text-muted">Здесь пока пусто.</p>
      ) : (
        byLevel(list).map(([lvl, items]) => (
          <div key={lvl} className="flex flex-col gap-2">
            {byLevel(list).length > 1 && <p className="text-[11px] font-mono text-muted">{LEVEL_RU(lvl)}</p>}
            <div className="grid gap-2 sm:grid-cols-2" role="group" aria-label={`${title}: ${LEVEL_RU(lvl)}`}>
              {items.map((s) => {
                const on = picked.includes(s.id);
                return (
                  <ChoiceCard
                    key={s.id}
                    name={s.name}
                    role="checkbox"
                    selected={on}
                    onPick={() => onFlip(s.id)}
                    details={<SpellDetails s={s} />}
                    className={`flex min-h-[64px] w-full flex-col gap-0.5 rounded-[10px] border px-3 py-2 pr-11 text-left transition cursor-pointer ${
                      on ? "border-accent bg-accent/10" : "border-line bg-raised/50 hover:border-accent/60"
                    }`}
                  >
                    <span className={`text-sm font-semibold ${on ? "text-accent" : "text-ink"}`}>
                      {on ? "✓ " : ""}
                      {s.name}
                    </span>
                    {s.flavor && (
                      <span className="font-serif italic text-xs text-accent/90 line-clamp-2 leading-relaxed">
                        {s.flavor}
                      </span>
                    )}
                    <span className="text-[11px] text-muted">{spellMeta(s)}</span>
                    <span className="flex flex-wrap gap-1 pt-0.5">
                      {s.concentration && <Tag>концентрация</Tag>}
                      {s.ritual && <Tag>ритуал</Tag>}
                      {!s.combat && <Tag>вне боя</Tag>}
                    </span>
                  </ChoiceCard>
                );
              })}
            </div>
          </div>
        ))
      )}
    </fieldset>
  );
}

function Tag({ children }: { children: string }) {
  return <span className="rounded border border-line/70 px-1.5 text-[10px] font-mono text-muted">{children}</span>;
}
