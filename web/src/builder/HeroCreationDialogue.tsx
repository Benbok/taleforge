import { useQuery, useQueryClient } from '@tanstack/react-query';
import { useState } from 'react';
import { api } from '../lib/api';
import { abilityKeys, abilityNames, type HeroDialogue } from '../lib/universal';

export default function HeroCreationDialogue({ id, onCreated }: { id: string; onCreated: (id: string) => void }) {
  const qc = useQueryClient();
  const query = useQuery({ queryKey: ['hero-dialogue', id], queryFn: () => api<HeroDialogue>(`/api/hero-creation/dialogues/${id}`) });
  const [answer, setAnswer] = useState(''), [error, setError] = useState(''), [busy, setBusy] = useState(false);
  const draft = query.data;
  async function send(confirm = false) {
    if (!draft) return;
    setBusy(true); setError('');
    try {
      if (confirm) {
        const result = await api<{ hero_id: string }>(`/api/hero-creation/dialogues/${id}/confirm`, { body: { expected_revision: draft.revision } });
        onCreated(result.hero_id);
      } else {
        const result = await api<HeroDialogue>(`/api/hero-creation/dialogues/${id}/answers`, { body: { answer, expected_revision: draft.revision } });
        qc.setQueryData(['hero-dialogue', id], result); setAnswer('');
      }
    } catch (err) { setError((err as Error).message); } finally { setBusy(false); }
  }
  if (query.error) return <p role='alert'>{query.error.message}</p>;
  if (!draft) return <p>Загружаю беседу…</p>;
  return <section className='card flex flex-col gap-4 p-5'><h2 className='font-heading text-xl'>Беседа с мастером</h2>
    <p className='whitespace-pre-wrap'>{draft.description.identity}</p>
    <div className='flex flex-col gap-3'>{draft.transcript.map((message, index) => <p className='whitespace-pre-wrap' key={index}>
      <strong>{message.role === 'user' ? 'Вы' : 'Мастер'}: </strong>{message.content}</p>)}</div>
    {draft.proposal && <><h3 className='font-semibold'>Предложение характеристик</h3>
      <p>{draft.description.name}</p>
      {abilityKeys.map(key => <div key={key}><strong>{abilityNames[key]}: {draft.proposal!.abilities[key]}</strong><p>{draft.proposal!.explanations[key]}</p></div>)}
      <p className='text-sm text-muted'>Герой начнёт с первого уровня. Вещи и приёмы появятся в игре.</p>
    </>}
    {draft.status === 'confirmed' ? <button className='btn' onClick={() => onCreated(draft.hero_id!)}>Открыть героя</button> : <>
      <label className='flex flex-col gap-1'>Ответ или уточнение замысла<textarea className='field' value={answer} maxLength={4000} onChange={event => setAnswer(event.target.value)} /></label>
      <div className='flex flex-wrap gap-3'><button className='btn' disabled={busy || !answer.trim()} onClick={() => void send()}>Ответить мастеру</button>
        {draft.status === 'ready' && <button className='btn btn-primary' disabled={busy} onClick={() => void send(true)}>Подтвердить героя</button>}</div>
    </>}
    {busy && <p role='status'>Мастер готовит ответ…</p>}{error && <p role='alert'>{error}</p>}
    {error && <button className='btn' onClick={() => void query.refetch()}>Обновить предложение</button>}
  </section>;
}
