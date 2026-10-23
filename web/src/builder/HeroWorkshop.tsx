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
  return <><Header><Link className='btn' to='/'>К столам</Link></Header>
    <main className='mx-auto flex max-w-5xl flex-col gap-6 px-4 py-6 md:px-8'>
      <header><p className='text-xs uppercase tracking-widest text-accent'>Личная библиотека</p><h1 className='font-heading text-3xl'>Мастерская героя</h1>
        <p className='mt-2 text-sm text-muted'>Опишите героя и обсудите замысел с мастером. Каждый герой начинает с первого уровня.</p></header>
      {hero.error && <p role='alert'>{hero.error.message}</p>}
      {id ? hero.data ? <><UniversalHeroCard card={hero.data} />
        <HeroCardEditor key={hero.data.id} card={hero.data} onReload={() => void hero.refetch()} onSaved={card => { qc.setQueryData(['library', id], card); void qc.invalidateQueries({ queryKey: ['library'], exact: true }); }} />
      </> : <p>Загружаю карточку…</p> : dialogueId ? <HeroCreationDialogue id={dialogueId} onCreated={created} onDeleted={() => setSearch({})} /> : <>
        <form className='card flex flex-col gap-5 p-5' onSubmit={event => { event.preventDefault(); void start(); }}>
          <HeroDescriptionForm value={description} onChange={setDescription} disabled={busy} />
          <button className='btn btn-primary self-start' disabled={busy || !description.identity.trim()}>Обсудить с мастером</button>
          {busy && <p role='status'>Мастер обдумывает ваш замысел…</p>}{error && <p role='alert'>{error}</p>}
        </form>
        {pending.data?.filter(draft => !draft.campaign_id && ['questions', 'ready'].includes(draft.status)).map(draft =>
          <article className='card flex items-center justify-between gap-3 p-4' key={draft.id}
            aria-label={`Черновик: ${draft.description.name || draft.description.identity}`}>
            <button className='min-w-0 flex-1 text-left' onClick={() => setSearch({ dialogue: draft.id })}>Продолжить: {draft.description.name || draft.description.identity}</button>
            <DeleteHeroDraft draft={draft} />
          </article>)}
      </>}
    </main></>;
}
