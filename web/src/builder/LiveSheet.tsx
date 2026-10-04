import { Spinner } from "../components/ActionButton";
import { ABILITIES, ABILITY_ABBR, SKILLS, signed } from "../game/hero";
import type { Preview } from "../lib/builder";
import { StatDetailTrigger } from "./StatDetailPopover";

/** Лист героя, пока его собирают: числа — от сервера, по тем же правилам, что и в игре. */
export default function LiveSheet({
  preview,
  loading,
  failed,
  name,
}: {
  preview: Preview | null;
  loading: boolean;
  failed: string | null;
  name: string;
}) {
  const d = preview?.derived;

  return (
    <section
      className="card sticky top-24 flex flex-col gap-5 p-5 border border-line bg-surface shadow-xl"
      aria-label="Лист героя"
      aria-busy={loading}
    >
      {/* Header */}
      <div className="flex items-center justify-between gap-2 border-b border-line pb-3">
        <div>
          <span className="font-mono text-[10px] uppercase tracking-wider text-accent font-semibold block">
            Судовой формуляр
          </span>
          <h2 className="truncate font-heading text-xl font-bold text-ink">
            {name.trim() || "Безымянный исследователь"}
          </h2>
        </div>
        {loading && (
          <span className="flex items-center gap-1.5 font-mono text-xs text-patina-hi">
            <Spinner />
            <span>сверка</span>
          </span>
        )}
      </div>

      {failed && (
        <div role="alert" className="rounded-[8px] border border-bad/40 bg-bad/10 p-2.5 font-mono text-xs text-bad">
          Ошибка расчёта: {failed}
        </div>
      )}

      {!d ? (
        <div className="p-4 text-center rounded-[10px] border border-dashed border-line bg-raised/30">
          <p className="text-xs sm:text-sm text-muted">
            Формуляр заполнится автоматически после выбора класса, происхождения и распределения характеристик.
          </p>
        </div>
      ) : (
        <>
          {/* 4 Big Combat Stats */}
          <div className="grid grid-cols-4 gap-2 text-center">
            <BigStat label="КД" value={d.ac} />
            <BigStat label="Хиты" value={d.hp_max} tone="text-patina-hi" />
            <BigStat label="Скорость" value={`${d.speed} фт`} />
            <StatDetailTrigger type="mastery" className="cursor-help">
              <BigStat label="Бонус МС" value={signed(d.pb)} tone="text-accent" />
            </StatDetailTrigger>
          </div>

          {/* 6 Core Abilities */}
          <div className="grid grid-cols-3 gap-2 text-center">
            {ABILITIES.map((a) => {
              const mod = d.mods[a];
              return (
                <StatDetailTrigger key={a} type="ability" id={a} className="cursor-help">
                  <div className="rounded-[8px] border border-line/80 bg-raised/60 p-2 transition hover:border-accent/40">
                    <div className="font-mono text-[10px] text-muted tracking-wider uppercase">
                      {ABILITY_ABBR[a]}
                    </div>
                    <div className="font-heading text-lg font-bold text-ink tabular-nums">
                      {d.abilities[a]}
                    </div>
                    <div
                      className={`font-mono text-xs font-semibold tabular-nums ${
                        mod > 0 ? "text-patina-hi" : mod < 0 ? "text-bad" : "text-muted"
                      }`}
                    >
                      {signed(mod)}
                    </div>
                  </div>
                </StatDetailTrigger>
              );
            })}
          </div>

          {/* Saving Throws */}
          <div>
            <h3 className="mb-1.5 font-mono text-[11px] font-semibold text-muted uppercase tracking-wider">
              Спасброски
            </h3>
            <div className="flex flex-wrap gap-1.5 text-xs font-mono">
              {ABILITIES.map((a) => (
                <StatDetailTrigger key={a} type="ability" id={a} inline>
                  <span
                    className="rounded-[6px] border border-line bg-raised px-2 py-0.5 text-ink-2 tabular-nums cursor-help transition hover:border-accent/50"
                  >
                    <span className="text-muted mr-1">{ABILITY_ABBR[a]}</span>
                    <span className="font-semibold">{signed(d.saves[a])}</span>
                  </span>
                </StatDetailTrigger>
              ))}
            </div>
          </div>

          {/* Skills */}
          <div>
            <h3 className="mb-1.5 font-mono text-[11px] font-semibold text-muted uppercase tracking-wider">
              Навыки
            </h3>
            <ul className="grid grid-cols-2 gap-x-3 gap-y-1 text-xs">
              {SKILLS.map(([id, ru]) => (
                <StatDetailTrigger key={id} type="skill" id={id} as="li" className="border-b border-line/30 py-0.5">
                  <div className="flex w-full justify-between items-center px-1 rounded transition hover:bg-raised/60 cursor-help">
                    <span className="truncate text-ink-2">{ru}</span>
                    <span className="font-mono tabular-nums text-accent font-semibold ml-1">
                      {signed(d.skills[id])}
                    </span>
                  </div>
                </StatDetailTrigger>
              ))}
            </ul>
          </div>

          {/* Attacks */}
          {d.attacks.length > 0 && (
            <div>
              <h3 className="mb-1.5 font-mono text-[11px] font-semibold text-muted uppercase tracking-wider">
                Атаки и оружие
              </h3>
              <ul className="flex flex-col gap-1 text-xs font-mono">
                {d.attacks.map((a) => (
                  <li
                    key={a.key}
                    className="flex items-center justify-between rounded-[6px] border border-line bg-raised/60 px-2.5 py-1"
                  >
                    <span className="text-ink font-medium">{a.name}</span>
                    <span className="text-muted">
                      <span className="text-patina-hi font-semibold">{signed(a.attack_bonus)}</span> попадание ·{" "}
                      <span className="text-accent">{a.damage}</span>
                    </span>
                  </li>
                ))}
              </ul>
            </div>
          )}

          {d.spellcasting && (
            <div>
              <h3 className="mb-1.5 font-mono text-[11px] font-semibold text-muted uppercase tracking-wider">
                Заклинания
              </h3>
              <p className="flex flex-wrap gap-x-3 gap-y-1 text-xs font-mono text-muted">
                <span>
                  Сл спасброска <span className="text-accent font-semibold">{d.spellcasting.save_dc}</span>
                </span>
                <span>
                  атака <span className="text-patina-hi font-semibold">{signed(d.spellcasting.attack)}</span>
                </span>
                {d.spellcasting.needs.prepared > 0 && <span>готовит {d.spellcasting.needs.prepared}</span>}
              </p>
            </div>
          )}
        </>
      )}

      {/* Equipment Preview */}
      {preview && preview.inventory.length > 0 && (
        <div className="border-t border-line pt-3">
          <h3 className="mb-1.5 font-mono text-[11px] font-semibold text-muted uppercase tracking-wider">
            Стартовое снаряжение
          </h3>
          <ul className="flex flex-col gap-1 text-xs">
            {preview.inventory.map((it, i) => (
              <li key={`${it.item}-${i}`} className="flex justify-between items-center text-ink-2">
                <span className="truncate">
                  {it.name}
                  {it.qty > 1 && <span className="text-muted"> ×{it.qty}</span>}
                </span>
                {it.equipped && (
                  <span className="shrink-0 font-mono text-[10px] text-accent border border-accent/40 bg-accent/10 rounded px-1.5 py-0.2">
                    надето
                  </span>
                )}
              </li>
            ))}
          </ul>
        </div>
      )}

      {/* Remaining Steps / Status */}
      {preview && preview.errors.length > 0 && (
        <div className="rounded-[10px] border border-warn/40 bg-warn/10 p-3">
          <h3 className="font-mono text-[11px] font-bold text-warn uppercase tracking-wider mb-1.5">
            Осталось заполнить:
          </h3>
          <ul className="list-disc pl-4 text-xs text-warn space-y-1">
            {preview.errors.map((e) => (
              <li key={e}>{e}</li>
            ))}
          </ul>
        </div>
      )}

      {preview && !preview.errors.length && (
        <div className="rounded-[10px] border border-patina/40 bg-patina/10 p-3 text-center">
          <span className="font-mono text-xs font-bold text-patina-hi uppercase tracking-wider">
            ✓ Лист готов к утверждению
          </span>
        </div>
      )}
    </section>
  );
}

function BigStat({ label, value, tone }: { label: string; value: number | string; tone?: string }) {
  return (
    <div className="rounded-[8px] border border-line bg-raised/80 p-2">
      <div className="font-mono text-[10px] uppercase tracking-wider text-muted">{label}</div>
      <div className={`mt-0.5 font-heading text-xl font-bold tabular-nums ${tone ?? "text-ink"}`}>
        {value}
      </div>
    </div>
  );
}
