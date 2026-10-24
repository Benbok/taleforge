import { useState } from 'react';
import { api } from '../lib/api';
import type { HeroCard, StartingEquipment } from '../lib/universal';
import StartingEquipmentList from './StartingEquipmentList';

interface EquipmentProposal {
  id: string;
  edit: { starting_equipment: StartingEquipment };
}

export default function HeroEquipmentStudio({ card, onSaved }: { card: HeroCard; onSaved: (card: HeroCard) => void }) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [preview, setPreview] = useState<EquipmentProposal | null>(null);
  const [status, setStatus] = useState('');
  if (!card.editable) return null;
  const url = `/api/me/characters/${card.id}`;

  async function generate() {
    setBusy(true); setError(''); setStatus('');
    try {
      const proposal = await api<EquipmentProposal>(url + '/equipment-proposals', {
        body: { expected_revision: card.revision },
      });
      setPreview(proposal);
    } catch (err) {
      setError(`Не удалось подобрать снаряжение. Прежний набор сохранён. ${(err as Error).message}`);
    } finally { setBusy(false); }
  }

  async function confirm() {
    if (!preview) return;
    setBusy(true); setError('');
    try {
      const saved = await api<HeroCard>(url + `/edit-proposals/${preview.id}/confirm`, {
        body: { request_key: `equipment:${preview.id}` },
      });
      onSaved(saved); setPreview(null); setStatus('Новое снаряжение сохранено');
    } catch (err) { setError((err as Error).message); } finally { setBusy(false); }
  }

  return <div className='mt-3 space-y-3'>
    <button type='button' className='btn btn-outline-copper' disabled={busy} onClick={() => void generate()}>
      {busy ? 'Мастер подбирает снаряжение…' : card.equipment?.length ? 'Пересоздать снаряжение' : 'Создать снаряжение'}
    </button>
    <p className='text-xs text-muted'>Мастер подберёт оружие и броню по сохранённому описанию. Вы сможете рассмотреть набор перед заменой.</p>
    {preview && <section className='space-y-3 rounded-xl border border-accent/40 bg-accent/5 p-4' aria-label='Новое снаряжение'>
      <h4 className='font-heading text-lg text-ink'>Предложение мастера</h4>
      <StartingEquipmentList items={[preview.edit.starting_equipment.weapon, preview.edit.starting_equipment.armor]} />
      <p className='text-xs text-muted'>Заменится только набор в библиотеке. Созданные игровые копии сохранят своё снаряжение.</p>
      <div className='flex flex-wrap gap-2'>
        <button type='button' className='btn btn-primary' disabled={busy} onClick={() => void confirm()}>Заменить снаряжение</button>
        <button type='button' className='btn' disabled={busy} onClick={() => setPreview(null)}>Оставить прежнее</button>
      </div>
    </section>}
    {error && <p role='alert' className='text-sm text-bad'>{error}</p>}
    {status && <p role='status' className='text-sm text-patina'>{status}</p>}
  </div>;
}
