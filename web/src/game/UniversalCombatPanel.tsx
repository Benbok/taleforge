import { useRef, useState } from 'react';
import { api } from '../lib/api';

export interface CombatView {
  life_state: 'conscious' | 'unconscious' | 'stable' | 'dead';
  ac: string;
  game_seconds: string;
  active?: boolean;
  pending_request?: { kind: string; item_id?: string | null; target_id?: string | null; request_key: string } | null;
  inventory: { id: string; name: string; kind: string; status_name: string; quantity: string;
    equipped: boolean; defense_bonus?: string; attack_bonus?: string; damage_bonus?: string;
    description?: string; base_dice?: string; restore_pool?: string | null; restore_amount?: string }[];
  enemies: { id: string; name: string; condition?: string; hp?: string | null; life_state?: string }[];
}

export default function UniversalCombatPanel({ campaignId, heroId, state, onUpdated }: {
  campaignId: string; heroId: string; state?: CombatView | null; onUpdated?: (card: unknown) => void;
}) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [selected, setSelected] = useState('');
  const retry = useRef<{ kind: string; item_id?: string | null; target_id?: string | null; request_key: string } | null>(null);
  if (!state) return null;
  const awake = state.life_state === 'conscious';
  const enemies = state.enemies.filter(enemy => !enemy.life_state || enemy.life_state === 'conscious');
  const target = enemies.some(enemy => enemy.id === selected) ? selected : enemies[0]?.id;
  const labels = { conscious: 'Готов к действию', unconscious: 'Без сознания', stable: 'Состояние стабильно', dead: 'Герой погиб' };

  async function send(kind: string, item_id?: string, target_id?: string, repeat = false) {
    if (busy) return;
    const request = repeat && (state?.pending_request || retry.current) ? (state?.pending_request || retry.current)! : { kind, item_id, target_id, request_key: crypto.randomUUID() };
    retry.current = request;
    setBusy(true); setError('');
    try {
      const card = await api(`/api/campaigns/${campaignId}/characters/${heroId}/universal-actions`, {
        method: 'POST', body: JSON.stringify(request),
      });
      onUpdated?.(card);
      retry.current = null;
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Действие не завершилось. Можно безопасно повторить запрос.');
    } finally { setBusy(false); }
  }

  return <section className='space-y-3 rounded-xl border border-line-soft bg-surface-2/40 p-3 text-xs' aria-label='Бой и снаряжение'>
    <div className='flex items-center justify-between gap-2'>
      <h3 className='font-semibold text-ink'>Снаряжение и защита</h3>
      <span className='rounded border border-accent/30 px-2 py-1 font-mono text-accent'>КД {state.ac}</span>
    </div>
    <p className={awake ? 'text-muted' : 'font-semibold text-accent'}>{labels[state.life_state]}</p>
    {!awake && <p className='leading-relaxed text-muted'>Пока герой не может действовать. Мастер сохраняет необходимые события состояния; чтение страницы не запускает новые проверки.</p>}
    <div className='space-y-2'>
      {state.inventory.map(item => <div key={item.id} className='rounded-lg border border-line-soft bg-bg/30 p-2.5'>
        <div className='flex items-start justify-between gap-2'>
          <div><p className='font-medium text-ink'>{item.name}</p><p className='mt-0.5 text-[10px] text-muted'>{item.status_name} · {item.equipped ? 'Надето' : 'В инвентаре'} · {item.quantity} шт.</p></div>
          {awake && <button disabled={busy || !!state.pending_request} className='btn-ghost shrink-0 px-2 py-1' aria-label={`${item.kind === 'consumable' ? 'Использовать' : item.equipped ? 'Снять' : 'Надеть'} ${item.name}`}
            onClick={() => send(item.kind === 'consumable' ? 'consume' : item.equipped ? 'unequip' : 'equip', item.id)}>
            {item.kind === 'consumable' ? 'Использовать' : item.equipped ? 'Снять' : 'Надеть'}
          </button>}
        </div>
        {item.description && <p className='mt-1.5 leading-relaxed text-muted'>{item.description}</p>}
        {item.kind === 'armor' && <p className='mt-1 text-patina'>Защита +{item.defense_bonus ?? '0'}</p>}
        {item.kind === 'weapon' && <p className='mt-1 text-patina'>{item.base_dice ?? '1d6'} · попадание +{item.attack_bonus ?? '0'} · урон +{item.damage_bonus ?? '0'}</p>}
        {awake && item.kind === 'weapon' && item.equipped && target && <button disabled={busy || !!state.pending_request} className='btn-ghost mt-2 px-2 py-1' onClick={() => send('weapon_attack',item.id,target)}>Атаковать оружием</button>}
      </div>)}
    </div>
    {enemies.length > 0 && <div className='space-y-2 border-t border-line-soft pt-2'>
      <label className='block text-muted' htmlFor='combat-target'>Цель атаки</label>
      <select id='combat-target' value={target} onChange={event => setSelected(event.target.value)} className='w-full rounded border border-line bg-bg px-2 py-1.5'>
        {enemies.map(enemy => <option key={enemy.id} value={enemy.id}>{enemy.name} · {enemy.condition ?? 'В бою'}{enemy.hp != null ? ` · HP ${enemy.hp}` : ''}</option>)}
      </select>
      {awake && <button disabled={busy || !!state.pending_request} className='btn-ghost px-2 py-1' onClick={() => send('guard')}>Защищаться</button>}
      <p className='leading-relaxed text-muted'>После игрового действия может ответить один способный действовать противник. Повтор запроса сохраняет прежние броски.</p>
    </div>}
    {state.pending_request && <div className='rounded border border-accent/30 p-2 text-muted'>
      <p>Действие сохранено. Завершите его перед следующим ходом.</p>
      <button disabled={busy} className='mt-2 underline text-accent' onClick={() => send('',undefined,undefined,true)}>Завершить сохранённое действие</button>
    </div>}
    {error && <div role='alert' className='rounded border border-bad/30 p-2 text-bad'>
      <p>{error}</p><button disabled={busy} className='mt-1 underline' onClick={() => send('',undefined,undefined,true)}>Повторить запрос</button>
    </div>}
    {busy && <p role='status' className='text-muted'>Действие обрабатывается…</p>}
  </section>;
}
