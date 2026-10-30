import { useEffect, useRef, useState } from 'react';
import ArtworkViewer from '../components/ArtworkViewer';
import { api, ApiError } from '../lib/api';
import { useAuthedImageResource } from '../lib/authedImage';

interface Artwork {
  status: 'idle' | 'pending' | 'ready' | 'failed';
  image_url: string | null; thumbnail_url: string | null;
  enabled: boolean; can_generate: boolean; can_regenerate?: boolean; error: string | null;
}

function Original({ url, name, onClose }: { url: string; name: string; onClose: () => void }) {
  const { src, error, retry } = useAuthedImageResource(url);
  return <ArtworkViewer src={src} name={name} label={`Предмет «${name}»`} alt={`Предмет «${name}»`} onClose={onClose} error={error} onRetry={retry} />;
}

function SavedImage({ art, name }: { art: Artwork; name: string }) {
  const { src, error, retry } = useAuthedImageResource(art.thumbnail_url!);
  const [open, setOpen] = useState(false);
  return <>
    {error ? (
      <div className='flex h-28 w-28 sm:h-32 sm:w-32 shrink-0 flex-col items-center justify-center rounded-xl border border-bad/30 bg-bad/5 p-2 text-center'>
        <p role='alert' className='text-[10px] leading-tight text-bad'>Не удалось загрузить миниатюру.</p>
        <button type='button' onClick={retry} className='mt-2 inline-flex items-center gap-1 rounded-md border border-bad/30 bg-surface px-2 py-1 text-[10px] text-bad hover:bg-bad/10 focus-visible:outline-2 focus-visible:outline-bad'>
          Повторить загрузку
        </button>
      </div>
    ) : (
      <button
        type='button'
        onClick={() => setOpen(true)}
        aria-label={`Рассмотреть ${name}`}
        className='group relative flex h-28 w-28 sm:h-32 sm:w-32 shrink-0 cursor-zoom-in items-center justify-center overflow-hidden rounded-xl border border-line-soft/80 bg-gradient-to-b from-surface-2 via-surface to-bg p-1.5 shadow-md shadow-black/25 transition-all duration-200 hover:border-accent/60 hover:shadow-lg hover:shadow-accent/10 focus-visible:outline-2 focus-visible:outline-accent'
      >
        <div className='pointer-events-none absolute inset-0 bg-radial from-accent/15 via-transparent to-transparent opacity-50 transition-opacity duration-300 group-hover:opacity-100' />
        <div className='relative flex h-full w-full items-center justify-center overflow-hidden rounded-lg bg-black/40 ring-1 ring-white/5'>
          {src ? (
            <img
              src={src}
              alt={`Предмет «${name}»`}
              className='h-full w-full object-contain drop-shadow-[0_4px_10px_rgba(0,0,0,0.5)] transition-transform duration-300 ease-out group-hover:scale-105'
            />
          ) : (
            <span className='flex flex-col items-center gap-1 p-1 text-[10px] text-muted'>
              <span className='h-4 w-4 animate-spin rounded-full border border-line border-t-accent/70' />
              <span>Загрузка…</span>
            </span>
          )}
        </div>
        <span
          className='pointer-events-none absolute bottom-1.5 right-1.5 flex items-center gap-1 rounded bg-black/80 px-1.5 py-0.5 font-mono text-[9px] font-medium text-white/90 backdrop-blur-xs opacity-0 transition-opacity duration-150 group-hover:opacity-100 shadow-xs'
          aria-hidden='true'
        >
          <span className='text-[10px]'>⤢</span>
          <span>Увеличить</span>
        </span>
      </button>
    )}
    {open && <Original url={art.image_url!} name={name} onClose={() => setOpen(false)} />}
  </>;
}

function ArtworkCard({ endpoint, name }: { endpoint: string; name: string }) {
  const [art, setArt] = useState<Artwork | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [reload, setReload] = useState(0);
  const active = useRef(true);
  const running = useRef(false);
  const key = useRef<{ value: string; regenerate: boolean } | null>(null);
  const revision = useRef(0);
  useEffect(() => {
    active.current = true;
    let alive = true;
    let timer: ReturnType<typeof setTimeout> | undefined;
    async function load() {
      const version = revision.current;
      try {
        const data = await api<Artwork>(endpoint);
        if (!alive || !data?.status) return;
        setError('');
        if (revision.current === version) setArt(data);
        if (!running.current && (data.status === 'failed' || data.status === 'ready')) key.current = null;
        // Other viewers may replace the selected image while this card remains mounted.
        if (data.enabled) timer = setTimeout(() => void load(), data.status === 'pending' ? 2500 : 15000);
      } catch {
        if (alive) { setError('Не удалось проверить изображение предмета.'); timer = setTimeout(() => void load(), 5000); }
      }
    }
    void load();
    return () => { alive = false; active.current = false; clearTimeout(timer); };
  }, [endpoint, reload]);

  async function generate(regenerate = false) {
    if (running.current) return;
    running.current = true;
    setBusy(true); setError('');
    if (!key.current || key.current.regenerate !== regenerate) key.current = { value: crypto.randomUUID(), regenerate };
    try {
      const result = await api<Artwork>(endpoint, { body: { request_key: key.current.value, regenerate } });
      if (!active.current) return;
      revision.current += 1;
      setArt(result); key.current = null;
    } catch (exc) {
      if (!active.current) return;
      const pending = exc instanceof ApiError && (exc.data as { detail?: { code?: string } })?.detail?.code === 'artwork_pending';
      if (!pending) {
        setError(exc instanceof Error ? exc.message : 'Не удалось создать изображение.');
        if (exc instanceof ApiError && exc.status < 500 && exc.status !== 408) key.current = null;
      }
    } finally {
      running.current = false;
      if (active.current) { setBusy(false); setReload(value => value + 1); }
    }
  }
  if (art && !art.enabled && !art.image_url) return null;
  const pending = busy || art?.status === 'pending';
  return (
    <div className='flex flex-col items-center sm:items-start gap-2' aria-label={`Изображение предмета ${name}`}>
      {art?.thumbnail_url && art.image_url && <SavedImage key={art.image_url} art={art} name={name} />}
      {art?.can_generate && (
        <button
          type='button'
          disabled={pending}
          onClick={() => void generate()}
          aria-label={`Создать изображение ${name}`}
          className='btn btn-outline-copper group relative flex h-28 w-28 sm:h-32 sm:w-32 shrink-0 flex-col items-center justify-center gap-1.5 p-2 text-center transition-all hover:bg-accent/10 focus-visible:outline-2 focus-visible:outline-accent disabled:opacity-60 disabled:cursor-not-allowed shadow-2xs'
        >
          <span
            className='flex h-8 w-8 items-center justify-center rounded-lg border border-accent/40 bg-surface text-accent transition-transform duration-200 group-hover:scale-110 shadow-2xs'
            aria-hidden='true'
          >
            {pending ? <span className='animate-spin text-sm'>↻</span> : <span className='text-sm'>✨</span>}
          </span>
          <span className='text-[11px] font-semibold leading-tight text-ink group-hover:text-accent'>
            {pending ? 'Создаётся изображение…' : 'Создать изображение'}
          </span>
        </button>
      )}
      {art?.can_regenerate && (
        <button
          type='button'
          disabled={pending}
          onClick={() => void generate(true)}
          aria-label={`Пересоздать изображение ${name}`}
          className='btn btn-outline-copper group/btn inline-flex w-28 sm:w-32 items-center justify-center gap-1.5 py-1 px-2 text-[11px] font-semibold text-ink transition-all hover:bg-accent/10 focus-visible:outline-2 focus-visible:outline-accent disabled:opacity-60 disabled:cursor-not-allowed shadow-2xs'
        >
          <span className={`text-xs ${pending ? 'animate-spin' : 'transition-transform group-hover/btn:rotate-180'}`} aria-hidden='true'>
            ↻
          </span>
          <span>{pending ? 'Создаётся замена…' : 'Пересоздать'}</span>
        </button>
      )}
      {pending && <p role='status' className='text-[10px] text-muted text-center sm:text-left'>Можно продолжать игру.</p>}
      {(error || art?.error) && <p role='alert' className='text-[11px] text-bad text-center sm:text-left'>{error || art?.error}</p>}
    </div>
  );
}

export default function EquipmentArtwork({ campaignId, heroId, itemId, name, description = '' }: {
  campaignId: string; heroId: string; itemId: string; name: string; description?: string;
}) {
  const endpoint = `/api/campaigns/${campaignId}/characters/${heroId}/items/${itemId}/artwork`;
  return <ArtworkCard key={`${endpoint}:${name}:${description}`} endpoint={endpoint} name={name} />;
}

export function EquipmentArtworkAt({ endpoint, name, description = '' }: { endpoint: string; name: string; description?: string }) {
  return <ArtworkCard key={`${endpoint}:${name}:${description}`} endpoint={endpoint} name={name} />;
}
