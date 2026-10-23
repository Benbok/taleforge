import { useQuery, useQueryClient } from '@tanstack/react-query';
import { useState } from 'react';
import { api } from '../lib/api';
import { abilityKeys, abilityNames, type HeroDialogue } from '../lib/universal';
import DeleteHeroDraft from './DeleteHeroDraft';

export default function HeroCreationDialogue({ id, onCreated, onDeleted }: { id: string; onCreated: (id: string) => void; onDeleted?: () => void }) {
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
  return <section className='card flex flex-col gap-6 p-5 md:p-7'>
    <header className='flex flex-wrap items-start justify-between gap-3 border-b border-line pb-5'><div>
      <p className='mb-2 text-xs uppercase tracking-widest text-patina'>02 / Вместе с мастером</p><h2 className='font-heading text-xl'>Беседа с мастером</h2>
      <p className='mt-2 text-sm text-muted'>Уточняйте детали, задавайте вопросы и выбирайте то, что подходит вашему герою.</p>
    </div><span className='workshop-status'>Черновик сохранён</span></header>
    <details className='rounded-xl border border-line bg-bg p-4'><summary className='cursor-pointer text-sm font-semibold'>Ваш замысел{draft.description.name ? `: ${draft.description.name}` : ''}</summary>
      <p className='mt-3 whitespace-pre-wrap text-sm leading-relaxed text-muted'>{draft.description.identity}</p></details>
    <div className='flex flex-col gap-4'>{draft.transcript.map((message, index) => <div className={`workshop-message ${message.role === 'user' ? 'is-user' : ''}`} key={index}>
      <p className='mb-2 text-xs font-semibold uppercase tracking-widest text-patina'>{message.role === 'user' ? 'Вы' : 'Мастер'}</p>
      <p className='whitespace-pre-wrap text-sm leading-relaxed'>{message.content}</p></div>)}</div>
    {draft.proposal && <section className='workshop-proposal rounded-xl border border-line p-5' aria-label='Предложение характеристик'>
      <div className='mb-5'><p className='text-xs uppercase tracking-widest text-patina'>Можно обсудить и изменить</p><h3 className='mt-2 font-heading text-lg'>Предложение характеристик</h3>
        {draft.description.name && <p className='mt-1 text-sm text-muted'>{draft.description.name}</p>}</div>
      <div className='grid gap-3 sm:grid-cols-2 lg:grid-cols-3'>{abilityKeys.map(key => <div className='rounded-xl border border-line bg-surface p-4' key={key}>
        <div className='flex items-center justify-between gap-3'><strong className='text-sm'>{abilityNames[key]}</strong><span className='font-mono text-2xl text-accent'>{draft.proposal!.abilities[key]}</span></div>
        <p className='mt-2 text-xs leading-relaxed text-muted'>{draft.proposal!.explanations[key]}</p></div>)}</div>
      <p className='mt-4 text-xs leading-relaxed text-muted'>Герой начнёт с первого уровня. Вещи и приёмы появятся в игре. Карточка создастся только после вашего подтверждения.</p>
    </section>}
    {draft.status === 'confirmed' ? <button className='btn' onClick={() => onCreated(draft.hero_id!)}>Открыть героя</button> : <>
      <label className='flex flex-col gap-2 text-sm font-semibold'>Ответ или уточнение замысла<textarea className='field workshop-field min-h-28 font-normal' placeholder='Например: герой больше полагается на знания, чем на силу. Как это отразить?' disabled={busy} value={answer} maxLength={4000} onChange={event => setAnswer(event.target.value)} /></label>
      <div className='flex flex-wrap gap-3'><button className='btn' disabled={busy || !answer.trim()} onClick={() => void send()}>Ответить мастеру</button>
        {draft.status === 'ready' && <button className='btn btn-primary' disabled={busy} onClick={() => void send(true)}>Подтвердить героя</button>}</div>
    </>}
    {busy && <p role='status' className='workshop-notice'>Мастер готовит ответ…</p>}{error && <p role='alert' className='workshop-notice border-bad'>{error}</p>}
    {error && <button className='btn' onClick={() => void query.refetch()}>Обновить предложение</button>}
    {['questions', 'ready'].includes(draft.status) && <div className='border-t border-line pt-4'>
      <DeleteHeroDraft draft={draft} onDeleted={onDeleted} disabled={busy} />
    </div>}
  </section>;
}
