import { useState } from 'react';
import { api } from '../lib/api';
import { abilityKeys, abilityNames, type AbilityKey, type EditProposal, type HeroCard, type HeroEdit } from '../lib/universal';
import HeroDescriptionForm from './HeroDescriptionForm';

export default function HeroCardEditor({
  card,
  onSaved,
  onReload,
}: {
  card: HeroCard;
  onSaved: (card: HeroCard) => void;
  onReload: () => void;
}) {
  const [tab, setTab] = useState<'manual' | 'master'>('manual');
  const [description, setDescription] = useState(card.sheet.description);
  const [scores, setScores] = useState(card.sheet.abilities);
  const [baseRevision, setBaseRevision] = useState(card.revision);
  const [message, setMessage] = useState('');
  const [error, setError] = useState('');
  const [status, setStatus] = useState('');
  const [busy, setBusy] = useState(false);
  const [preview, setPreview] = useState<{
    edit: HeroEdit;
    id?: string;
    explanations?: EditProposal['explanations'];
    key: string;
  } | null>(null);

  if (!card.editable) return null;
  const url = `/api/me/characters/${card.id}`;

  function swap(key: AbilityKey, value: string) {
    const other = abilityKeys.find(k => scores[k] === value)!;
    setScores({ ...scores, [key]: value, [other]: scores[key] });
    setPreview(null);
  }

  async function propose() {
    setBusy(true);
    setError('');
    setStatus('');
    try {
      const result = await api<EditProposal>(url + '/edit-proposals', {
        body: { message, expected_revision: baseRevision },
      });
      setPreview({ ...result, key: crypto.randomUUID() });
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  }

  async function save() {
    if (!preview) return;
    setBusy(true);
    setError('');
    try {
      const saved = preview.id
        ? await api<HeroCard>(url + `/edit-proposals/${preview.id}/confirm`, { body: { request_key: preview.key } })
        : await api<HeroCard>(url, { method: 'PATCH', body: { edit: preview.edit, request_key: preview.key } });
      onSaved(saved);
      setDescription(saved.sheet.description);
      setScores(saved.sheet.abilities);
      setBaseRevision(saved.revision);
      setPreview(null);
      setStatus('Сохранено');
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className='card flex flex-col gap-6 p-6 md:p-8' aria-label='Редактор базового героя'>
      {/* Шапка редактора */}
      <header className='flex flex-wrap items-center justify-between gap-4 border-b border-line pb-5'>
        <div>
          <h2 className='font-heading text-2xl font-bold tracking-tight text-ink'>Изменить образ</h2>
          <p className='mt-1 text-sm text-muted'>
            Настройте карточку вручную или опишите пожелания мастеру для автоматической корректировки.
          </p>
        </div>

        {/* Переключатель вкладок: Вручную / Через мастера */}
        <div className='flex rounded-xl border border-line bg-surface-2/60 p-1' role='tablist' aria-label='Режимы редактирования'>
          <button
            type='button'
            role='tab'
            aria-selected={tab === 'manual'}
            className={`rounded-lg px-4 py-2 text-xs font-semibold transition-all ${
              tab === 'manual'
                ? 'bg-surface text-ink shadow-sm border border-line'
                : 'text-muted hover:text-ink'
            }`}
            onClick={() => setTab('manual')}
          >
            ✎ Ручная настройка
          </button>
          <button
            type='button'
            role='tab'
            aria-selected={tab === 'master'}
            className={`rounded-lg px-4 py-2 text-xs font-semibold transition-all ${
              tab === 'master'
                ? 'bg-surface text-ink shadow-sm border border-line'
                : 'text-muted hover:text-ink'
            }`}
            onClick={() => setTab('master')}
          >
            ✧ Попросить мастера
          </button>
        </div>
      </header>

      {/* Вкладка 1: Ручная настройка (Текст и перестановка характеристик) */}
      <div className={tab === 'manual' ? 'flex flex-col gap-6' : 'hidden'}>
        <HeroDescriptionForm
          value={description}
          onChange={value => {
            setDescription(value);
            setPreview(null);
          }}
          disabled={busy}
        />

        <fieldset className='rounded-2xl border border-line bg-surface-2/40 p-5'>
          <div className='mb-4'>
            <legend className='text-xs font-bold uppercase tracking-wider text-patina'>
              Перестановка стартового набора
            </legend>
            <p className='mt-1 text-xs text-muted'>
              Фиксированный бюджет: 15, 14, 13, 12, 10, 8. Каждое значение используется ровно один раз. При выборе занятого значения характеристики меняются местами.
            </p>
          </div>

          <div className='grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-6'>
            {abilityKeys.map(key => {
              const val = Number(scores[key]);
              const mod = Math.floor((val - 10) / 2);
              const modSign = mod >= 0 ? '+' : '';
              return (
                <div key={key} className='flex flex-col gap-2 rounded-xl border border-line bg-surface p-3 shadow-sm'>
                  <div className='flex items-center justify-between'>
                    <label htmlFor={`score-${key}`} className='text-xs font-semibold uppercase tracking-wider text-muted'>
                      {abilityNames[key]}
                    </label>
                    <span className={`text-[0.68rem] font-mono font-bold ${mod > 0 ? 'text-patina' : mod < 0 ? 'text-bad' : 'text-muted'}`}>
                      {modSign}{mod}
                    </span>
                  </div>

                  <select
                    id={`score-${key}`}
                    className='field font-mono font-bold text-base'
                    aria-label={`${abilityNames[key]}: значение`}
                    value={scores[key]}
                    disabled={busy}
                    onChange={event => swap(key, event.target.value)}
                  >
                    {['15', '14', '13', '12', '10', '8'].map(value => (
                      <option key={value} value={value}>
                        {value}
                      </option>
                    ))}
                  </select>
                </div>
              );
            })}
          </div>
        </fieldset>

        <button
          type='button'
          className='btn btn-primary self-start'
          disabled={busy}
          onClick={() => {
            setStatus('');
            setError('');
            setPreview({
              edit: { description_patch: description, base_scores: scores, expected_revision: baseRevision },
              key: crypto.randomUUID(),
            });
          }}
        >
          Предпросмотр правок
        </button>
      </div>

      {/* Вкладка 2: Правка через мастера */}
      <div className={tab === 'master' ? 'flex flex-col gap-5' : 'hidden'}>
        <div className='rounded-xl border border-line-soft bg-surface-2/40 p-4'>
          <p className='text-xs font-semibold uppercase tracking-wider text-patina'>Пожелания мастеру</p>
          <p className='mt-1 text-xs text-muted leading-relaxed'>
            Напишите, что именно нужно изменить в образе или характеристиках. Мастер скорректирует карточку в рамках правил системы и предложит обоснования.
          </p>
        </div>

        <label className='flex flex-col gap-2 text-sm font-semibold text-ink'>
          Правка через мастера
          <textarea
            className='field workshop-field min-h-28 font-normal'
            placeholder='Например: сделай героя более выносливым и практичным, сместив акцент с ловкости на телосложение...'
            value={message}
            maxLength={4000}
            disabled={busy}
            onChange={event => {
              setMessage(event.target.value);
              setTab('master');
            }}
          />
        </label>

        <button
          type='button'
          className='btn btn-primary self-start shadow-md shadow-accent/20'
          disabled={busy || !message.trim()}
          onClick={() => void propose()}
        >
          Предложить версию
        </button>
      </div>

      {/* Конфликт ревизий (карточка обновилась в фоне) */}
      {card.revision !== baseRevision && (
        <div className='rounded-xl border border-warn bg-warn/10 p-4 flex flex-col gap-2'>
          <p className='text-sm text-ink font-medium'>
            Сохранённая карточка обновилась. Сверьте её выше с вашим черновиком перед повторным сохранением.
          </p>
          <button
            type='button'
            className='btn self-start'
            disabled={busy}
            onClick={() => {
              setBaseRevision(card.revision);
              setPreview(null);
              setError('');
            }}
          >
            Продолжить с моим черновиком
          </button>
        </div>
      )}

      {/* Блок предпросмотра правок перед сохранением */}
      {preview && (
        <section
          className='rounded-2xl border border-accent/40 bg-surface-2/70 p-5 md:p-6 flex flex-col gap-4 shadow-md'
          aria-label='Предпросмотр правок'
        >
          <div className='border-b border-line-soft pb-3'>
            <h3 className='font-heading text-lg font-bold text-ink'>Предложение для подтверждения</h3>
            <p className='mt-1 text-xs text-muted'>Проверьте изменения перед записью в библиотеку.</p>
          </div>

          {/* Текстовые изменения описания */}
          {preview.edit.description_patch && (
            <div className='flex flex-col gap-2'>
              {Object.entries(preview.edit.description_patch).map(([key, value]) => (
                <p key={key} className='whitespace-pre-wrap text-sm leading-relaxed text-ink'>
                  {value}
                </p>
              ))}
            </div>
          )}

          {/* Характеристики */}
          <div className='grid gap-2 sm:grid-cols-2 lg:grid-cols-3 border-t border-line-soft pt-3'>
            {abilityKeys.map(key => (
              <p key={key} className='text-sm font-medium text-ink'>
                {abilityNames[key]}: {preview.edit.base_scores?.[key] ?? scores[key]}
                {preview.explanations ? ` — ${preview.explanations[key]}` : ''}
              </p>
            ))}
          </div>

          <p className='text-xs text-muted'>
            Изменения будут сохранены после подтверждения. Игровые копии живут отдельно.
          </p>

          <div className='flex flex-wrap gap-3 pt-2'>
            <button
              type='button'
              className='btn btn-primary shadow-md shadow-accent/20'
              disabled={busy}
              onClick={() => void save()}
            >
              Подтвердить правки
            </button>
            <button
              type='button'
              className='btn'
              disabled={busy}
              onClick={() => setPreview(null)}
            >
              Отменить
            </button>
          </div>
        </section>
      )}

      {/* Статусы и ошибки */}
      {busy && <p role='status' className='workshop-notice text-muted'>Готовлю предложение…</p>}
      {status && <p role='status' className='workshop-notice border-patina/50 bg-patina/10 text-patina font-semibold'>{status}</p>}
      {error && <p role='alert' className='workshop-notice border-bad text-bad'>{error}</p>}
      {error && (
        <button type='button' className='btn self-start' onClick={onReload}>
          Обновить сохранённую карточку
        </button>
      )}
    </section>
  );
}
