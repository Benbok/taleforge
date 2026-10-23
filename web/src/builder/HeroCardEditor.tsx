import { useState } from 'react';
import { api } from '../lib/api';
import { abilityKeys, abilityNames, type AbilityKey, type EditProposal, type HeroCard, type HeroEdit } from '../lib/universal';
import HeroDescriptionForm from './HeroDescriptionForm';

export default function HeroCardEditor({ card, onSaved, onReload }: { card: HeroCard; onSaved: (card: HeroCard) => void; onReload: () => void }) {
  const [description, setDescription] = useState(card.sheet.description);
  const [scores, setScores] = useState(card.sheet.abilities);
  const [baseRevision, setBaseRevision] = useState(card.revision);
  const [message, setMessage] = useState(''), [error, setError] = useState(''), [status, setStatus] = useState('');
  const [busy, setBusy] = useState(false);
  const [preview, setPreview] = useState<{ edit: HeroEdit; id?: string; explanations?: EditProposal['explanations']; key: string } | null>(null);
  if (!card.editable) return null;
  const url = `/api/me/characters/${card.id}`;
  function swap(key: AbilityKey, value: string) {
    const other = abilityKeys.find(k => scores[k] === value)!;
    setScores({ ...scores, [key]: value, [other]: scores[key] }); setPreview(null);
  }
  async function propose() {
    setBusy(true); setError(''); setStatus('');
    try {
      const result = await api<EditProposal>(url + '/edit-proposals', { body: { message, expected_revision: baseRevision } });
      setPreview({ ...result, key: crypto.randomUUID() });
    } catch (err) { setError((err as Error).message); } finally { setBusy(false); }
  }
  async function save() {
    if (!preview) return;
    setBusy(true); setError('');
    try {
      const saved = preview.id ? await api<HeroCard>(url + `/edit-proposals/${preview.id}/confirm`, { body: { request_key: preview.key } }) :
        await api<HeroCard>(url, { method: 'PATCH', body: { edit: preview.edit, request_key: preview.key } });
      onSaved(saved); setDescription(saved.sheet.description); setScores(saved.sheet.abilities);
      setBaseRevision(saved.revision); setPreview(null); setStatus('Сохранено');
    } catch (err) { setError((err as Error).message); } finally { setBusy(false); }
  }
  return <section className='card flex flex-col gap-5 p-5' aria-label='Редактор базового героя'><h2 className='font-heading text-xl'>Изменить образ</h2>
    <HeroDescriptionForm value={description} onChange={value => { setDescription(value); setPreview(null); }} disabled={busy} />
    <fieldset className='grid grid-cols-2 gap-3 sm:grid-cols-3'><legend className='mb-3 text-sm'>Перестановка стартового набора</legend>
      {abilityKeys.map(key => <label key={key} className='flex flex-col gap-1 text-sm'>{abilityNames[key]}
        <select className='field' aria-label={`${abilityNames[key]}: значение`} value={scores[key]} disabled={busy} onChange={event => swap(key, event.target.value)}>
          {['15', '14', '13', '12', '10', '8'].map(value => <option key={value} value={value}>{value}</option>)}
        </select></label>)}</fieldset>
    {card.revision !== baseRevision && <div className='rounded-lg border border-warn p-3'>
      <p>Сохранённая карточка обновилась. Сверьте её выше с вашим черновиком перед повторным сохранением.</p>
      <button className='btn mt-2' disabled={busy} onClick={() => { setBaseRevision(card.revision); setPreview(null); setError(''); }}>Продолжить с моим черновиком</button>
    </div>}
    <button className='btn self-start' disabled={busy} onClick={() => { setStatus(''); setError(''); setPreview({ edit: { description_patch: description, base_scores: scores, expected_revision: baseRevision }, key: crypto.randomUUID() }); }}>Предпросмотр правок</button>
    <label className='flex flex-col gap-1'>Правка через мастера<textarea className='field' value={message} maxLength={4000} onChange={event => setMessage(event.target.value)} /></label>
    <button className='btn self-start' disabled={busy || !message.trim()} onClick={() => void propose()}>Предложить версию</button>
    {preview && <section className='rounded-lg border border-accent p-4 flex flex-col gap-3' aria-label='Предпросмотр правок'>
      <h3 className='font-semibold'>Предложение для подтверждения</h3>
      {Object.entries(preview.edit.description_patch ?? {}).map(([key, value]) => <p key={key} className='whitespace-pre-wrap'>{value}</p>)}
      {abilityKeys.map(key => <p key={key}>{abilityNames[key]}: {preview.edit.base_scores?.[key] ?? scores[key]}{preview.explanations ? ` — ${preview.explanations[key]}` : ''}</p>)}
      <p className='text-xs text-muted'>Изменения будут сохранены после подтверждения. Игровые копии живут отдельно.</p>
      <div className='flex gap-3'><button className='btn btn-primary' disabled={busy} onClick={() => void save()}>Подтвердить правки</button>
        <button className='btn' disabled={busy} onClick={() => setPreview(null)}>Отменить</button></div>
    </section>}
    {busy && <p role='status'>Готовлю предложение…</p>}{status && <p role='status'>{status}</p>}{error && <p role='alert'>{error}</p>}
    {error && <button className='btn' onClick={onReload}>Обновить сохранённую карточку</button>}
  </section>;
}
