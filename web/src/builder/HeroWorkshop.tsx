import { useQuery, useQueryClient } from '@tanstack/react-query';
import { useState } from 'react';
import { Link, useNavigate, useParams, useSearchParams } from 'react-router-dom';
import Header from '../components/Header';
import { api } from '../lib/api';
import { emptyDescription, type HeroCard, type HeroDialogue } from '../lib/universal';
import HeroDescriptionForm from './HeroDescriptionForm';
import HeroCreationDialogue from './HeroCreationDialogue';
import HeroCardEditor from './HeroCardEditor';
import UniversalHeroCard from './UniversalHeroCard';
import DeleteHeroDraft from './DeleteHeroDraft';
import HeroDescriptionProgress from './HeroDescriptionProgress';
import HeroPortraitStudio from './HeroPortraitStudio';
import HeroEquipmentStudio from './HeroEquipmentStudio';

export default function HeroWorkshop() {
  const { hid } = useParams();
  const id = hid === 'new' ? undefined : hid;
  const [search, setSearch] = useSearchParams();
  const dialogueId = search.get('dialogue');
  const qc = useQueryClient(), navigate = useNavigate();
  const [description, setDescription] = useState(emptyDescription);
  const [error, setError] = useState(''), [busy, setBusy] = useState(false);
  const hero = useQuery({ queryKey: ['library', id], queryFn: () => api<HeroCard>(`/api/me/characters/${id}`), enabled: !!id });
  const pending = useQuery({ queryKey: ['hero-drafts'], queryFn: () => api<HeroDialogue[]>('/api/hero-creation/dialogues'), enabled: !id && !dialogueId });

  async function start() {
    setBusy(true); setError('');
    try {
      const draft = await api<HeroDialogue>('/api/hero-creation/dialogues', { body: { description } });
      qc.setQueryData(['hero-dialogue', draft.id], draft); setSearch({ dialogue: draft.id });
    } catch (err) { setError((err as Error).message); void pending.refetch(); } finally { setBusy(false); }
  }

  function created(heroId: string) { void qc.invalidateQueries({ queryKey: ['library'] }); navigate(`/heroes/${heroId}`, { replace: true }); }
  const drafts = pending.data?.filter(draft => !draft.campaign_id && ['questions', 'ready'].includes(draft.status)) ?? [];
  const step = id ? 2 : dialogueId ? 1 : 0;

  return <>
    <Header>
      <Link className='btn flex items-center gap-1.5' to='/?tab=heroes'>
        <span aria-hidden='true'>←</span> Библиотека героев
      </Link>
      <Link className='btn' to='/'>К столам</Link>
    </Header>
    <main className='workshop-page mx-auto flex max-w-6xl flex-col gap-6 px-4 py-6 md:px-8 md:py-8'>
      <header className='workshop-masthead relative overflow-hidden rounded-2xl border border-line p-6 md:p-8'>
        <div className='workshop-emblem' aria-hidden='true'>✧</div>
        <nav aria-label='Навигация' className='relative mb-2 flex items-center gap-2 text-xs font-semibold uppercase tracking-[0.16em] text-muted'>
          <Link to='/?tab=heroes' className='text-accent hover:underline flex items-center gap-1 transition-colors'>
            ← Библиотека героев
          </Link>
          <span className='text-line' aria-hidden='true'>/</span>
          <span>Мастерская героя</span>
        </nav>
        <h1 className='relative mt-3 font-heading text-3xl tracking-tight md:text-4xl'>Мастерская героя</h1>
        <p className='relative mt-3 max-w-xl text-sm leading-relaxed text-muted'>
          Большая история начинается с небольшого замысла. Опишите героя — мастер поможет превратить идею в игровую карточку.
        </p>
        <ol className='relative mt-7 flex gap-2 sm:gap-5' aria-label='Этапы создания героя'>
          {['Замысел', 'Беседа с мастером', 'Карточка героя'].map((label, index) => (
            <li
              key={label}
              aria-current={index === step ? 'step' : undefined}
              className={`workshop-step ${index === step ? 'is-current' : ''} ${index < step ? 'is-done' : ''}`}
            >
              <span className='workshop-step-number' aria-hidden='true'>
                {index < step ? '✓' : `0${index + 1}`}
              </span>
              <span>{label}</span>
            </li>
          ))}
        </ol>
      </header>

      {hero.error && <p role='alert' className='workshop-notice border-bad text-bad'>{hero.error.message}</p>}

      {id ? (
        hero.data ? (
          <>
            <UniversalHeroCard
              card={hero.data}
              equipmentActions={<HeroEquipmentStudio card={hero.data} onSaved={card => {
                qc.setQueryData(['library', id], card);
                void qc.invalidateQueries({ queryKey: ['library'], exact: true });
              }} />}
              portraitActions={
                <HeroPortraitStudio
                  card={hero.data}
                  endpoint={`/api/me/characters/${id}/portrait`}
                  onSaved={card => {
                    qc.setQueryData(['library', id], card);
                    void qc.invalidateQueries({ queryKey: ['library'], exact: true });
                  }}
                />
              }
            />
            <HeroCardEditor
              key={hero.data.id}
              card={hero.data}
              onReload={() => void hero.refetch()}
              onSaved={card => {
                qc.setQueryData(['library', id], card);
                void qc.invalidateQueries({ queryKey: ['library'], exact: true });
              }}
            />
          </>
        ) : (
          <p className='text-sm text-muted'>Загружаю карточку…</p>
        )
      ) : dialogueId ? (
        <HeroCreationDialogue id={dialogueId} onCreated={created} onDeleted={() => setSearch({})} />
      ) : (
        <>
          <div className='grid items-start gap-6 lg:grid-cols-[minmax(0,1fr)_330px]'>
            <form
              className='card flex min-w-0 flex-col gap-6 p-5 md:p-7'
              onSubmit={event => {
                event.preventDefault();
                void start();
              }}
            >
              <div className='border-b border-line pb-5'>
                <p className='text-xs uppercase tracking-widest text-patina'>01 / Замысел</p>
                <h2 className='mt-2 font-heading text-xl font-bold text-ink'>Каким будет ваш герой?</h2>
                <p className='mt-2 text-sm leading-relaxed text-muted'>
                  Не нужно знать правила или продумывать всё заранее. Начните с образа, который хочется сыграть.
                </p>
              </div>
              <HeroDescriptionForm value={description} onChange={setDescription} disabled={busy} />
              <div className='flex flex-col items-start gap-3 border-t border-line pt-5'>
                <button
                  className='btn btn-primary workshop-submit'
                  disabled={busy || !description.identity.trim()}
                >
                  {busy ? 'Мастер обдумывает замысел…' : 'Обсудить с мастером'}
                </button>
                <p className='text-xs leading-relaxed text-muted'>
                  {description.identity.trim()
                    ? 'Дальше — беседа и предложение характеристик. Вы решаете, когда подтвердить героя.'
                    : 'Расскажите, кто ваш герой, чтобы начать беседу.'}
                </p>
              </div>
              {busy && <p role='status' className='workshop-notice text-muted'>Мастер обдумывает ваш замысел…</p>}
              {error && <p role='alert' className='workshop-notice border-bad text-bad'>{error}</p>}
            </form>
            <HeroDescriptionProgress description={description} />
          </div>

          {pending.error && (
            <p role='alert' className='workshop-notice border-bad text-bad'>
              Не удалось загрузить черновики.{' '}
              <button type='button' className='underline' onClick={() => void pending.refetch()}>
                Повторить
              </button>
            </p>
          )}

          {drafts.length > 0 && (
            <section aria-label='Сохранённые черновики'>
              <div className='mb-4 flex flex-wrap items-baseline gap-3'>
                <h2 className='font-heading text-xl font-bold text-ink'>Продолжить историю</h2>
                <span className='text-xs text-muted'>Черновиков: {drafts.length}</span>
              </div>
              <div className='grid gap-3 sm:grid-cols-2'>
                {drafts.map(draft => (
                  <article
                    className='card workshop-draft flex min-w-0 items-center justify-between gap-3 p-5 shadow-sm'
                    key={draft.id}
                    aria-label={`Черновик: ${draft.description.name || draft.description.identity}`}
                  >
                    <button
                      className='min-w-0 flex-1 text-left'
                      aria-label={`Продолжить: ${draft.description.name || draft.description.identity}`}
                      onClick={() => setSearch({ dialogue: draft.id })}
                    >
                      <span className='mb-2 block text-xs text-patina'>
                        {draft.status === 'ready' ? '✓ Готов к подтверждению' : 'Беседа начата'}
                      </span>
                      <span className='block truncate font-semibold text-ink'>
                        {draft.description.name || draft.description.identity}
                      </span>
                      <span className='mt-2 block text-xs text-muted'>Продолжить беседу →</span>
                    </button>
                    <DeleteHeroDraft draft={draft} />
                  </article>
                ))}
              </div>
            </section>
          )}
        </>
      )}
    </main>
  </>;
}
