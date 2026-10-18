import { useState } from "react";
import type { EditProposal } from "../lib/api.gen";
import LoreEditor, { type Lore } from "./LoreEditor";

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
  onLore(fields: Record<string, unknown>): void;
  onPropose(instruction: string): void;
  onApplyProposal(): void;
  onDismissProposal(): void;
  affected: string[];
}

export default function ContentEditor({ content, busy, proposal, onRename, onLore, onPropose, onApplyProposal, onDismissProposal, affected }: Props) {
  const [names, setNames] = useState<Record<string, string>>({});
  const [ask, setAsk] = useState("");
  const groups: [string, Obj[]][] = [
    ["Локации", content.plot?.locations ?? []],
    ["NPC", content.plot?.npcs ?? []],
    ["Антагонисты", content.plot?.antagonists ?? []],
  ];
  return (
    <section aria-label="Редактор содержимого" className="flex flex-col gap-4">
      <LoreEditor lore={content.setting?.lore ?? {}} busy={busy} onSave={onLore} />
      {groups.map(([title, items]) =>
        items.length ? (
          <div key={title}>
            <h3 className="font-heading text-sm text-muted">{title}</h3>
            <ul className="mt-1 flex flex-col gap-2">
              {items.map((item) => (
                <li key={item.id} className="flex flex-wrap items-center gap-2">
                  <input className="min-h-11 flex-1 rounded-lg border border-line bg-raised px-2" aria-label={`Название: ${item.id}`} value={names[item.id] ?? item.name} onChange={(e) => setNames({ ...names, [item.id]: e.target.value })} />
                  <button className="btn min-h-11 px-3 text-sm" type="button" disabled={busy || names[item.id] === undefined || names[item.id] === item.name} onClick={() => onRename(item.id, names[item.id])}>Сохранить</button>
                </li>
              ))}
            </ul>
          </div>
        ) : null,
      )}
      {affected.length > 0 && (
        <p className="rounded-lg border border-warn/40 bg-warn/10 p-3 text-sm" role="status">Станут устаревшими: {affected.join(", ")}</p>
      )}
      <div className="flex flex-col gap-2 rounded-lg border border-line p-3">
        <label className="flex flex-col gap-1 text-sm">
          <span className="text-muted">Попросить ИИ предложить правку (ничего не применяется без вашего подтверждения)</span>
          <input className="min-h-11 rounded-lg border border-line bg-raised px-2" value={ask} onChange={(e) => setAsk(e.target.value)} />
        </label>
        <button className="btn min-h-11 self-start px-3 text-sm" type="button" disabled={busy || !ask.trim()} onClick={() => onPropose(ask)}>Предложить</button>
        {proposal && (
          <div role="group" aria-label="Предложение ИИ" className="text-sm">
            <p>Операций: {(proposal.patch.operations ?? []).length}. Затронет: {(proposal.affected ?? []).map((a) => `${a.kind}:${a.ref}`).join(", ") || "ничего"}</p>
            <div className="mt-2 flex gap-2">
              <button className="btn btn-primary min-h-11 px-3" type="button" disabled={busy} onClick={onApplyProposal}>Применить</button>
              <button className="btn min-h-11 px-3" type="button" onClick={onDismissProposal}>Отклонить</button>
            </div>
          </div>
        )}
      </div>
    </section>
  );
}
