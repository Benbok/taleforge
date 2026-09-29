import { Spinner } from "../components/ActionButton";
import { ABILITIES, ABILITY_ABBR, SKILLS, signed } from "../game/hero";
import type { Preview } from "../lib/builder";

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
    <section className="card flex flex-col gap-4 p-4" aria-label="Лист героя" aria-busy={loading}>
      <div className="flex items-center justify-between gap-2">
        <h2 className="truncate text-lg font-semibold">{name.trim() || "Безымянный герой"}</h2>
        {loading && (
          <span className="flex items-center gap-1.5 text-xs text-muted">
            <Spinner /> считаем
          </span>
        )}
      </div>
      {failed && (
        <p role="alert" className="text-sm text-bad">
          Лист не пересчитан: {failed}
        </p>
      )}
      {!d ? (
        <p className="text-sm text-muted">Лист заполнится, когда выбраны класс, происхождение и все характеристики.</p>
      ) : (
        <>
          <div className="grid grid-cols-4 gap-2 text-center">
            <Big label="КД" value={d.ac} />
            <Big label="Хиты" value={d.hp_max} />
            <Big label="Скорость" value={d.speed} />
            <Big label="Мастерство" value={signed(d.pb)} />
          </div>
          <div className="grid grid-cols-3 gap-2 text-center sm:grid-cols-6 lg:grid-cols-3">
            {ABILITIES.map((a) => (
              <div key={a} className="rounded-md border border-line p-1.5">
                <div className="text-xs text-muted">{ABILITY_ABBR[a]}</div>
                <div className="text-lg font-semibold">{d.abilities[a]}</div>
                <div className="text-xs">{signed(d.mods[a])}</div>
              </div>
            ))}
          </div>
          <div>
            <h3 className="mb-1 text-sm text-muted">Спасброски</h3>
            <p className="text-sm">{ABILITIES.map((a) => `${ABILITY_ABBR[a]} ${signed(d.saves[a])}`).join(" · ")}</p>
          </div>
          <div>
            <h3 className="mb-1 text-sm text-muted">Навыки</h3>
            <ul className="grid grid-cols-2 gap-x-3 text-sm">
              {SKILLS.map(([id, ru]) => (
                <li key={id} className="flex justify-between gap-2">
                  <span className="truncate">{ru}</span>
                  <span className="tabular-nums">{signed(d.skills[id])}</span>
                </li>
              ))}
            </ul>
          </div>
          {d.attacks.length > 0 && (
            <div>
              <h3 className="mb-1 text-sm text-muted">Атаки</h3>
              <ul className="text-sm">
                {d.attacks.map((a) => (
                  <li key={a.key}>
                    {a.name}: {signed(a.attack_bonus)} к попаданию, {a.damage}
                  </li>
                ))}
              </ul>
            </div>
          )}
        </>
      )}
      {preview && preview.inventory.length > 0 && (
        <div>
          <h3 className="mb-1 text-sm text-muted">Стартовое снаряжение</h3>
          <ul className="text-sm">
            {preview.inventory.map((it, i) => (
              <li key={`${it.item}-${i}`}>
                {it.name}
                {it.qty > 1 ? ` ×${it.qty}` : ""}
                {it.equipped ? <span className="text-muted"> · надето</span> : null}
              </li>
            ))}
          </ul>
        </div>
      )}
      {preview && preview.errors.length > 0 && (
        <div>
          <h3 className="mb-1 text-sm text-warn">Что осталось</h3>
          <ul className="list-disc pl-5 text-sm">
            {preview.errors.map((e) => (
              <li key={e}>{e}</li>
            ))}
          </ul>
        </div>
      )}
      {preview && !preview.errors.length && <p className="text-sm text-ok">Герой готов.</p>}
    </section>
  );
}

function Big({ label, value }: { label: string; value: number | string }) {
  return (
    <div className="rounded-md border border-line p-1.5">
      <div className="text-xs text-muted">{label}</div>
      <div className="text-xl font-semibold">{value}</div>
    </div>
  );
}
