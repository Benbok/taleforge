import { useQuery, useQueryClient } from '@tanstack/react-query';
import { useState } from 'react';
import { api } from '../lib/api';
import { abilityKeys, abilityNames, type HeroDialogue } from '../lib/universal';
import DeleteHeroDraft from './DeleteHeroDraft';
import StartingEquipmentList from './StartingEquipmentList';

export default function HeroCreationDialogue({
  id,
  onCreated,
  onDeleted,
}: {
  id: string;
  onCreated: (id: string) => void;
  onDeleted?: () => void;
}) {
  const qc = useQueryClient();
  const query = useQuery({
    queryKey: ['hero-dialogue', id],
    queryFn: () => api<HeroDialogue>(`/api/hero-creation/dialogues/${id}`),
  });
  const [answer, setAnswer] = useState('');
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const draft = query.data;

  async function send(confirm = false, answerOverride?: string) {
    if (!draft) return;
    setBusy(true);
    setError('');
    try {
      if (confirm) {
        const result = await api<{ hero_id: string }>(`/api/hero-creation/dialogues/${id}/confirm`, {
          body: { expected_revision: draft.revision },
        });
        onCreated(result.hero_id);
      } else {
        const result = await api<HeroDialogue>(`/api/hero-creation/dialogues/${id}/answers`, {
          body: { answer: answerOverride ?? answer, expected_revision: draft.revision },
        });
        qc.setQueryData(['hero-dialogue', id], result);
        setAnswer('');
      }
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  }

  if (query.error) return <p role='alert' className='workshop-notice border-bad'>{query.error.message}</p>;
  if (!draft) return <p className='text-sm text-muted'>Загружаю беседу…</p>;

  const isReady = draft.status === 'ready';

  return (
    <section className='card flex flex-col gap-6 p-5 md:p-8'>
      {/* Шапка беседы с мастером */}
      <header className='flex flex-wrap items-start justify-between gap-3 border-b border-line pb-5'>
        <div>
          <div className='mb-2 flex items-center gap-2'>
            <a
              href='/?tab=heroes'
              className='text-xs font-semibold text-accent hover:underline flex items-center gap-1 transition-colors'
            >
              ← Библиотека героев
            </a>
            <span className='text-line' aria-hidden='true'>/</span>
            <p className='text-xs uppercase tracking-widest text-patina'>02 / Вместе с мастером</p>
          </div>
          <h2 className='font-heading text-2xl font-bold tracking-tight text-ink'>Беседа с мастером</h2>
          <p className='mt-1 text-sm text-muted leading-relaxed'>
            Уточняйте детали, задавайте вопросы и выбирайте то, что подходит вашему герою.
          </p>
        </div>
        <span className={`workshop-status ${isReady ? 'border-patina/50 text-patina bg-patina/10 font-semibold' : ''}`}>
          {isReady ? '✓ Готов к подтверждению' : 'Черновик сохранён'}
        </span>
      </header>

      {/* Раскрывающийся исходный замысел */}
      <details className='rounded-xl border border-line bg-surface-2/40 p-4 transition-colors hover:border-line-soft'>
        <summary className='cursor-pointer text-sm font-semibold text-ink'>
          Ваш замысел{draft.description.name ? `: ${draft.description.name}` : ''}
        </summary>
        <div className='mt-3 border-t border-line-soft pt-3'>
          <p className='whitespace-pre-wrap font-serif text-sm leading-relaxed text-muted'>{draft.description.identity}</p>
        </div>
      </details>

      {/* Лента сообщений: диалог с мастером */}
      <div className='flex flex-col gap-4'>
        {draft.transcript.filter(message => message.role === 'user' || message.role === 'assistant').map((message, index) => {
          const isUser = message.role === 'user';
          return (
            <div
              className={`workshop-message ${isUser ? 'is-user' : 'is-master'}`}
              key={index}
            >
              <div className='mb-2 flex items-center gap-2'>
                <span className='text-xs font-semibold uppercase tracking-widest text-patina'>
                  {isUser ? 'Вы' : '✧ Мастер историй'}
                </span>
              </div>
              <p className='whitespace-pre-wrap text-sm leading-relaxed text-ink'>{message.content}</p>
            </div>
          );
        })}
      </div>

      {/* Предложение характеристик от мастера */}
      {draft.proposal && (
        <section className='workshop-proposal rounded-2xl border border-patina/30 p-5 md:p-6 shadow-sm' aria-label='Предложение характеристик'>
          <div className='mb-5 flex flex-wrap items-baseline justify-between gap-2 border-b border-line-soft pb-4'>
            <div>
              <p className='text-xs uppercase tracking-widest text-patina font-semibold'>Предложение мастера</p>
              <h3 className='mt-1 font-heading text-xl font-bold text-ink'>Предложение характеристик</h3>
              {draft.description.name && <p className='mt-1 text-sm text-muted'>{draft.description.name}</p>}
            </div>
            <span className='text-xs text-muted'>Стартовый набор: 15, 14, 13, 12, 10, 8</span>
          </div>

          <div className='grid gap-3 sm:grid-cols-2 lg:grid-cols-3'>
            {abilityKeys.map(key => (
              <div
                className='flex flex-col justify-between rounded-xl border border-line bg-surface p-4 shadow-sm transition-all hover:border-patina'
                key={key}
              >
                <div className='flex items-center justify-between gap-3'>
                  <strong className='text-sm font-semibold uppercase tracking-wider text-muted'>{abilityNames[key]}</strong>
                  <span className='font-mono text-2xl font-bold text-accent'>{draft.proposal!.abilities[key]}</span>
                </div>
                <p className='mt-3 border-t border-line-soft pt-2 text-xs leading-relaxed text-muted'>
                  {draft.proposal!.explanations[key]}
                </p>
              </div>
            ))}
          </div>

          <div className='mt-4 flex items-center gap-2 text-xs leading-relaxed text-muted'>
            <span className='text-accent' aria-hidden='true'>ℹ</span>
            <span>
              Герой начнёт с первого уровня с оружием и бронёй. Освоенные приёмы появятся в игре. Карточка создастся только после вашего подтверждения.
            </span>
          </div>
          <div className='mt-5 border-t border-line-soft pt-5'><h4 className='mb-3 font-heading text-lg font-semibold'>Стартовое снаряжение</h4>
            {draft.proposal.equipment ? <StartingEquipmentList items={[draft.proposal.equipment.weapon, draft.proposal.equipment.armor]} /> :
              <div className='flex flex-col items-start gap-3'><p className='text-sm text-muted'>В этом сохранённом предложении ещё нет оружия и брони. Мастер подберёт их перед подтверждением.</p>
                <button type='button' className='btn' disabled={busy} onClick={() => void send(false, 'Подбери стартовое снаряжение по моему описанию: одно обычное оружие и одну обычную броню.')}>Подобрать снаряжение</button></div>}
          </div>
        </section>
      )}

      {/* Блок ввода ответа и подтверждения */}
      {draft.status === 'confirmed' ? (
        <div className='rounded-xl border border-patina/40 bg-patina/10 p-5 flex flex-col items-start gap-3'>
          <p className='text-sm font-semibold text-patina'>Герой успешно подтверждён и готов к приключениям!</p>
          <button className='btn btn-primary' onClick={() => onCreated(draft.hero_id!)}>
            Открыть героя
          </button>
        </div>
      ) : (
        <div className='flex flex-col gap-4 border-t border-line pt-5'>
          <label className='flex flex-col gap-2 text-sm font-semibold text-ink'>
            Ответ или уточнение замысла
            <textarea
              className='field workshop-field min-h-28 font-normal'
              placeholder='Например: герой больше полагается на знания, чем на силу. Как это отразить?'
              disabled={busy}
              value={answer}
              maxLength={4000}
              onChange={event => setAnswer(event.target.value)}
            />
          </label>

          <div className='flex flex-wrap items-center gap-3'>
            <button
              className='btn'
              disabled={busy || !answer.trim()}
              onClick={() => void send()}
            >
              Ответить мастеру
            </button>
            {isReady && (
              <button
                className='btn btn-primary shadow-md shadow-accent/20'
                disabled={busy || !draft.proposal?.equipment}
                onClick={() => void send(true)}
              >
                Подтвердить героя
              </button>
            )}
          </div>
        </div>
      )}

      {/* Оповещения статуса */}
      {busy && <p role='status' className='workshop-notice text-muted'>Мастер готовит ответ…</p>}
      {error && <p role='alert' className='workshop-notice border-bad text-bad'>{error}</p>}
      {error && (
        <button className='btn self-start' onClick={() => void query.refetch()}>
          Обновить предложение
        </button>
      )}

      {/* Удаление черновика */}
      {['questions', 'ready'].includes(draft.status) && (
        <div className='border-t border-line pt-4'>
          <DeleteHeroDraft draft={draft} onDeleted={onDeleted} disabled={busy} />
        </div>
      )}
    </section>
  );
}
