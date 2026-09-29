import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import ActionButton from "../components/ActionButton";
import { api } from "../lib/api";

interface Bonds {
  questions?: { id: string; text: string }[];
  answers?: Record<string, { text: string; private: boolean }>;
  status?: string;
}

/** Связи героя: 2–3 вопроса мастера о завязке и других героях. Открытые ответы видят все за столом,
 *  личные — только мастер. ИИ-мастер с сюжетом может заменить вопросы по умолчанию своими: тогда ждём. */
export default function BondsForm({ campaignId, heroId }: { campaignId: string; heroId: string }) {
  const qc = useQueryClient();
  const key = ["bonds", campaignId, heroId];
  const q = useQuery({
    queryKey: key,
    queryFn: () => api<{ bonds: Bonds; can_answer: boolean }>(`/api/campaigns/${campaignId}/characters/${heroId}/bonds`),
    refetchInterval: (x) => (x.state.data?.bonds.status === "asking" ? 4000 : false),
  });
  const b = q.data?.bonds;
  const [draft, setDraft] = useState<Record<string, { text: string; private: boolean }>>({});
  useEffect(() => {
    if (b) setDraft(Object.fromEntries((b.questions ?? []).map((x) => [x.id, b.answers?.[x.id] ?? { text: "", private: false }])));
  }, [b]);

  if (q.isError) return <p className="text-sm text-bad">Вопросы о связях не загрузились: {(q.error as Error).message}</p>;
  if (!b) return <p className="text-sm text-muted">Загружаем вопросы мастера…</p>;
  if (b.status === "asking") return <p className="text-sm text-muted">Мастер придумывает вопросы под сюжет…</p>;
  const answered = Object.keys(b.answers ?? {}).length;

  return (
    <div className="flex flex-col gap-3">
      <p className="text-sm text-muted">
        Ответы помогут мастеру вплести героя в сюжет. {answered ? `Отвечено ${answered} из ${b.questions?.length ?? 0}.` : "Можно ответить коротко."}
      </p>
      {(b.questions ?? []).map((x) => {
        const a = draft[x.id] ?? { text: "", private: false };
        return (
          <label key={x.id} className="flex flex-col gap-1 text-sm">
            <span>{x.text}</span>
            <textarea
              className="field min-h-14"
              maxLength={600}
              value={a.text}
              onChange={(e) => setDraft((d) => ({ ...d, [x.id]: { ...a, text: e.target.value } }))}
            />
            <span className="flex items-center gap-1.5 text-xs text-muted">
              <input
                type="checkbox"
                checked={a.private}
                onChange={(e) => setDraft((d) => ({ ...d, [x.id]: { ...a, private: e.target.checked } }))}
              />
              Лично: увидит только мастер
            </span>
          </label>
        );
      })}
      <div>
        <ActionButton
          primary
          run={async () => {
            const answers = Object.entries(draft).map(([id, a]) => ({ id, text: a.text.trim(), private: a.private }));
            qc.setQueryData(key, await api(`/api/campaigns/${campaignId}/characters/${heroId}/bonds`, { method: "PUT", body: { answers } }));
          }}
          done="Ответы у мастера"
        >
          Сохранить ответы
        </ActionButton>
      </div>
    </div>
  );
}
