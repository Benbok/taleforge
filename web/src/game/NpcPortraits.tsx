import { useEffect, useRef, useState } from 'react';
import ArtworkViewer from '../components/ArtworkViewer';
import { api, ApiError } from '../lib/api';
import { useAuthedImageResource } from '../lib/authedImage';

interface Variant { id: string; image_url: string; thumbnail_url: string }
interface Portraits {
  status: 'idle' | 'pending' | 'ready' | 'failed'; selected_id: string | null;
  variants: Variant[]; enabled: boolean; can_generate: boolean; can_select: boolean; error: string | null;
}

function Original({ variant, name, close }: { variant: Variant; name: string; close: () => void }) {
  const { src, error, retry } = useAuthedImageResource(variant.image_url);
  return <ArtworkViewer src={src} error={error} onRetry={retry} onClose={close} name={name}
    label={`Портрет ${name}`} alt={`Портрет ${name}`} />;
}

function Preview({ variant, name, selected }: { variant: Variant; name: string; selected: boolean }) {
  const { src, error, retry } = useAuthedImageResource(variant.thumbnail_url);
  const [open, setOpen] = useState(false);
  return <>
    {error ? <button type='button' className='btn-ghost text-xs' onClick={retry}>Повторить загрузку</button>
      : <button type='button' onClick={() => setOpen(true)} aria-label={`Рассмотреть портрет ${name}`}
        className={`group relative block overflow-hidden rounded-xl border border-line-soft/80 bg-surface shadow-xs transition-all duration-200 hover:border-accent/60 hover:shadow-md focus-visible:outline-2 focus-visible:outline-accent ${selected ? 'w-full' : 'w-24'}`}>
        {src ? (
          <>
            <img src={src} alt={`Портрет ${name}`} className={`aspect-square object-contain transition-transform duration-300 ease-out group-hover:scale-105 ${selected ? 'max-h-64 w-full' : 'w-24'}`} />
            <span
              className='pointer-events-none absolute bottom-1 right-1 flex items-center gap-0.5 rounded bg-black/80 px-1 py-0.5 font-mono text-[8px] font-medium text-white/90 backdrop-blur-xs opacity-0 transition-opacity duration-150 group-hover:opacity-100'
              aria-hidden='true'
            >
              <span>⤢</span>
            </span>
          </>
        ) : <span className='block p-4 text-xs text-muted'>Загрузка…</span>}
      </button>}
    {open && <Original variant={variant} name={name} close={() => setOpen(false)} />}
  </>;
}

function PortraitCard({ endpoint, name }: { endpoint: string; name: string }) {
  const [data, setData] = useState<Portraits | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [reload, setReload] = useState(0);
  const active = useRef(true);
  const running = useRef(false);
  const key = useRef<string | null>(null);
  const revision = useRef(0);
  useEffect(() => {
    active.current = true;
    let alive = true;
    let timer: ReturnType<typeof setTimeout> | undefined;
    async function load() {
      const version = revision.current;
      try {
        const result = await api<Portraits>(endpoint);
        if (!alive) return;
        if (version === revision.current) { setData(result); setError(''); }
        if (!running.current && (result.status === 'failed' || result.status === 'ready')) key.current = null;
        if (result.enabled) timer = setTimeout(() => void load(), result.status === 'pending' ? 2500 : 15000);
      } catch { if (alive) { setError('Не удалось загрузить портреты.'); timer = setTimeout(() => void load(), 5000); } }
    }
    void load();
    return () => { alive = false; active.current = false; clearTimeout(timer); };
  }, [endpoint, reload]);

  async function generate() {
    if (running.current) return;
    running.current = true;
    setBusy(true); setError('');
    if (!key.current) key.current = crypto.randomUUID();
    try {
      const result = await api<Portraits>(endpoint, { body: { request_key: key.current } });
      if (!active.current) return;
      revision.current += 1;
      setData(result); key.current = null;
    } catch (exc) {
      if (!active.current) return;
      const pending = exc instanceof ApiError && (exc.data as { detail?: { code?: string } })?.detail?.code === 'portrait_pending';
      if (!pending) {
        setError(exc instanceof Error ? exc.message : 'Не удалось обновить портрет.');
        if (exc instanceof ApiError && exc.status < 500 && exc.status !== 408) key.current = null;
      }
    } finally {
      running.current = false;
      if (active.current) { setBusy(false); setReload(value => value + 1); }
    }
  }

  async function select(imageId: string) {
    if (running.current) return;
    running.current = true;
    setBusy(true); setError('');
    try {
      const result = await api<Portraits>(endpoint, { method: 'PUT', body: { image_id: imageId } });
      if (!active.current) return;
      revision.current += 1;
      setData(result);
    } catch (exc) {
      if (!active.current) return;
      setError(exc instanceof Error ? exc.message : 'Не удалось применить портрет.');
    } finally {
      running.current = false;
      if (active.current) { setBusy(false); setReload(value => value + 1); }
    }
  }

  if (data && !data.enabled && !data.variants.length) return null;
  const pending = busy || data?.status === 'pending';
  const selected = data?.variants.find(entry => entry.id === data.selected_id);
  const alternatives = data?.variants.filter(entry => entry.id !== data?.selected_id) ?? [];

  return <div className='space-y-2' aria-label={`Портрет ${name}`}>
    {selected && (
      <div className='space-y-1'>
        <p className='text-xs font-medium text-ink'>Выбранный портрет</p>
        <Preview key={selected.id} variant={selected} name={name} selected={true} />
      </div>
    )}
    {alternatives.length > 0 && (
      <div className='space-y-1.5'>
        {selected && <p className='text-xs text-muted'>Другие варианты</p>}
        <div className='flex gap-2 overflow-x-auto py-1'>
          {data?.variants.map((variant, index) => {
            if (variant.id === data?.selected_id) return null;
            return (
              <div key={variant.id} className='flex flex-col items-center gap-1.5'>
                <Preview variant={variant} name={name} selected={false} />
                {data?.can_select && (
                  <button
                    type='button'
                    disabled={pending}
                    onClick={() => void select(variant.id)}
                    aria-label={`Применить вариант ${index + 1}`}
                    className='btn-ghost px-2 py-0.5 text-[11px]'
                  >
                    Применить вариант {index + 1}
                  </button>
                )}
              </div>
            );
          })}
        </div>
      </div>
    )}
    {data?.can_generate && <button type='button' disabled={pending} onClick={() => void generate()}
      className='btn-ghost min-h-10 px-3 py-1.5 text-xs'>
      {pending ? 'Создаётся вариант…' : data?.variants.length ? 'Предложить ещё вариант' : 'Создать портрет'}
    </button>}
    {pending && <p role='status' className='text-xs text-muted'>Художник пишет портрет… Можно продолжать игру.</p>}
    {(error || data?.error) && <p role='alert' className='text-xs text-bad'>{error || data?.error}</p>}
  </div>;
}

export function NpcPortraitsAt({ endpoint, name }: { endpoint: string; name: string; description?: string }) {
  return <PortraitCard endpoint={endpoint} name={name} />;
}

export default function NpcPortraits({ campaignId, npcId, name }: { campaignId: string; npcId: string; name: string; description?: string }) {
  return <PortraitCard endpoint={`/api/campaigns/${campaignId}/npcs/${npcId}/portraits`} name={name} />;
}
