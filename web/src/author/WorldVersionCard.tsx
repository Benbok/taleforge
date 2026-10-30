import { Link } from "react-router-dom";
import type { WorldDraft } from "./WorldDescriptionForm";

export interface AcceptedVersion {
  version: string;
  published_at: string;
  adventure_id: string;
  draft_revision: number;
}

interface Props {
  draft: WorldDraft;
  version: AcceptedVersion;
  onEditNewVersion: () => void;
  onLaunchAdventure?: () => void;
}

export default function WorldVersionCard({
  draft,
  version,
  onEditNewVersion,
  onLaunchAdventure,
}: Props) {
  return (
    <div className="flex flex-col gap-6">
      {/* Зелёный статус подтверждения версии */}
      <section className="card flex flex-col items-start gap-4 p-6 border-patina/40 bg-patina/5">
        <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4 w-full">
          <div className="flex items-center gap-3.5">
            <span className="flex h-11 w-11 shrink-0 items-center justify-center rounded-full bg-patina/20 border border-patina text-patina-hi font-bold text-lg">
              ✓
            </span>
            <div>
              <div className="flex items-center gap-2">
                <h2 className="font-heading text-xl sm:text-2xl font-bold text-ink">{draft.title}</h2>
                <span className="rounded-full border border-patina bg-patina/20 px-2.5 py-0.5 font-mono text-xs font-bold text-patina-hi">
                  ВЕРСИЯ {version.version}
                </span>
              </div>
              <p className="font-mono text-xs text-patina-hi mt-0.5">
                Неизменяемый слепок мира зафиксирован · Готов к независимым приключениям
              </p>
            </div>
          </div>

          <div className="flex flex-wrap items-center gap-2.5">
            {onLaunchAdventure ? (
              <button
                type="button"
                onClick={onLaunchAdventure}
                className="btn btn-primary font-mono text-xs tracking-wider px-4 py-2"
              >
                ЗАПУСТИТЬ СТОЛ (НОВОЕ ПРОХОЖДЕНИЕ) →
              </button>
            ) : (
              <Link
                to={`/new?pack=${encodeURIComponent(version.adventure_id)}`}
                className="btn btn-primary font-mono text-xs tracking-wider px-4 py-2"
              >
                ЗАПУСТИТЬ СТОЛ (НОВОЕ ПРОХОЖДЕНИЕ) →
              </Link>
            )}

            <button
              type="button"
              onClick={onEditNewVersion}
              className="btn btn-outline-copper font-mono text-xs px-3 py-2"
            >
              Внести изменения (новая версия)
            </button>
          </div>
        </div>
      </section>

      {/* Паспорт мира и приключения */}
      <div className="grid gap-6 md:grid-cols-2">
        {/* Публичная часть (для игроков стола) */}
        <section className="card flex flex-col gap-4 border border-line bg-surface p-5 sm:p-6">
          <div className="border-b border-line pb-2.5 flex items-center justify-between">
            <div>
              <span className="font-mono text-[10px] uppercase tracking-wider text-accent">Публичный паспорт</span>
              <h3 className="font-heading text-lg font-bold text-ink">Сведения для исследователей</h3>
            </div>
            <span className="rounded-full bg-raised border border-line px-2 py-0.5 font-mono text-[10px] text-muted">
              ВИДЯТ ИГРОКИ
            </span>
          </div>

          <div className="flex flex-col gap-3.5 text-sm">
            <div>
              <span className="font-mono text-xs font-semibold text-muted uppercase">Замысел:</span>
              <p className="mt-1 text-ink font-medium leading-relaxed">{draft.premise || "—"}</p>
            </div>

            <div>
              <span className="font-mono text-xs font-semibold text-muted uppercase">Устройство мира:</span>
              <p className="mt-1 text-ink-2 text-xs leading-relaxed">{draft.world || "—"}</p>
            </div>

            <div>
              <span className="font-mono text-xs font-semibold text-muted uppercase">Обитатели и масштаб:</span>
              <p className="mt-1 text-ink-2 text-xs leading-relaxed">{draft.inhabitants || "—"}</p>
            </div>

            <div>
              <span className="font-mono text-xs font-semibold text-muted uppercase">Стартовая ситуация:</span>
              <p className="mt-1 text-ink-2 text-xs leading-relaxed">{draft.start || "—"}</p>
            </div>
          </div>
        </section>

        {/* Руководство мастера (законы и ограничения) */}
        <section className="card flex flex-col gap-4 border border-line bg-surface p-5 sm:p-6">
          <div className="border-b border-line pb-2.5 flex items-center justify-between">
            <div>
              <span className="font-mono text-[10px] uppercase tracking-wider text-accent">Внутренний свод</span>
              <h3 className="font-heading text-lg font-bold text-ink">Законы и руководство мастера</h3>
            </div>
            <span className="rounded-full bg-raised border border-line px-2 py-0.5 font-mono text-[10px] text-muted">
              ПРАВИЛА ИИ-ВЕДУЩЕГО
            </span>
          </div>

          <div className="flex flex-col gap-3.5 text-sm">
            <div>
              <span className="font-mono text-xs font-semibold text-muted uppercase">Фундаментальные законы:</span>
              <p className="mt-1 text-ink leading-relaxed text-xs">{draft.laws || "Стандартные законы"}</p>
            </div>

            <div>
              <span className="font-mono text-xs font-semibold text-muted uppercase">Принципы способностей:</span>
              <p className="mt-1 text-ink-2 leading-relaxed text-xs">{draft.powers || "—"}</p>
            </div>

            <div>
              <span className="font-mono text-xs font-semibold text-muted uppercase">Атмосфера и табу:</span>
              <p className="mt-1 text-ink-2 leading-relaxed text-xs">{draft.style || "Стандартный тон"}</p>
            </div>

            {draft.secret_text && (
              <div className="rounded-xl border border-warn/40 bg-warn/5 p-3.5 mt-2">
                <span className="font-mono text-[11px] font-bold text-warn uppercase">
                  Тайны мастера (секреты автора):
                </span>
                <p className="mt-1 text-xs text-ink leading-relaxed">{draft.secret_text}</p>
              </div>
            )}
          </div>
        </section>
      </div>

      {/* Информационная плашка об изоляции прохождений */}
      <div className="rounded-xl border border-line bg-raised/50 p-4 text-xs text-muted flex flex-col sm:flex-row sm:items-center justify-between gap-3">
        <div className="flex items-center gap-2">
          <span className="text-accent font-bold">ℹ</span>
          <span>
            Каждый запущенный стол получает собственную копию состояния. Любые новые NPC, предметы и последствия в игре
            не меняют этот базовый слепок.
          </span>
        </div>
        <Link to="/" className="btn btn-outline-copper h-8 px-3 text-xs font-mono shrink-0">
          К списку столов
        </Link>
      </div>
    </div>
  );
}

