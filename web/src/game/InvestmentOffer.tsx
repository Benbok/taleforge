import { useEffect, useState } from 'react';
import { api } from '../lib/api';
import { abilityNames, type AbilityKey } from '../lib/universal';

const GENITIVE: Record<string, string> = { str: 'Силы', dex: 'Ловкости', int: 'Интеллекта', wis: 'Мудрости', cha: 'Харизмы' };
import type { ChatMessage } from '../lib/types';
import { useGame } from '../stores/game';

/** Карточка паузы: провал можно выкупить энергией той же характеристики. Решает игрок героя, остальные ждут. */
export default function InvestmentOffer({ m, mySeat, heroName }: { m: ChatMessage; mySeat: string | null; heroName: string }) {
  const campaignId = useGame((s) => s.snapshot?.campaign.id);
  const d = m.data as unknown as {
    mid: string; seat_id: string; status: string; attribute: string; shortfall: number; price: number; available: number; deadline_ts: number;
  };
  const [busy, setBusy] = useState(false);
  const [left, setLeft] = useState(() => Math.max(0, d.deadline_ts - Math.floor(Date.now() / 1000)));
  useEffect(() => {
    if (d.status !== 'offered') return;
    const timer = setInterval(() => setLeft(Math.max(0, d.deadline_ts - Math.floor(Date.now() / 1000))), 1000);
    return () => clearInterval(timer);
  }, [d.status, d.deadline_ts]);
  const genitive = GENITIVE[d.attribute] ?? abilityNames[d.attribute as AbilityKey] ?? d.attribute;
  const answer = async (accept: boolean) => {
    setBusy(true);
    try {
      await api(`/api/campaigns/${campaignId}/investments/${d.mid}`, { method: 'POST', body: { accept } });
    } finally {
      setBusy(false);
    }
  };
  const settled = d.status === 'invested' ? 'вложил усилие и добился успеха' : 'принял провал';
  return (
    <section className='tf-pop mx-auto w-full max-w-xl rounded-xl border border-accent/40 bg-surface p-4 text-sm' aria-label='Вложить усилие'>
      {d.status !== 'offered' ? (
        <p className='text-muted'>{heroName} {settled}.</p>
      ) : mySeat === d.seat_id ? (
        <>
          <p className='text-ink'>Не хватило {d.shortfall} до успеха. Вложить {d.price} {genitive} (есть {d.available})?</p>
          <div className='mt-3 flex flex-wrap items-center gap-2'>
            <button type='button' disabled={busy} onClick={() => answer(true)} className='rounded-lg border border-accent bg-accent/10 px-3 py-1.5 font-semibold text-accent hover:bg-accent/20 disabled:opacity-60'>Вложить</button>
            <button type='button' disabled={busy} onClick={() => answer(false)} className='rounded-lg border border-line px-3 py-1.5 text-muted hover:text-ink disabled:opacity-60'>Принять провал</button>
            <span className='text-xs text-muted'>{left} с</span>
          </div>
        </>
      ) : (
        <p className='text-muted'>{heroName} решает, вложить ли {d.price} {genitive}… {left} с</p>
      )}
    </section>
  );
}
