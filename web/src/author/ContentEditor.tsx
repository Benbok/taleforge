import { useState } from "react";
import type { EditProposal } from "../lib/api.gen";
import type { Lore } from "./LoreEditor";

type Obj = { id: string; name: string };
export interface DraftContent {
  setting?: { lore?: Lore } & Record<string, unknown>;
  plot?: { locations?: Obj[]; npcs?: Obj[]; antagonists?: Obj[] } & Record<string, unknown>;
}

interface Props {
  content: DraftContent;
  busy: boolean;
  proposal: EditProposal | null;
  onRename(ref: string, name: string): void;
  onPropose(instruction: string): void;
  onApplyProposal(): void;
  onDismissProposal(): void;
  affected: string[];
}

export default function ContentEditor({
  content,
  busy,
  proposal,
  onRename,
  onPropose,
  onApplyProposal,
  onDismissProposal,
  affected,
}: Props) {
  const [names, setNames] = useState<Record<string, string>>({});
  const [ask, setAsk] = useState("");
  const groups: [string, Obj[], string][] = [
    ["Локации", content.plot?.locations ?? [], "🗺️"],
    ["NPC", content.plot?.npcs ?? [], "👤"],
    ["Антагонисты", content.plot?.antagonists ?? [], "⚔️"],
  ];

  return (
    <section aria-label="Места, NPC и правки" className="flex flex-col gap-6">
      {groups.map(([title, items, icon]) =>
        items.length ? (
          <div key={title} className="rounded-xl border border-line bg-surface p-4">
            <div className="mb-3 flex items-center justify-between border-b border-line-soft pb-2">
              <div className="flex items-center gap-2">
                <span>{icon}</span>
                <h3 className="font-heading text-sm font-semibold text-ink">{title}</h3>
              </div>
              <span className="text-xs text-muted">{items.length} шт.</span>
            </div>
            <ul className="flex flex-col gap-2.5">
              {items.map((item) => {
                const currentName = names[item.id] ?? item.name;
                const isModified = names[item.id] !== undefined && names[item.id] !== item.name;

                return (
                  <li
                    key={item.id}
                    className={`flex flex-wrap items-center gap-2 rounded-xl border p-2 transition-all sm:flex-nowrap ${
                      isModified
                        ? "border-accent/60 bg-raised"
                        : "border-line-soft bg-raised/50 hover:border-line"
                    }`}
                  >
                    <div className="flex min-w-0 flex-1 flex-col gap-0.5">
                      <span className="text-[11px] font-mono text-muted">{item.id}</span>
                      <input
                        className="min-h-10 w-full rounded-lg border border-line bg-surface px-2.5 text-sm text-ink transition-colors focus:border-accent focus:outline-none"
                        aria-label={`Название: ${item.id}`}
                        value={currentName}
                        onChange={(e) => setNames({ ...names, [item.id]: e.target.value })}
                      />
                    </div>
                    <button
                      className={`btn min-h-10 shrink-0 px-4 text-xs font-medium ${
                        isModified ? "btn-primary" : ""
                      }`}
                      type="button"
                      disabled={busy || !isModified}
                      onClick={() => onRename(item.id, names[item.id])}
                    >
                      Сохранить
                    </button>
                  </li>
                );
              })}
            </ul>
          </div>
        ) : null,
      )}

      {affected.length > 0 && (
        <p className="rounded-xl border border-warn/40 bg-warn/10 p-3 text-sm text-warn" role="status">
          <span className="font-medium">Станут устаревшими:</span> {affected.join(", ")}
        </p>
      )}

      {/* AI Co-pilot Box */}
      <div className="flex flex-col gap-3 rounded-2xl border-2 border-dashed border-accent/40 bg-surface p-4 sm:p-5">
        <div className="flex items-center gap-2">
          <span className="inline-flex h-7 w-7 items-center justify-center rounded-lg bg-accent/15 text-xs text-accent">✦</span>
          <div>
            <h3 className="font-heading text-sm font-semibold text-ink">ИИ-ассистент правок сюжета</h3>
            <p className="text-xs text-muted">Ничего не применится в мир без вашего подтверждения</p>
          </div>
        </div>

        <label className="flex flex-col gap-1.5 text-sm">
          <span className="text-muted text-xs">
            Попросить ИИ предложить правку (ничего не применяется без вашего подтверждения)
          </span>
          <div className="flex gap-2">
            <input
              className="min-h-11 flex-1 rounded-xl border border-line bg-raised px-3 text-sm text-ink transition-colors focus:border-accent focus:outline-none"
              placeholder="Например: Сделай конфликт более личным или добавь тайный мотив трактирщику"
              value={ask}
              onChange={(e) => setAsk(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter" && ask.trim() && !busy) {
                  e.preventDefault();
                  onPropose(ask);
                }
              }}
            />
            <button
              className="btn btn-primary min-h-11 shrink-0 px-4 text-sm font-medium"
              type="button"
              disabled={busy || !ask.trim()}
              onClick={() => onPropose(ask)}
            >
              Предложить
            </button>
          </div>
        </label>

        {proposal && (
          <div
            role="group"
            aria-label="Предложение ИИ"
            className="flex flex-col gap-2 rounded-xl border border-accent/60 bg-raised p-3 text-sm"
          >
            <div className="flex items-center gap-2 text-xs font-semibold text-accent">
              <span>✦ Готово предложение изменений</span>
            </div>
            <p className="text-xs text-ink-2">
              Операций: {(proposal.patch.operations ?? []).length}. Затронет:{" "}
              {(proposal.affected ?? []).map((a) => `${a.kind}:${a.ref}`).join(", ") || "ничего"}
            </p>
            <div className="mt-1 flex gap-2">
              <button
                className="btn btn-primary min-h-10 px-4 text-xs font-medium"
                type="button"
                disabled={busy}
                onClick={onApplyProposal}
              >
                Применить
              </button>
              <button
                className="btn min-h-10 px-3 text-xs"
                type="button"
                onClick={onDismissProposal}
              >
                Отклонить
              </button>
            </div>
          </div>
        )}
      </div>
    </section>
  );
}
